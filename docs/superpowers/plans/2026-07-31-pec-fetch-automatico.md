# PEC fetch automatico (IMAP) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sostituire lo scarico manuale degli mbox dalla webmail PEC con un job notturno che legge quattro caselle via IMAP in sola lettura e le consegna alla pipeline di lineage esistente.

**Architecture:** Un fetcher IMAP produce lo stesso artefatto che oggi Stefano scarica a mano (un `.eml` per busta) e chiama `intake_file()` + `promote_raw_object()`. Nulla a valle cambia: parser, classificazione e pannello restano quelli di `2026-07-17`. Il fetcher sa di IMAP e non sa nulla di PEC; il parser sa di PEC e non sa nulla di come è arrivato il file.

**Tech Stack:** Python ≥3.11, `imaplib` (stdlib — nessuna dipendenza nuova), `google-cloud-storage` (già presente), pytest.

**Spec:** `docs/superpowers/specs/2026-07-31-pec-fetch-automatico-design.md`

## Global Constraints

- **Sola lettura assoluta.** `select(..., readonly=True)` sempre. Nessun flag, nessun `\Seen`, nessuna label lato server. Sono caselle con valore probatorio.
- **SMTP mai configurato.** La porta 465 non compare in nessun file. Un ingest non invia.
- **Nessuna password nel repo.** Le password PEC arrivano da variabile d'ambiente (`PEC_PASSWORD_<ENTITY>`), popolata da Secret Manager in cloud. `core/source_registry.yaml` contiene host, porta e utente — mai la password.
- **`core/schemas.py:23` non si tocca.** `SocietaId = Literal["ORTI", "INTUR"]` resta com'è: VIGNA entra nell'identità *lineage*, non nella contabilità.
- **Idempotenza:** il watermark è ottimizzazione, il content-hash all'intake è la correttezza. Nessun task può affidarsi al solo watermark.
- Stile: `ruff check .` e `ruff format .` puliti prima di ogni commit.

## File Structure

| File | Responsabilità |
|---|---|
| `core/lineage/schemas.py` (modifica) | Allarga l'identità lineage a VIGNA/STEFANO; aggiunge il blocco config IMAP |
| `core/source_registry.yaml` (modifica) | Tre nuove sorgenti PEC + config IMAP sulle quattro |
| `ingest/pec_watermark.py` (nuovo) | Legge/scrive l'ultimo UID visto per casella, su GCS |
| `ingest/pec_imap.py` (nuovo) | Client IMAP read-only: dato un UID di partenza, restituisce le buste nuove |
| `ingest/pec_fetch.py` (nuovo) | CLI e orchestrazione: fetch → intake → promote → avanza watermark |
| `tests/test_pec_watermark.py` (nuovo) | |
| `tests/test_pec_imap.py` (nuovo) | |
| `tests/test_pec_fetch.py` (nuovo) | |

`pec_imap.py` non importa nulla di hotelops: è un client IMAP generico e testabile da solo. `pec_fetch.py` è l'unico che conosce sia IMAP sia il lineage.

---

### Task 1: Identità lineage per VIGNA e STEFANO

La grammatica dei source name valida lo slot società contro `SOCIETA_VALUES`, oggi `("ORTI", "INTUR", "GROUP")`. `PEC_MAILBOX_VIGNA_APPEND` verrebbe rifiutato.

**Files:**
- Modify: `core/lineage/schemas.py:47` (`SOCIETA_VALUES`) e `:122` (campo `societa`)
- Test: `tests/test_lineage_schemas.py` (se non esiste, crearlo)

**Interfaces:**
- Consumes: niente
- Produces: `SOCIETA_VALUES = ("ORTI", "INTUR", "GROUP", "VIGNA", "STEFANO")`; `SourceDefinition.societa: Literal["ORTI", "INTUR", "GROUP", "VIGNA", "STEFANO"]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lineage_schemas.py
import pytest

from core.lineage.schemas import validate_source_name


def test_vigna_is_a_valid_lineage_societa() -> None:
    system, dataset, societa, lifecycle = validate_source_name("PEC_MAILBOX_VIGNA_APPEND")
    assert societa == "VIGNA"


def test_stefano_is_a_valid_lineage_societa() -> None:
    _, _, societa, _ = validate_source_name("PEC_MAILBOX_STEFANO_APPEND")
    assert societa == "STEFANO"


def test_unknown_societa_is_still_rejected() -> None:
    with pytest.raises(ValueError, match="societa"):
        validate_source_name("PEC_MAILBOX_PIPPO_APPEND")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lineage_schemas.py -v`
Expected: FAIL — `ValueError: 'PEC_MAILBOX_VIGNA_APPEND': societa 'VIGNA' must be one of ['ORTI', 'INTUR', 'GROUP']`

- [ ] **Step 3: Write minimal implementation**

In `core/lineage/schemas.py` riga 47:

```python
SOCIETA_VALUES = ("ORTI", "INTUR", "GROUP", "VIGNA", "STEFANO")
```

E il campo del modello (riga ~122):

```python
    societa: Literal["ORTI", "INTUR", "GROUP", "VIGNA", "STEFANO"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_lineage_schemas.py tests/test_drive_fetch.py -v`
