# PEC fetch IMAP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sostituire lo scarico manuale degli mbox dalla webmail con un job notturno che legge le quattro caselle PEC via IMAP in sola lettura e le consegna alla pipeline esistente.

**Architecture:** Il fetcher scarica le buste nuove come `.eml` e chiama `intake_file()` + `promote_raw_object()`. Il parser `ingest_pec_mbox` accetta già `.eml` e risolve il contesto dalla sorgente: **nulla a valle cambia**. Il fetcher sa di IMAP e non sa nulla di PEC.

**Tech Stack:** Python ≥3.11, `imaplib` (stdlib — nessuna dipendenza nuova), `google-cloud-storage`, pytest.

**Spec:** `docs/superpowers/specs/2026-07-31-pec-fetch-automatico-design.md` · **Issue:** #114
**Base:** main a `3b97df8` o successivo (dopo il merge di #113)

## Stato di partenza — cosa esiste già

Verificato su main dopo #113. Non re-implementare:

- `EntityId` e i quattro `entity_id` (`INTUR`, `ORTI`, `VIGNA`, `STEFANO_PERSONALE`)
- Le quattro sorgenti `PEC_MAILBOX_*_APPEND` con i campi `casella`, `entity_id`, `input_formats`
- Parser generalizzato che accetta `.eml` e risolve la casella dal `--source`
- Classificazione, pannello CEO, digest, CLI `hotelops pec`
- `f_pec_messages` popolata: 2717 buste su quattro caselle

**Manca solo il pezzo che scarica.** `imaplib` non compare in nessun file del repo.

## Global Constraints

- **Sola lettura assoluta.** `select(..., readonly=True)` sempre. Nessun flag, nessun `\Seen`, nessuna label lato server: sono caselle con valore probatorio.
- **SMTP mai configurato.** La porta 465 non compare in nessun file.
- **Nessuna password nel repo.** Solo `password_env`, che nomina la variabile d'ambiente (Secret Manager in cloud).
- **`casella` è già l'utente IMAP.** Non duplicare l'indirizzo in un campo `user`: esiste già nel registry.
- **Idempotenza:** watermark = efficienza, content-hash all'intake = correttezza. Nessun task può affidarsi al solo watermark.
- `ruff check .` non deve superare i 87 errori di main; `pytest` tutto verde.

## File Structure

| File | Responsabilità |
|---|---|
| `core/lineage/schemas.py` (modifica) | Modello `ImapMailbox` + campo opzionale su `SourceDefinition` |
| `core/source_registry.yaml` (modifica) | Blocco `imap` sulle 4 caselle + `eml` negli `input_formats` |
| `ingest/pec_watermark.py` (nuovo) | Ultimo UID visto per casella, su GCS |
| `ingest/pec_imap.py` (nuovo) | Client IMAP read-only, autonomo |
| `ingest/pec_fetch.py` (nuovo) | CLI e orchestrazione |
| `tests/test_pec_watermark.py`, `tests/test_pec_imap.py`, `tests/test_pec_fetch.py` (nuovi) | |

---

### Task 1: Config IMAP nel registry + `eml` negli input_formats

Tre caselle su quattro hanno `input_formats: [mbox]`. Il fetcher produce `.eml`: senza questa aggiunta il promote le rifiuta.

**Files:**
- Modify: `core/lineage/schemas.py` (nuovo `ImapMailbox`, campo su `SourceDefinition`)
- Modify: `core/source_registry.yaml` (4 blocchi `imap`, 3 `input_formats`)
- Test: `tests/test_pec_imap_config.py`

**Interfaces:**
- Produces: `ImapMailbox(host: str, port: int = 993, password_env: str)`; `SourceDefinition.imap: Optional[ImapMailbox] = None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pec_imap_config.py
import pytest

from core.lineage.source_resolver import load_registry

CASELLE = [
    ("PEC_MAILBOX_INTUR_APPEND", "in.tur@pec.it", "imaps.pec.aruba.it", "PEC_PASSWORD_INTUR"),
    ("PEC_MAILBOX_ORTI_APPEND", "orti@pec.it", "imaps.pec.aruba.it", "PEC_PASSWORD_ORTI"),
    ("PEC_MAILBOX_VIGNA_APPEND", "vineyardamalficoast@pec.it", "imaps.pec.aruba.it", "PEC_PASSWORD_VIGNA"),
]


@pytest.mark.parametrize("name,casella,host,env", CASELLE)
def test_imap_block_presente(name, casella, host, env) -> None:
    sd = load_registry().get(name)
    assert sd.imap is not None, f"{name} senza blocco imap"
    assert sd.imap.host == host
    assert sd.imap.port == 993
    assert sd.imap.password_env == env
    # la casella NON si duplica nel blocco imap: è già un campo della sorgente
    assert sd.casella == casella


@pytest.mark.parametrize("name,_c,_h,_e", CASELLE)
def test_eml_accettato(name, _c, _h, _e) -> None:
    """Il fetcher produce .eml: il promote deve accettarlo."""
    sd = load_registry().get(name)
    assert "eml" in sd.input_formats, f"{name} non accetta eml"


def test_imap_model_non_ha_campo_password() -> None:
    from core.lineage.schemas import ImapMailbox

    assert "password" not in ImapMailbox.model_fields
    assert "user" not in ImapMailbox.model_fields


def test_nessun_smtp_nel_registry() -> None:
    text = open("core/source_registry.yaml", encoding="utf-8").read().lower()
    assert "smtp" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pec_imap_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'ImapMailbox'` / `sd.imap is None`

- [ ] **Step 3: Write minimal implementation**

In `core/lineage/schemas.py`, accanto a `RawStorage`:

```python
class ImapMailbox(BaseModel):
    """Config IMAP in sola lettura di una casella PEC.

    L'utente NON sta qui: è il campo `casella` della sorgente.
    La password NON sta qui: `password_env` nomina la variabile d'ambiente.
    """

    host: str
    port: int = 993
    password_env: str
```

Su `SourceDefinition`, accanto a `drive_file_id`:

```python
    imap: Optional[ImapMailbox] = None
```

In `core/source_registry.yaml`, su ognuna delle quattro sorgenti PEC aggiungere il blocco (variando `password_env` con l'entity: `INTUR`, `ORTI`, `VIGNA`, `PERSONALE`):

```yaml
    imap:
      host: imaps.pec.aruba.it
      port: 993
      password_env: PEC_PASSWORD_INTUR
```

⚠️ `PEC_MAILBOX_PERSONALE_APPEND` è su `mpspec.it`, **non** Aruba: usare host e porta reali quando disponibili. Se ancora ignoti, lasciarla senza blocco `imap` — il fetcher la salterà, e il test parametrizzato sopra non la include.

E su INTUR, ORTI, VIGNA cambiare:

```yaml
    input_formats: [mbox, eml]
```

(`PERSONALE` ha già `[eml, mbox]`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pec_imap_config.py tests/test_pec_multicasella.py -v`
Expected: PASS — inclusi i test multicasella esistenti, che non devono rompersi.

- [ ] **Step 5: Commit**

```bash
git add core/lineage/schemas.py core/source_registry.yaml tests/test_pec_imap_config.py
git commit -m "feat(pec): blocco config IMAP sulle caselle + eml negli input_formats

L'utente IMAP è il campo casella già esistente, non si duplica. La
password non ha un campo nel modello, così non può finire nel repo."
```

---

### Task 2: Watermark UID su GCS

**Files:**
- Create: `ingest/pec_watermark.py`
- Test: `tests/test_pec_watermark.py`

**Interfaces:**
- Produces: `read_watermark(bucket: str, entity_id: str, client=None) -> int` (0 se assente); `write_watermark(bucket: str, entity_id: str, uid: int, client=None) -> None`

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


def test_watermark_assente_vale_zero() -> None:
    assert read_watermark("vigna-raw", "VIGNA", client=_FakeClient()) == 0


def test_roundtrip() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 4321, client=c)
    assert read_watermark("vigna-raw", "VIGNA", client=c) == 4321


def test_watermark_separato_per_entity() -> None:
    c = _FakeClient()
    write_watermark("hotelops-raw", "INTUR", 100, client=c)
    write_watermark("hotelops-raw", "ORTI", 200, client=c)
    assert read_watermark("hotelops-raw", "INTUR", client=c) == 100
    assert read_watermark("hotelops-raw", "ORTI", client=c) == 200


def test_payload_json_con_last_uid() -> None:
    c = _FakeClient()
    write_watermark("vigna-raw", "VIGNA", 7, client=c)
    assert json.loads(next(iter(c.store.values())))["last_uid"] == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pec_watermark.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.pec_watermark'`

- [ ] **Step 3: Write minimal implementation**

```python
# ingest/pec_watermark.py
"""Watermark UID per casella PEC, su GCS.

È una OTTIMIZZAZIONE, non la garanzia di correttezza: evita di riscaricare
buste già viste. La correttezza sta nel content-hash all'intake. Se un
watermark si perde, il giro riscarica e l'hash impedisce i duplicati.
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

### Task 3: Client IMAP in sola lettura

**Files:**
- Create: `ingest/pec_imap.py`
- Test: `tests/test_pec_imap.py`

**Interfaces:**
- Produces: `ImapConfig(host, port, user, password)` (dataclass frozen); `fetch_since(cfg, since_uid: int, since_date: str | None = None, conn_factory=None) -> list[tuple[int, bytes]]` ordinata per uid crescente

**Trappola IMAP da conoscere:** una ricerca `UID N:*` restituisce **sempre almeno l'ultimo messaggio della casella**, anche quando il suo UID è minore di N. Va rifiltrato lato client, altrimenti si rilavora l'ultima busta a ogni giro.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pec_imap.py
import pytest

from ingest.pec_imap import ImapConfig, fetch_since

CFG = ImapConfig(host="imaps.pec.aruba.it", port=993, user="x@pec.it", password="s3cret")


class _FakeImap:
    def __init__(self, messages: dict[int, bytes]):
        self.messages = messages
        self.selected_readonly = None
        self.logged_out = False

    def login(self, user, password):
        return ("OK", [b""])

    def select(self, mailbox="INBOX", readonly=False):
        self.selected_readonly = readonly
        return ("OK", [b"1"])

    def uid(self, command, *args):
        if command == "search":
            criterion = " ".join(str(a) for a in args if a is not None)
            uids = sorted(self.messages)
            if criterion.startswith("UID"):
                lo = int(criterion.split()[1].split(":")[0])
                hit = [u for u in uids if u >= lo]
                # comportamento reale: "N:*" torna sempre anche l'ultimo
                if uids and uids[-1] not in hit:
                    hit.append(uids[-1])
                uids = hit
            return ("OK", [" ".join(str(u) for u in uids).encode()])
        if command == "fetch":
            return ("OK", [(b"", self.messages[int(args[0])])])
        raise AssertionError(f"comando non previsto: {command}")

    def logout(self):
        self.logged_out = True


def _factory(fake):
    def make(cfg):
        fake.login(cfg.user, cfg.password)
        fake.select("INBOX", readonly=True)
        return fake

    return make


def test_solo_messaggi_dopo_il_watermark() -> None:
    fake = _FakeImap({10: b"dieci", 11: b"undici", 12: b"dodici"})
    got = fetch_since(CFG, since_uid=10, conn_factory=_factory(fake))
    assert [uid for uid, _ in got] == [11, 12]


def test_ultimo_messaggio_non_ritorna_se_sotto_watermark() -> None:
    fake = _FakeImap({10: b"dieci"})
    assert fetch_since(CFG, since_uid=99, conn_factory=_factory(fake)) == []


def test_casella_vuota() -> None:
    fake = _FakeImap({})
    assert fetch_since(CFG, since_uid=0, conn_factory=_factory(fake)) == []


def test_uid_non_contigui() -> None:
    """Buste cancellate a mano dalla webmail lasciano buchi negli UID."""
    fake = _FakeImap({3: b"tre", 17: b"diciassette", 40: b"quaranta"})
    got = fetch_since(CFG, since_uid=3, conn_factory=_factory(fake))
    assert [uid for uid, _ in got] == [17, 40]


def test_casella_aperta_readonly() -> None:
    fake = _FakeImap({1: b"uno"})
    fetch_since(CFG, since_uid=0, conn_factory=_factory(fake))
    assert fake.selected_readonly is True


def test_logout_anche_su_errore() -> None:
    fake = _FakeImap({1: b"uno"})

    def exploding(cfg):
        fake.login(cfg.user, cfg.password)
        fake.select("INBOX", readonly=True)
        fake.uid = lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
        return fake

    with pytest.raises(RuntimeError):
        fetch_since(CFG, since_uid=0, conn_factory=exploding)
    assert fake.logged_out is True


def test_byte_restituiti_intatti() -> None:
    raw = b"Return-Path: <posta-certificata@pec.aruba.it>\r\nSubject: t\r\n\r\nbody"
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

Modulo autonomo: non importa nulla di hotelops. Non invia (nessun SMTP) e
non scrive sulla casella (nessun flag, nessun \\Seen): sono caselle con
valore probatorio e un processo automatico non le tocca.
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
    """Buste con UID > since_uid, più quelle da since_date (formato "01-Jul-2026")."""
    conn = (conn_factory or _connect)(cfg)
    try:
        uids = _search(conn, f"UID {since_uid + 1}:*")
        if since_date:
            uids |= _search(conn, f"SINCE {since_date}")
        # "UID N:*" torna sempre anche l'ultimo messaggio, pure se il suo UID
        # è < N. Senza questo filtro lo si rilavora a ogni giro, per sempre.
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

### Task 4: Fetcher e CLI

**Files:**
- Create: `ingest/pec_fetch.py`
- Test: `tests/test_pec_fetch.py`

**Interfaces:**
- Consumes: `fetch_since` (Task 3), `read_watermark`/`write_watermark` (Task 2), registry (Task 1), `intake_file`/`promote_raw_object` (esistenti — firme in `ingest/drive_fetch.py:104,118`)
- Produces: `fetch_mailbox(source_name, since_days=7, promote=True, deps=None) -> FetchResult(entity_id, fetched, ingested, deduped, last_uid, status, error)`; `status ∈ {"OK","FAILED"}`

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


def _deps(messages, watermarks=None):
    wm = dict(watermarks or {})
    seen = set()
    calls = {"intake": [], "promote": []}

    def fake_fetch(cfg, since_uid, since_date=None, conn_factory=None):
        return [(u, b) for u, b in messages if u > since_uid]

    def fake_intake(path, source_name, actor):
        h = str(hash(path.read_bytes()))
        deduped = h in seen
        seen.add(h)
        calls["intake"].append((source_name, h, deduped))
        return _IntakeResult(f"ro-{h}", h, deduped)

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


def test_ingerisce_le_buste_nuove() -> None:
    deps, _, calls = _deps([(11, b"una"), (12, b"due")])
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert (res.fetched, res.ingested, res.status) == (2, 2, "OK")
    assert len(calls["intake"]) == 2


def test_watermark_avanza_al_uid_massimo() -> None:
    deps, wm, _ = _deps([(11, b"una"), (12, b"due")])
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res.last_uid == 12
    assert wm["VIGNA"] == 12


def test_secondo_giro_zero_duplicati() -> None:
    """Il test che conta: stessa busta due volte, una riga sola."""
    deps, _, calls = _deps([(11, b"una"), (12, b"due")])
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    res2 = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res2.fetched == 0
    assert len(calls["intake"]) == 2


def test_hash_protegge_se_il_watermark_si_perde() -> None:
    deps, wm, _ = _deps([(11, b"una"), (12, b"due")])
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    wm.clear()
    res2 = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res2.fetched == 2, "riscarica, giustamente"
    assert (res2.deduped, res2.ingested) == (2, 0), "ma non duplica"


def test_casella_vuota_non_e_errore() -> None:
    deps, _, _ = _deps([])
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert (res.status, res.fetched) == ("OK", 0)


def test_casella_irraggiungibile_torna_failed() -> None:
    deps, _, _ = _deps([])
    deps.fetch_since = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("giù"))
    res = fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert res.status == "FAILED"


def test_watermark_fermo_su_fallimento() -> None:
    deps, wm, _ = _deps([], watermarks={"VIGNA": 50})
    deps.fetch_since = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("giù"))
    fetch_mailbox("PEC_MAILBOX_VIGNA_APPEND", deps=deps)
    assert wm["VIGNA"] == 50


def test_sorgente_sconosciuta_solleva() -> None:
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
    python -m ingest.pec_fetch --all
    python -m ingest.pec_fetch --source-name PEC_MAILBOX_VIGNA_APPEND
    python -m ingest.pec_fetch --source-name PEC_MAILBOX_ORTI_APPEND --no-promote

Sostituisce lo scarico manuale dell'mbox dalla webmail. Tutto ciò che sta a
valle (parser, classificazione, pannello, digest) è invariato.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    entity_id: str
    fetched: int = 0
    ingested: int = 0
    deduped: int = 0
    last_uid: int = 0
    status: str = "OK"
    error: Optional[str] = None


@dataclass
class Deps:
    """Confini iniettabili — i test non toccano rete, GCS o BQ."""

    fetch_since: Callable
    read_watermark: Callable
    write_watermark: Callable
    intake_file: Callable
    promote_raw_object: Callable
    get_password: Callable


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

    entity = sd.entity_id
    bucket = sd.raw_storage.bucket
    res = FetchResult(entity_id=entity)

    cfg = ImapConfig(
        host=sd.imap.host,
        port=sd.imap.port,
        user=sd.casella,  # l'utente IMAP è la casella del registry
        password=d.get_password(sd.imap.password_env),
    )

    watermark = d.read_watermark(bucket, entity)
    since_date = (
        (dt.date.today() - dt.timedelta(days=since_days)).strftime("%d-%b-%Y")
        if since_days
        else None
    )

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
    p.add_argument("--source-name", default=None)
    p.add_argument("--all", action="store_true", help="Tutte le caselle PEC con blocco imap")
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
        names = sorted(
            sd.source_name
            for sd in load_registry().find_all_by_detector_category("pec_mbox")
            if sd.imap is not None
        )
    elif args.source_name:
        names = [args.source_name]
    else:
        raise SystemExit("ERROR: serve --source-name oppure --all")

    failed = []
    for name in names:
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

`find_all_by_detector_category` è in `core/lineage/source_resolver.py:53`. `SourceRegistry` **non ha `.items()`**: espone `.sources`, `.get()`, `.resolve()` e quel metodo.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pec_fetch.py -v`
Expected: PASS (8 test)

Poi la suite intera più il lint:

Run: `pytest -q && ruff check . | tail -2`
Expected: tutto verde; ruff non oltre gli 87 errori di main.

- [ ] **Step 5: Commit**

```bash
git add ingest/pec_fetch.py tests/test_pec_fetch.py
git commit -m "feat(pec): fetcher automatico IMAP -> intake -> promote

Watermark per non riscaricare, content-hash per non duplicare, finestra
di sicurezza di 7 giorni per le buste fuori ordine. Una casella giù non
ferma le altre: exit 2 con l'elenco."
```

---

### Task 5: Deploy — Cloud Run Job + Scheduler

**Files:**
- Modify: `docs/` — annotare i comandi accanto a quelli di `spiaggia-corrispettivi-daily`

- [ ] **Step 1: Caricare le password in Secret Manager**

```bash
for E in INTUR ORTI VIGNA; do
  printf '%s' "<password-di-$E>" | gcloud secrets create "pec-password-$E" \
    --data-file=- --replication-policy=automatic --project=hotelops-suite
done
```

Verifica: `gcloud secrets list --project=hotelops-suite | grep pec-password` → tre segreti.

- [ ] **Step 2: Gate — provare in locale, senza promote**

```bash
export PEC_PASSWORD_VIGNA='<password>'
python -m ingest.pec_fetch --source-name PEC_MAILBOX_VIGNA_APPEND --no-promote -v
```

Expected: `VIGNA: status=OK fetched=N ...` con N > 0 (la vigna è ferma all'08/07, quindi ci sono buste da recuperare).

**Gate bloccante:** rilanciare *lo stesso comando*. Deve stampare `fetched=0`. Se stampa altro, il watermark non si scrive e non si prosegue al deploy.

- [ ] **Step 3: Primo giro reale con promote su una casella sola**

```bash
python -m ingest.pec_fetch --source-name PEC_MAILBOX_VIGNA_APPEND -v
```

Poi verificare che le righe siano atterrate:

```bash
python -c "
from google.cloud import bigquery
c = bigquery.Client(project='hotelops-suite')
q = '''SELECT MAX(DATE(data_evento)) al, COUNT(*) n
       FROM hotelops.f_pec_messages WHERE entity_id=\"VIGNA\"'''
for r in c.query(q): print(f'VIGNA: {r.n} buste, ultima {r.al}')
"
```

Expected: conteggio superiore a 107 e data più recente dell'08/07.

- [ ] **Step 4: Creare il Cloud Run Job ed eseguirlo**

```bash
gcloud run jobs deploy pec-fetch-daily \
  --source . --region=europe-west1 --project=hotelops-suite \
  --command=python --args=-m,ingest.pec_fetch,--all \
  --set-secrets=PEC_PASSWORD_INTUR=pec-password-INTUR:latest,PEC_PASSWORD_ORTI=pec-password-ORTI:latest,PEC_PASSWORD_VIGNA=pec-password-VIGNA:latest \
  --max-retries=1 --task-timeout=15m

gcloud run jobs execute pec-fetch-daily --region=europe-west1 --wait
```

Expected: una riga `status=OK` per casella. Una `FAILED` dà exit 2 e nomina la casella — comportamento voluto.

- [ ] **Step 5: Schedulare e committare la nota**

```bash
gcloud scheduler jobs create http pec-fetch-daily-trigger \
  --location=europe-west1 --schedule="0 4 * * *" --time-zone="Europe/Rome" \
  --uri="https://run.googleapis.com/v2/projects/hotelops-suite/locations/europe-west1/jobs/pec-fetch-daily:run" \
  --http-method=POST --oauth-service-account-email=<SA del job>
```

```bash
git add docs/
git commit -m "docs(pec): comandi deploy del job pec-fetch-daily"
```

---

## Self-Review

**Copertura.** Sola lettura → Task 3 (`readonly=True` + test). SMTP mai → Task 1 (test sul registry) e Task 3. Watermark → Task 2, usato in Task 4. Content-hash → Task 4, due test. `eml` negli input_formats → Task 1, altrimenti il promote rifiuta ciò che il fetcher produce. Errore parziale → Task 4 (due test + exit 2). Finestra 7 giorni → Task 3 (`since_date`) e Task 4 (`--since-days`). Deploy e Secret Manager → Task 5.

**Placeholder.** Nessuno, tranne host e porta di `mpspec.it`, dichiarati in Task 1 con la via d'uscita esplicita (lasciare PERSONALE senza blocco `imap`: il fetcher la salta).

**Coerenza dei tipi.** `fetch_since(cfg, since_uid, since_date, conn_factory)` identica fra Task 3, i finti di Task 4 e la chiamata reale. `read_watermark(bucket, entity_id)` / `write_watermark(bucket, entity_id, uid)` coincidono fra Task 2 e Task 4. `intake_file(path, source_name=, actor=)` e `promote_raw_object(raw_object_id, actor=)` combaciano con `ingest/drive_fetch.py:104,118`. `ImapMailbox` (registry: host/port/password_env) e `ImapConfig` (runtime: + user/password) sono distinti di proposito: `user` viene da `sd.casella`, `password` da `os.environ`, e nessuno dei due può finire nel repo.