Expected: PASS — inclusi i test esistenti di `test_drive_fetch.py`, che costruiscono `SourceDefinition` e non devono rompersi.

- [ ] **Step 5: Commit**

```bash
git add core/lineage/schemas.py tests/test_lineage_schemas.py
git commit -m "feat(lineage): VIGNA e STEFANO come identità lineage valide

Slot società della grammatica 4-part allargato per le caselle PEC delle
altre entità. Riguarda solo il registro lineage: core/schemas.py::SocietaId
resta ORTI|INTUR — la vigna non entra nella contabilità."
```

---

### Task 2: Config IMAP nel SourceDefinition

**Files:**
- Modify: `core/lineage/schemas.py` (nuovo modello `ImapMailbox` + campo opzionale su `SourceDefinition`)
- Test: `tests/test_lineage_schemas.py`

**Interfaces:**
- Consumes: Task 1
- Produces: `ImapMailbox(host: str, port: int = 993, user: str, password_env: str)`; `SourceDefinition.imap: Optional[ImapMailbox] = None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lineage_schemas.py — aggiungere in coda
from core.lineage.schemas import ImapMailbox, RawStorage, SourceDefinition


def _pec_source_def(**overrides) -> SourceDefinition:
    base = dict(
        source_name="PEC_MAILBOX_VIGNA_APPEND",
        system="PEC",
        dataset="MAILBOX",
        societa="VIGNA",
        lifecycle="APPEND",
        canonical_table="f_pec_messages",
        parser_module="ingest.flussi.ingest_pec_mbox",
        promotion_policy="AUTO",
        detector_category="pec_mbox",
        loop_targets=["pec_archive"],
        raw_storage=RawStorage(
            backend="gcs", bucket="vigna-raw", path_template="pec/mailbox/VIGNA"
        ),
    )
    base.update(overrides)
    return SourceDefinition(**base)


def test_imap_config_is_optional() -> None:
    assert _pec_source_def().imap is None


def test_imap_config_roundtrip() -> None:
    sd = _pec_source_def(
        imap=ImapMailbox(
            host="imaps.pec.aruba.it",
            user="vineyardamalficoast@pec.it",
            password_env="PEC_PASSWORD_VIGNA",
        )
    )
    assert sd.imap.host == "imaps.pec.aruba.it"
    assert sd.imap.port == 993
    assert sd.imap.password_env == "PEC_PASSWORD_VIGNA"


def test_imap_config_has_no_password_field() -> None:
    """La password non deve poter finire nel registry."""
    assert "password" not in ImapMailbox.model_fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lineage_schemas.py -v -k imap`
Expected: FAIL — `ImportError: cannot import name 'ImapMailbox'`

- [ ] **Step 3: Write minimal implementation**

In `core/lineage/schemas.py`, accanto a `RawStorage`:

```python
class ImapMailbox(BaseModel):
    """Config di una casella IMAP in sola lettura.

    La password NON sta qui: `password_env` nomina la variabile d'ambiente
    che la contiene (popolata da Secret Manager in cloud).
    """

    host: str
    port: int = 993
    user: str
    password_env: str
```

E su `SourceDefinition`, accanto a `drive_file_id`:

```python
    imap: Optional[ImapMailbox] = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_lineage_schemas.py -v`
Expected: PASS (tutti)

- [ ] **Step 5: Commit**

```bash
git add core/lineage/schemas.py tests/test_lineage_schemas.py
git commit -m "feat(lineage): blocco config IMAP sul SourceDefinition

host/porta/utente nel registry, password solo via env (password_env) —
il modello non ha proprio un campo password, così non ci può finire."
```

---

### Task 3: Le quattro caselle nel registry

**Files:**
- Modify: `core/source_registry.yaml` (blocco PEC, dopo `PEC_MAILBOX_INTUR_APPEND` a riga ~795)
- Test: `tests/test_pec_registry.py` (nuovo)

**Interfaces:**
- Consumes: Task 1, Task 2
- Produces: quattro sorgenti `PEC_MAILBOX_{INTUR,ORTI,VIGNA,STEFANO}_APPEND`, ognuna con blocco `imap`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pec_registry.py
import pytest

from core.lineage.source_resolver import load_registry

PEC_SOURCES = [
    ("PEC_MAILBOX_INTUR_APPEND", "in.tur@pec.it", "imaps.pec.aruba.it", "hotelops-raw"),
    ("PEC_MAILBOX_ORTI_APPEND", "orti@pec.it", "imaps.pec.aruba.it", "orti-raw"),
    ("PEC_MAILBOX_VIGNA_APPEND", "vineyardamalficoast@pec.it", "imaps.pec.aruba.it", "vigna-raw"),
]


@pytest.mark.parametrize("name,user,host,bucket", PEC_SOURCES)
def test_pec_source_has_imap_config(name, user, host, bucket) -> None:
    sd = load_registry().get(name)
    assert sd is not None, f"{name} assente dal registry"
    assert sd.imap is not None, f"{name} senza blocco imap"
    assert sd.imap.user == user
    assert sd.imap.host == host
    assert sd.imap.port == 993
    assert sd.raw_storage.bucket == bucket


@pytest.mark.parametrize("name,_u,_h,_b", PEC_SOURCES)
def test_pec_sources_share_parser_and_loop(name, _u, _h, _b) -> None:
    sd = load_registry().get(name)
    assert sd.parser_module == "ingest.flussi.ingest_pec_mbox"
    assert sd.canonical_table == "f_pec_messages"
    assert sd.loop_targets == ["pec_archive"]


def test_no_smtp_anywhere_in_registry() -> None:
    """Un ingest non invia: smtp non deve comparire nel registry."""
    text = open("core/source_registry.yaml", encoding="utf-8").read().lower()
    assert "smtp" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pec_registry.py -v`
Expected: FAIL — `PEC_MAILBOX_ORTI_APPEND assente dal registry`

- [ ] **Step 3: Write minimal implementation**

Aggiungere il blocco `imap` a `PEC_MAILBOX_INTUR_APPEND` (esistente):

```yaml
    imap:
      host: imaps.pec.aruba.it
      port: 993
      user: in.tur@pec.it
      password_env: PEC_PASSWORD_INTUR
```

E le tre nuove sorgenti subito dopo:

```yaml
  # ── PEC orti@pec.it ──────────────────────────────────────────────────────
  PEC_MAILBOX_ORTI_APPEND:
    system: PEC
    dataset: MAILBOX
    dataset_label: "PEC orti@pec.it — buste ricevute + messaggi inviati"
    societa: ORTI
    business_unit: null
    lifecycle: APPEND
    canonical_table: f_pec_messages
    parser_module: ingest.flussi.ingest_pec_mbox
    hash_basis: msgid
    loop_targets: [pec_archive]
    promotion_policy: AUTO
    detector_category: pec_mbox
    raw_storage:
      backend: gcs
      bucket: orti-raw
      path_template: "pec/mailbox/ORTI"
    imap:
      host: imaps.pec.aruba.it
      port: 993
      user: orti@pec.it
      password_env: PEC_PASSWORD_ORTI
    notes: |
      Fetch automatico IMAP read-only (ingest/pec_fetch.py). Stesso parser di
      INTUR. Spec: docs/superpowers/specs/2026-07-31-pec-fetch-automatico-design.md

  # ── PEC vineyardamalficoast@pec.it ───────────────────────────────────────
  PEC_MAILBOX_VIGNA_APPEND:
    system: PEC
    dataset: MAILBOX
    dataset_label: "PEC vineyardamalficoast@pec.it — Amalfi Coast Vineyard"
    societa: VIGNA
    business_unit: null
    lifecycle: APPEND
    canonical_table: f_pec_messages
    parser_module: ingest.flussi.ingest_pec_mbox
    hash_basis: msgid
    loop_targets: [pec_archive]
    promotion_policy: AUTO
    detector_category: pec_mbox
    raw_storage:
      backend: gcs
      bucket: vigna-raw
      path_template: "pec/mailbox/VIGNA"
    imap:
      host: imaps.pec.aruba.it
      port: 993
      user: vineyardamalficoast@pec.it
      password_env: PEC_PASSWORD_VIGNA
    notes: |
      VIGNA è identità lineage, NON società contabile: non entra in
      core/schemas.py::SocietaId. Fetch automatico IMAP read-only.
```

`PEC_MAILBOX_STEFANO_APPEND` **non si aggiunge in questo task**: manca l'host IMAP di `mpspec.it` (questione aperta #1 della spec). Va aggiunta con la stessa forma appena Stefano fornisce host e porta, ed è l'unico pezzo del piano che resta scoperto.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pec_registry.py -v`
Expected: PASS

Poi verifica che i bucket esistano davvero:

Run: `gsutil ls -b gs://orti-raw gs://vigna-raw`
Expected: entrambi elencati. Se mancano, crearli con `gsutil mb -l europe-west1 gs://<nome>` e abilitare Object Versioning con `gsutil versioning set on gs://<nome>` — come `hotelops-raw`.

- [ ] **Step 5: Commit**

```bash
git add core/source_registry.yaml tests/test_pec_registry.py
git commit -m "feat(registry): sorgenti PEC ORTI e VIGNA + config IMAP su tutte

Stessa grammatica e stesso parser di INTUR. STEFANO resta fuori finché
non abbiamo host IMAP di mpspec.it."
```

---

### Task 4: Watermark su GCS

**Files:**
- Create: `ingest/pec_watermark.py`
- Test: `tests/test_pec_watermark.py`

**Interfaces:**
- Consumes: niente
- Produces:
  - `read_watermark(bucket: str, entity_id: str, client=None) -> int` — 0 se assente
  - `write_watermark(bucket: str, entity_id: str, uid: int, client=None) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pec_watermark.py
import json

from ingest.pec_watermark import read_watermark, write_watermark


class _FakeBlob:
    def __init__(self, store, key):
        self._store, self._key = store, key

    def exists(self):
        return self._key in self._store

    def download_as_text(self):
        return self._store[self._key]

    def upload_from_string(self, data, content_type=None):
        self._store[self._key] = data


class _FakeBucket:
    def __init__(self, store):
        self._store = store

    def blob(self, key):
        return _FakeBlob(self._store, key)


class _FakeClient:
    def __init__(self):
        self.store = {}

    def bucket(self, name):
        return _FakeBucket(self.store)


def test_missing_watermark_reads_as_zero() -> None:
    assert read_watermark("vigna-raw", "VIGNA", client=_FakeClient()) == 0


def test_write_then_read_roundtrip() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 4321, client=c)
    assert read_watermark("vigna-raw", "VIGNA", client=c) == 4321


def test_watermark_is_stored_per_entity() -> None:
    c = _FakeClient()
    write_watermark("hotelops-raw", "INTUR", 100, client=c)
    write_watermark("hotelops-raw", "ORTI", 200, client=c)
    assert read_watermark("hotelops-raw", "INTUR", client=c) == 100
    assert read_watermark("hotelops-raw", "ORTI", client=c) == 200


def test_watermark_payload_is_json_with_last_uid() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 7, client=c)
    payload = json.loads(next(iter(c.store.values())))
    assert payload["last_uid"] == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pec_watermark.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.pec_watermark'`

- [ ] **Step 3: Write minimal implementation**

```python
# ingest/pec_watermark.py
"""Watermark UID per casella PEC, su GCS.

È una OTTIMIZZAZIONE, non una garanzia di correttezza: serve a non
riscaricare buste già viste. La correttezza sta nel content-hash
all'intake (f_raw_objects). Se un watermark si perde, il giro riscarica
e l'hash impedisce i duplicati.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

_PREFIX = "pec/_watermark"


def _blob(bucket: str, entity_id: str, client=None):
    if client is None:
        from google.cloud import storage

        client = storage.Client()
    return client.bucket(bucket).blob(f"{_PREFIX}/{entity_id}.json")


def read_watermark(bucket: str, entity_id: str, client=None) -> int:
    """Ultimo UID ingerito per questa casella. 0 se non c'è mai stato un giro."""
    blob = _blob(bucket, entity_id, client)
    if not blob.exists():
        log.info("Nessun watermark per %s: si parte da 0", entity_id)
        return 0
    return int(json.loads(blob.download_as_text())["last_uid"])


def write_watermark(bucket: str, entity_id: str, uid: int, client=None) -> None:
    blob = _blob(bucket, entity_id, client)
    blob.upload_from_string(
        json.dumps({"last_uid": int(uid)}), content_type="application/json"
    )
    log.info("Watermark %s → %d", entity_id, uid)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pec_watermark.py -v`
Expected: PASS (4 test)

- [ ] **Step 5: Commit**

```bash
git add ingest/pec_watermark.py tests/test_pec_watermark.py
git commit -m "feat(pec): watermark UID per casella su GCS"
```

---

### Task 5: Client IMAP in sola lettura

**Files:**
- Create: `ingest/pec_imap.py`
- Test: `tests/test_pec_imap.py`

**Interfaces:**
- Consumes: niente (modulo autonomo, non importa hotelops)
- Produces:
  - `ImapConfig(host: str, port: int, user: str, password: str)` — dataclass frozen
  - `fetch_since(cfg: ImapConfig, since_uid: int, since_date: str | None = None, conn_factory=None) -> list[tuple[int, bytes]]` — lista `(uid, raw_rfc822)` ordinata per uid crescente

**Nota sul comportamento IMAP che si sbaglia sempre:** una ricerca `UID N:*` restituisce **sempre almeno l'ultimo messaggio della casella**, anche quando il suo UID è minore di N. Va rifiltrato lato client, altrimenti a ogni giro rilavori l'ultima busta.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pec_imap.py
import pytest

from ingest.pec_imap import ImapConfig, fetch_since

CFG = ImapConfig(host="imaps.pec.aruba.it", port=993, user="x@pec.it", password="s3cret")


class _FakeImap:
    """Finto IMAP4_SSL. Registra come è stato usato."""

    def __init__(self, messages: dict[int, bytes]):
        self.messages = messages
        self.selected_readonly = None
        self.logged_out = False
        self.searches: list[str] = []

    def login(self, user, password):
        return ("OK", [b""])

    def select(self, mailbox="INBOX", readonly=False):
        self.selected_readonly = readonly
        return ("OK", [b"1"])

    def uid(self, command, *args):
        if command == "search":
            criterion = " ".join(str(a) for a in args if a is not None)
            self.searches.append(criterion)
            uids = sorted(self.messages)
            # Comportamento reale: "N:*" torna sempre anche l'ultimo messaggio
            if criterion.startswith("UID"):
                lo = int(criterion.split()[1].split(":")[0])
                hit = [u for u in uids if u >= lo]
                if uids and uids[-1] not in hit:
                    hit.append(uids[-1])
                uids = hit
            return ("OK", [" ".join(str(u) for u in uids).encode()])
        if command == "fetch":
            uid = int(args[0])
            return ("OK", [(b"", self.messages[uid])])
        raise AssertionError(f"comando non previsto: {command}")

    def logout(self):
        self.logged_out = True


def _factory(fake):
    def make(cfg):
        fake.login(cfg.user, cfg.password)
        fake.select("INBOX", readonly=True)
        return fake

    return make


def test_returns_only_messages_after_watermark() -> None:
    fake = _FakeImap({10: b"dieci", 11: b"undici", 12: b"dodici"})
    got = fetch_since(CFG, since_uid=10, conn_factory=_factory(fake))
    assert [uid for uid, _ in got] == [11, 12]


def test_last_message_is_not_re_yielded_when_below_watermark() -> None:
    """La quirk di 'UID N:*' non deve far ritornare buste già viste."""
    fake = _FakeImap({10: b"dieci"})
    got = fetch_since(CFG, since_uid=99, conn_factory=_factory(fake))
    assert got == []


def test_empty_mailbox_returns_empty() -> None:
    fake = _FakeImap({})
    assert fetch_since(CFG, since_uid=0, conn_factory=_factory(fake)) == []


def test_non_contiguous_uids_are_handled() -> None:
    """Messaggi cancellati a mano dalla webmail lasciano buchi negli UID."""
    fake = _FakeImap({3: b"tre", 17: b"diciassette", 40: b"quaranta"})
    got = fetch_since(CFG, since_uid=3, conn_factory=_factory(fake))
    assert [uid for uid, _ in got] == [17, 40]


def test_mailbox_is_selected_readonly() -> None:
    fake = _FakeImap({1: b"uno"})
    fetch_since(CFG, since_uid=0, conn_factory=_factory(fake))
    assert fake.selected_readonly is True


def test_connection_is_closed_even_on_error() -> None:
    fake = _FakeImap({1: b"uno"})

    def exploding_factory(cfg):
        fake.login(cfg.user, cfg.password)
        fake.select("INBOX", readonly=True)
        fake.uid = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        return fake

    with pytest.raises(RuntimeError):
        fetch_since(CFG, since_uid=0, conn_factory=exploding_factory)
    assert fake.logged_out is True


def test_returns_raw_bytes_unmodified() -> None:
    raw = b"Return-Path: <posta-certificata@pec.aruba.it>\r\nSubject: test\r\n\r\nbody"
    fake = _FakeImap({5: raw})
    got = fetch_since(CFG, since_uid=0, conn_factory=_factory(fake))
    assert got[0][1] == raw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pec_imap.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.pec_imap'`

- [ ] **Step 3: Write minimal implementation**

```python
# ingest/pec_imap.py
"""Client IMAP in sola lettura per caselle PEC.

Modulo autonomo: non importa nulla di hotelops. Non invia: nessun SMTP,
mai. Non scrive sulla casella: nessun flag, nessun \\Seen — sono caselle
con valore probatorio e un processo automatico non le tocca.
"""

from __future__ import annotations

import imaplib
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    user: str
    password: str


def _connect(cfg: ImapConfig):
    conn = imaplib.IMAP4_SSL(cfg.host, cfg.port)
    conn.login(cfg.user, cfg.password)
    conn.select("INBOX", readonly=True)  # <- la garanzia di sola lettura
    return conn


def _search(conn, criterion: str) -> set[int]:
    typ, data = conn.uid("search", None, criterion)
    if typ != "OK":
        raise RuntimeError(f"IMAP search fallita ({criterion}): {typ}")
    if not data or not data[0]:
        return set()
    return {int(u) for u in data[0].split()}


def fetch_since(
    cfg: ImapConfig,
    since_uid: int,
    since_date: str | None = None,
    conn_factory=None,
) -> list[tuple[int, bytes]]:
    """Buste con UID > since_uid, più (opzionale) quelle arrivate da since_date.

    since_date in formato IMAP: "01-Jul-2026". Serve come finestra di
    sicurezza per catturare buste arrivate fuori ordine.
    """
    factory = conn_factory or _connect
    conn = factory(cfg)
    try:
        uids = _search(conn, f"UID {since_uid + 1}:*")
        if since_date:
            uids |= _search(conn, f"SINCE {since_date}")
        # "UID N:*" torna sempre anche l'ultimo messaggio della casella,
        # anche se il suo UID è < N. Senza questo filtro lo rilavori ogni giro.
        uids = {u for u in uids if u > since_uid}

        out: list[tuple[int, bytes]] = []
        for uid in sorted(uids):
            typ, msg = conn.uid("fetch", str(uid), "(RFC822)")
            if typ != "OK" or not msg or msg[0] is None:
                log.warning("UID %d: fetch fallita, salto", uid)
                continue
            out.append((uid, msg[0][1]))
        return out
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001 — logout best-effort
            log.debug("logout fallito", exc_info=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pec_imap.py -v`
Expected: PASS (7 test)

- [ ] **Step 5: Commit**

```bash
git add ingest/pec_imap.py tests/test_pec_imap.py
git commit -m "feat(pec): client IMAP read-only con filtro sulla quirk UID N:*"
```

---

### Task 6: Il fetcher — orchestrazione e CLI

**Files:**
- Create: `ingest/pec_fetch.py`
- Test: `tests/test_pec_fetch.py`

**Interfaces:**
- Consumes: `fetch_since` (Task 5), `read_watermark`/`write_watermark` (Task 4), registry (Task 3), `intake_file`/`promote_raw_object` (esistenti)
- Produces: `fetch_mailbox(source_name: str, since_days: int = 7, promote: bool = True, deps: Deps | None = None) -> FetchResult` con `FetchResult(entity_id: str, fetched: int, ingested: int, deduped: int, last_uid: int, status: str)`; `status ∈ {"OK", "FAILED"}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pec_fetch.py
from dataclasses import dataclass

import pytest

from ingest.pec_fetch import Deps, fetch_mailbox


@dataclass
class _IntakeResult:
    raw_object_id: str
    content_hash: str
    deduped: bool


def _deps(messages, watermarks=None, seen_hashes=None):
    """Deps finte: nessuna rete, nessun GCS, nessun BQ."""
    wm = dict(watermarks or {})
    seen = set(seen_hashes or [])
    calls = {"intake": [], "promote": []}

    def fake_fetch(cfg, since_uid, since_date=None, conn_factory=None):
        return [(u, b) for u, b in messages if u > since_uid]

    def fake_intake(path, source_name, actor):
        raw = path.read_bytes()
        h = str(hash(raw))
        deduped = h in seen
        seen.add(h)
        calls["intake"].append((source_name, h, deduped))
        return _IntakeResult(raw_object_id=f"ro-{h}", content_hash=h, deduped=deduped)

    def fake_promote(raw_object_id, actor):
        calls["promote"].append(raw_object_id)
        return type("P", (), {"status": "PROMOTED", "reason": None, "noop": False})()

    return Deps(
        fetch_since=fake_fetch,
        read_watermark=lambda b, e: wm.get(e, 0),
        write_watermark=lambda b, e, u: wm.__setitem__(e, u),
        intake_file=fake_intake,
        promote_raw_object=fake_promote,
        get_password=lambda env: "s3cret",
    ), wm, calls


def test_fetches_and_ingests_new_messages() -> None:
    deps, wm, calls = _deps([(11, b"una"), (12, b"due")])
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res.fetched == 2
    assert res.ingested == 2
    assert res.status == "OK"
    assert len(calls["intake"]) == 2


def test_watermark_advances_to_highest_uid() -> None:
    deps, wm, _ = _deps([(11, b"una"), (12, b"due")])
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res.last_uid == 12
    assert wm["VIGNA"] == 12


def test_second_run_produces_zero_duplicates() -> None:
    """Il test che conta: stesso messaggio due volte, una riga sola."""
    msgs = [(11, b"una"), (12, b"due")]
    deps, wm, calls = _deps(msgs)
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    res2 = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res2.fetched == 0, "il watermark deve impedire il ri-fetch"
    assert len(calls["intake"]) == 2, "nessun intake in più al secondo giro"


def test_content_hash_catches_duplicates_when_watermark_is_lost() -> None:
    """Se il watermark sparisce, il giro riscarica ma non duplica."""
    msgs = [(11, b"una"), (12, b"due")]
    deps, wm, calls = _deps(msgs)
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    wm.clear()  # watermark perso
    res2 = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res2.fetched == 2, "riscarica, giustamente"
    assert res2.deduped == 2, "ma l'intake li riconosce già visti"
    assert res2.ingested == 0


def test_empty_mailbox_is_not_an_error() -> None:
    deps, wm, _ = _deps([])
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res.status == "OK"
    assert res.fetched == 0


def test_unreachable_mailbox_returns_failed_not_raises() -> None:
    deps, _, _ = _deps([])

    def exploding(cfg, since_uid, since_date=None, conn_factory=None):
        raise ConnectionError("server irraggiungibile")

    deps.fetch_since = exploding
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res.status == "FAILED"
    assert res.fetched == 0


def test_watermark_not_advanced_on_failure() -> None:
    deps, wm, _ = _deps([], watermarks={"VIGNA": 50})

    def exploding(cfg, since_uid, since_date=None, conn_factory=None):
        raise ConnectionError("boom")

    deps.fetch_since = exploding
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert wm["VIGNA"] == 50, "un giro fallito non deve spostare il watermark"


def test_unknown_source_raises() -> None:
    deps, _, _ = _deps([])
    with pytest.raises(ValueError, match="non nel registry"):
        fetch_mailbox("PEC_MAILBOX_PIPPO_APPEND", deps=deps)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pec_fetch.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.pec_fetch'`

- [ ] **Step 3: Write minimal implementation**

```python
# ingest/pec_fetch.py
"""PEC auto-sync: fetch IMAP read-only, poi intake + promote.

Usage:
    python -m ingest.pec_fetch --source-name PEC_MAILBOX_VIGNA_APPEND
    python -m ingest.pec_fetch --all
    python -m ingest.pec_fetch --source-name PEC_MAILBOX_ORTI_APPEND --no-promote

La password arriva da os.environ[<password_env>] (Secret Manager in cloud).
Sostituisce il gesto manuale di scaricare l'mbox dalla webmail: tutto ciò
che sta a valle (parser, classificazione, pannello) è invariato.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    entity_id: str
    fetched: int = 0
    ingested: int = 0
    deduped: int = 0
    last_uid: int = 0
    status: str = "OK"
    error: str | None = None


@dataclass
class Deps:
    """Confini iniettabili — così i test non toccano rete, GCS o BQ."""

    fetch_since: Callable = field(default=None)
    read_watermark: Callable = field(default=None)
    write_watermark: Callable = field(default=None)
    intake_file: Callable = field(default=None)
    promote_raw_object: Callable = field(default=None)
    get_password: Callable = field(default=None)


def _default_deps() -> Deps:
    from ingest.intake import intake_file
    from ingest.pec_imap import fetch_since
    from ingest.pec_watermark import read_watermark, write_watermark
    from ingest.promotion import promote_raw_object

    return Deps(
        fetch_since=fetch_since,
        read_watermark=read_watermark,
        write_watermark=write_watermark,
        intake_file=intake_file,
        promote_raw_object=promote_raw_object,
        get_password=lambda env: os.environ[env],
    )


def fetch_mailbox(
    source_name: str,
    since_days: int = 7,
    promote: bool = True,
    deps: Deps | None = None,
) -> FetchResult:
    from core.lineage.source_resolver import load_registry

    from ingest.pec_imap import ImapConfig

    d = deps or _default_deps()
    sd = load_registry().get(source_name)
    if sd is None:
        raise ValueError(f"source {source_name!r} non nel registry")
    if sd.imap is None:
        raise ValueError(f"source {source_name!r} senza blocco imap")

    entity = sd.societa
    bucket = sd.raw_storage.bucket
    res = FetchResult(entity_id=entity)

    cfg = ImapConfig(
        host=sd.imap.host,
        port=sd.imap.port,
        user=sd.imap.user,
        password=d.get_password(sd.imap.password_env),
    )

    watermark = d.read_watermark(bucket, entity)
    since_date = (
        dt.date.today() - dt.timedelta(days=since_days)
    ).strftime("%d-%b-%Y") if since_days else None

    try:
        messages = d.fetch_since(cfg, watermark, since_date=since_date)
    except Exception as exc:  # noqa: BLE001 — una casella giù non ferma le altre
        log.error("%s: fetch fallita: %s", entity, exc)
        res.status, res.error = "FAILED", str(exc)
        return res

    res.fetched = len(messages)
    highest = watermark

    with tempfile.TemporaryDirectory() as tmp:
        for uid, raw in messages:
            path = Path(tmp) / f"{entity}_{uid}.eml"
            path.write_bytes(raw)
            out = d.intake_file(path, source_name=source_name, actor="pec_fetch")
            if out.deduped:
                res.deduped += 1
            else:
                res.ingested += 1
                if promote and out.raw_object_id:
                    d.promote_raw_object(out.raw_object_id, actor="pec_fetch")
            highest = max(highest, uid)

    if highest > watermark:
        d.write_watermark(bucket, entity, highest)
    res.last_uid = highest
    return res


def main() -> None:
    p = argparse.ArgumentParser(
        prog="ingest.pec_fetch",
        description="Fetch IMAP read-only delle caselle PEC, poi intake + promote.",
    )
    p.add_argument("--source-name", default=None, help="Registry source name")
    p.add_argument("--all", action="store_true", help="Tutte le sorgenti PEC con blocco imap")
    p.add_argument("--since-days", type=int, default=7,
                   help="Finestra di sicurezza oltre al watermark (0 = solo watermark)")
    p.add_argument("--no-promote", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    from core.lineage.source_resolver import load_registry

    if args.all:
        names = [
            sd.source_name
            for sd in load_registry().find_all_by_detector_category("pec_mbox")
            if sd.imap is not None
        ]
    elif args.source_name:
        names = [args.source_name]
    else:
        raise SystemExit("ERROR: serve --source-name oppure --all")

    failed = []
    for name in sorted(names):
        r = fetch_mailbox(name, since_days=args.since_days, promote=not args.no_promote)
        print(
            f"{r.entity_id}: status={r.status} fetched={r.fetched} "
            f"ingested={r.ingested} deduped={r.deduped} last_uid={r.last_uid}"
            + (f" error={r.error}" if r.error else "")
        )
        if r.status == "FAILED":
            failed.append(r.entity_id)

    if failed:
        print(f"PARZIALE: caselle non raggiunte: {', '.join(failed)}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
```

**Nota:** `--all` usa `find_all_by_detector_category("pec_mbox")` (`core/lineage/source_resolver.py:53`), che è già l'API pensata per questo. `SourceRegistry` non ha `.items()`: espone `.sources` (dict), `.get()`, `.resolve()` e `.find_all_by_detector_category()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pec_fetch.py -v`
Expected: PASS (8 test)

Poi la suite intera, per assicurarsi che l'allargamento di `SOCIETA_VALUES` non abbia rotto nulla:

Run: `pytest -q && ruff check . && ruff format --check .`
Expected: tutto verde

- [ ] **Step 5: Commit**

```bash
git add ingest/pec_fetch.py tests/test_pec_fetch.py
git commit -m "feat(pec): fetcher automatico IMAP -> intake -> promote

Sostituisce lo scarico manuale dell'mbox dalla webmail. Watermark per non
riscaricare, content-hash per non duplicare, finestra di sicurezza di 7
giorni per le buste fuori ordine. Una casella giù non ferma le altre: il
run esce 2 e dice quali."
```

---

### Task 7: Deploy — Cloud Run Job + Scheduler

**Files:**
- Modify: `docs/` — annotare il comando di deploy accanto a quello di `spiaggia-corrispettivi-daily`

**Interfaces:**
- Consumes: Task 6 (`python -m ingest.pec_fetch --all`)
- Produces: job `pec-fetch-daily` schedulato

- [ ] **Step 1: Caricare le password in Secret Manager**

```bash
for E in INTUR ORTI VIGNA; do
  printf '%s' "<password-di-$E>" | gcloud secrets create "pec-password-$E" \
    --data-file=- --replication-policy=automatic --project=hotelops-suite
done
```

Verifica: `gcloud secrets list --project=hotelops-suite | grep pec-password`
Expected: tre segreti elencati.

- [ ] **Step 2: Provare il giro in locale, in sola lettura, senza promote**

```bash
export PEC_PASSWORD_VIGNA='<password>'
python -m ingest.pec_fetch --source-name PEC_MAILBOX_VIGNA_APPEND --no-promote -v
```

Expected: `VIGNA: status=OK fetched=N ingested=N deduped=0 last_uid=<uid>` con N > 0.
**Gate:** rilanciare *lo stesso comando* subito dopo. Deve stampare `fetched=0`. Se stampa un numero maggiore di zero, il watermark non si sta scrivendo e non si prosegue.

- [ ] **Step 3: Creare il Cloud Run Job**

```bash
gcloud run jobs deploy pec-fetch-daily \
  --source . \
  --region=europe-west1 \
  --project=hotelops-suite \
  --command=python \
  --args=-m,ingest.pec_fetch,--all \
  --set-secrets=PEC_PASSWORD_INTUR=pec-password-INTUR:latest,PEC_PASSWORD_ORTI=pec-password-ORTI:latest,PEC_PASSWORD_VIGNA=pec-password-VIGNA:latest \
  --max-retries=1 \
  --task-timeout=15m
```

- [ ] **Step 4: Eseguirlo una volta a mano e leggere i log**

```bash
gcloud run jobs execute pec-fetch-daily --region=europe-west1 --wait
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=pec-fetch-daily' \
  --limit=50 --project=hotelops-suite
```

Expected: una riga `status=OK` per ciascuna delle tre caselle. Se una risulta `FAILED`, l'exit code è 2 e i log dicono quale — è il comportamento voluto, non un bug.

- [ ] **Step 5: Schedulare e committare la nota**

```bash
gcloud scheduler jobs create http pec-fetch-daily-trigger \
  --location=europe-west1 \
  --schedule="0 4 * * *" \
  --time-zone="Europe/Rome" \
  --uri="https://run.googleapis.com/v2/projects/hotelops-suite/locations/europe-west1/jobs/pec-fetch-daily:run" \
  --http-method=POST \
  --oauth-service-account-email=<SA del job>
```

```bash
git add docs/
git commit -m "docs(pec): comandi deploy del job pec-fetch-daily"
```

---

## Self-Review

**Copertura della spec.** Sola lettura → Task 5 (`readonly=True` più test dedicato). SMTP mai configurato → Task 3 (test che cerca "smtp" nel registry) e Task 5. Watermark UID → Task 4, usato in Task 6. Content-hash → Task 6, due test espliciti. Quattro caselle → Task 3, **con l'eccezione dichiarata di STEFANO** (questione aperta #1: manca l'host `mpspec.it`). `entity_id` invece di `SocietaId` → Task 1, che tocca `core/lineage/schemas.py` e non `core/schemas.py`. Cloud Run Job + Secret Manager → Task 7. Errore parziale → Task 6, due test più l'exit code 2. Finestra di sicurezza 7 giorni → Task 5 (`since_date`) e Task 6 (`--since-days`, default 7).

**Placeholder.** Nessun TBD. L'unico buco è dichiarato e circoscritto: `PEC_MAILBOX_STEFANO_APPEND` non entra finché Stefano non fornisce host e porta di `mpspec.it`. Aggiungerla è copiare il blocco `PEC_MAILBOX_VIGNA_APPEND` cambiando quattro valori.

**Coerenza dei tipi.** `fetch_since(cfg, since_uid, since_date, conn_factory)` ha la stessa firma in Task 5, nei finti di Task 6 e nella chiamata reale. `read_watermark(bucket, entity_id)` e `write_watermark(bucket, entity_id, uid)` coincidono fra Task 4 e Task 6. `intake_file(path, source_name=, actor=)` e `promote_raw_object(raw_object_id, actor=)` combaciano con le firme reali usate da `ingest/drive_fetch.py:104,118`. `ImapMailbox.password_env` (registry, Task 2) è distinto da `ImapConfig.password` (runtime, Task 5): il primo nomina la variabile, il secondo porta il valore — la separazione è voluta ed è ciò che impedisce alla password di finire nel repo.
