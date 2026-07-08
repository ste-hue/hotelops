# PEC/MBOX Ingestion Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare 32 mbox PEC (in.tur@pec.it, 2018–2026, ~2,44 GB) in GCS via lineage e spacchettarli in `f_pec_messages` + `f_pec_allegati` su BigQuery, con dedup idempotente e report no-silent-skips.

**Architecture:** mbox → `hotelops intake` (GCS raw, dedup MD5 file) → `hotelops promote` → parser deterministico `ingest_pec_mbox.py` (due forme: busta con daticert / messaggio inviato raw) → righe validate Pydantic scritte via gate I1; allegati reali su GCS content-addressed (sha256); vista `v_pec_conversazioni` per il ciclo inviata→accettazione→consegna.

**Tech Stack:** Python 3.11, stdlib `mailbox`/`email`/`xml.etree`, Pydantic, google-cloud-bigquery/storage, pytest.

**Spec:** `docs/superpowers/specs/2026-07-08-pec-mbox-ingestion-design.md` — leggerla prima di iniziare.

## Global Constraints

- Ogni write BQ passa da `core.bq.write.bq_write_validated` (invariante I1). Mai `load_table_from_json` diretto per fatti.
- Ogni riga fatto porta `raw_object_id` (I9) e `hash_riga`.
- Parser deterministico: niente LLM (I5), niente euristiche sul filename — identità e forma SEMPRE dal contenuto.
- `source_folder = RECEIVED | SENT` è la semantica primaria (fatto osservato); "direzione" e altre derivazioni vivono solo nella vista.
- Nessuno skip silenzioso: ogni messaggio o produce una riga o incrementa un contatore visibile nel report.
- Convenzioni repo: `ruff format` + `ruff check` puliti; test in `tests/test_ingest_pec_mbox.py`; commit atomici, stage per nome (mai `git add .`).
- I file mbox reali NON entrano in git né nelle fixture: le fixture sono sintetiche, costruite in-test.

---

### Task 1: Costanti config + schemi Pydantic

**Files:**
- Modify: `core/config.py` (blocco costanti `F_*`)
- Modify: `core/schemas.py` (prima della sezione `# ── Validation helper`)
- Test: `tests/test_ingest_pec_mbox.py` (nuovo)

**Interfaces:**
- Produces: `core.config.F_PEC_MESSAGES`, `core.config.F_PEC_ALLEGATI` (str, `"<project>.hotelops.f_pec_..."`); `core.schemas.PecMessageRow`, `core.schemas.PecAllegatoRow`, `core.schemas.SourceFolderPec`, `core.schemas.TipoPec` — usati da tutti i task successivi.

- [ ] **Step 1: Scrivi i test che falliscono**

```python
# tests/test_ingest_pec_mbox.py
"""PEC mbox ingestion — schemi, parser, dedup, report."""

from datetime import datetime, timezone

import pytest

from core.schemas import PecAllegatoRow, PecMessageRow, validate_batch


def _msg_row(**over) -> dict:
    base = {
        "msgid": "opec296.20240325@pec.aruba.it",
        "source_folder": "RECEIVED",
        "tipo": "POSTA_CERTIFICATA",
        "ref_msgid": None,
        "data_evento": datetime(2024, 3, 25, 10, 0, tzinfo=timezone.utc),
        "data_certificata": True,
        "mittente": "avvocato@pec.studiolegale.it",
        "destinatari": "in.tur@pec.it",
        "n_destinatari": 1,
        "subject": "Diffida",
        "body_text": "testo",
        "provider": "pec.aruba.it",
        "casella": "in.tur@pec.it",
        "societa_id": "INTUR",
        "n_allegati": 1,
        "ha_postacert": True,
        "parse_warning": None,
        "hash_riga": "abc123",
        "raw_object_id": "raw-001",
        "data_caricamento": datetime(2026, 7, 8, 12, 0),
    }
    base.update(over)
    return base


def test_pec_message_row_valida():
    validate_batch([_msg_row()], PecMessageRow, context="test")


def test_pec_message_row_rifiuta_source_folder_invalido():
    from core.schemas import SchemaViolationError

    with pytest.raises(SchemaViolationError):
        validate_batch([_msg_row(source_folder="INBOX")], PecMessageRow, context="test")


def test_pec_message_row_rifiuta_msgid_vuoto():
    from core.schemas import SchemaViolationError

    with pytest.raises(SchemaViolationError):
        validate_batch([_msg_row(msgid="  ")], PecMessageRow, context="test")


def test_pec_allegato_row_valida():
    row = {
        "msgid": "opec296.20240325@pec.aruba.it",
        "nome_file": "BILANCIO 2020.pdf",
        "mime_type": "application/pdf",
        "size_bytes": 12345,
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "is_firmato": False,
        "gcs_uri": "gs://hotelops-raw/PEC_MAILBOX_INTUR_APPEND/allegati/e3b0/BILANCIO 2020.pdf",
        "hash_riga": "def456",
        "raw_object_id": "raw-001",
        "data_caricamento": datetime(2026, 7, 8, 12, 0),
    }
    validate_batch([row], PecAllegatoRow, context="test")
```

- [ ] **Step 2: Verifica che falliscano**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: FAIL con `ImportError: cannot import name 'PecAllegatoRow'`

- [ ] **Step 3: Implementa costanti e schemi**

In `core/config.py`, dopo `F_SPIAGGIA_CORRISPETTIVI`:

```python
F_PEC_MESSAGES              = _t("f_pec_messages")
F_PEC_ALLEGATI              = _t("f_pec_allegati")
```

In `core/schemas.py`, prima di `# ── Validation helper`:

```python
# ── f_pec_messages / f_pec_allegati ──────────────────────────────────────────

SourceFolderPec = Literal["RECEIVED", "SENT"]
TipoPec = Literal[
    "POSTA_CERTIFICATA",
    "ACCETTAZIONE",
    "CONSEGNA",
    "ANOMALIA",
    "MESSAGGIO_INVIATO",
    "ALTRO",
]


class PecMessageRow(BaseModel):
    """Schema for f_pec_messages — una riga per busta PEC ricevuta o messaggio inviato.

    Le ricevute (ACCETTAZIONE/CONSEGNA) sono righe autonome: fatti immutabili,
    linkate al messaggio originale via ref_msgid. source_folder è il fatto
    osservato (derivato dall'anatomia: busta ⇒ RECEIVED, raw ⇒ SENT); ogni
    semantica derivata vive in v_pec_conversazioni. Fatti documentali, non
    finanziari: I4 non applicabile. Lifecycle: APPEND, dedup su hash_riga=md5(msgid).
    """

    msgid: str
    source_folder: SourceFolderPec
    tipo: TipoPec
    ref_msgid: Optional[str] = None
    data_evento: datetime
    data_certificata: bool
    mittente: Optional[str] = None
    destinatari: Optional[str] = None  # ";"-joined
    n_destinatari: int = 0
    subject: Optional[str] = None
    body_text: Optional[str] = None
    provider: Optional[str] = None  # dominio busta — solo RECEIVED
    casella: str
    societa_id: SocietaId
    n_allegati: int = 0
    ha_postacert: bool = False
    parse_warning: Optional[str] = None
    hash_riga: str
    raw_object_id: str
    data_caricamento: datetime

    @field_validator("msgid", "casella", "hash_riga", "raw_object_id")
    @classmethod
    def pec_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("campo vuoto")
        return v


class PecAllegatoRow(BaseModel):
    """Schema for f_pec_allegati — un allegato reale trasmesso in una PEC.

    Esclusi gli artefatti di busta (daticert.xml, smime.p7s, postacert.eml).
    Il binario vive su GCS content-addressed; gcs_uri è NULL solo se
    l'estrazione è fallita (parse_warning sul messaggio). APPEND, dedup su
    hash_riga=md5(msgid|sha256|nome_file).
    """

    msgid: str
    nome_file: str
    mime_type: Optional[str] = None
    size_bytes: int = 0
    sha256: str
    is_firmato: bool = False
    gcs_uri: Optional[str] = None
    hash_riga: str
    raw_object_id: str
    data_caricamento: datetime

    @field_validator("msgid", "nome_file", "sha256", "hash_riga", "raw_object_id")
    @classmethod
    def pec_all_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("campo vuoto")
        return v
```

- [ ] **Step 4: Verifica che passino**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: `4 passed`

- [ ] **Step 5: Lint + commit**

```bash
ruff format core/schemas.py core/config.py tests/test_ingest_pec_mbox.py
ruff check core/schemas.py core/config.py tests/test_ingest_pec_mbox.py
git add core/config.py core/schemas.py tests/test_ingest_pec_mbox.py
git commit -m "feat(pec): schemi PecMessageRow/PecAllegatoRow + costanti config"
```

---

### Task 2: Entry nel source registry

**Files:**
- Modify: `core/source_registry.yaml` (dopo il blocco `POWERBI_BOOKINGSTIPOLOGIA_ORTI_SNAPSHOT`)
- Test: `tests/test_ingest_pec_mbox.py` (append)

**Interfaces:**
- Produces: source `PEC_MAILBOX_INTUR_APPEND` risolvibile via `core.lineage.source_resolver.load_registry()` — usata dall'esecuzione (Task 8) per `hotelops intake --source-name`.

- [ ] **Step 1: Scrivi il test che fallisce**

Append a `tests/test_ingest_pec_mbox.py`:

```python
def test_registry_pec_mailbox_intur():
    from core.lineage.source_resolver import load_registry

    reg = load_registry()
    s = reg.resolve("pec_mbox", "INTUR")
    assert s.source_name == "PEC_MAILBOX_INTUR_APPEND"
    assert s.canonical_table == "f_pec_messages"
    assert s.parser_module == "ingest.flussi.ingest_pec_mbox"
    assert s.promotion_policy == "AUTO"
    assert s.loop_targets == ["pec_archive"]
```

- [ ] **Step 2: Verifica che fallisca**

Run: `python -m pytest tests/test_ingest_pec_mbox.py::test_registry_pec_mailbox_intur -q`
Expected: FAIL (lookup senza match)

- [ ] **Step 3: Aggiungi l'entry al registry**

In `core/source_registry.yaml`, dopo il blocco BOOKINGSTIPOLOGIA:

```yaml
  # ── PEC in.tur@pec.it — buste ricevute + inviate (export webmail mbox) ────
  PEC_MAILBOX_INTUR_APPEND:
    system: PEC
    dataset: MAILBOX
    dataset_label: "PEC in.tur@pec.it — buste ricevute + messaggi inviati (export webmail mbox)"
    societa: INTUR
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
      bucket: hotelops-raw
      path_template: "pec/mailbox/INTUR"
    notes: |
      Archeologia aziendale: export mbox della webmail PEC (received 2021→,
      sent 2018→). Due forme distinte dal CONTENUTO (mai dal filename):
      busta di trasporto (From=posta-certificata@..., daticert.xml autoritativo)
      e messaggio inviato (From=casella, raw). Il parser scrive anche
      f_pec_allegati e carica gli allegati reali su GCS content-addressed.
      Dedup a 3 livelli: file (MD5 intake), messaggio (msgid certificato),
      allegato (sha256). Spec: docs/superpowers/specs/2026-07-08-pec-mbox-*.md.
      Nuove caselle (es. ORTI) = nuove entry con la stessa grammar.
```

- [ ] **Step 4: Verifica che passi**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add core/source_registry.yaml tests/test_ingest_pec_mbox.py
git commit -m "feat(registry): source PEC_MAILBOX_INTUR_APPEND (AUTO, loop pec_archive)"
```

---

### Task 3: Parse daticert.xml + classificazione forma/tipo

**Files:**
- Create: `ingest/flussi/ingest_pec_mbox.py`
- Test: `tests/test_ingest_pec_mbox.py` (append)

**Interfaces:**
- Produces: `parse_daticert(xml_bytes: bytes) -> dict` con chiavi `msgid, tipo_raw, mittente, destinatari (list[str]), data_evento (datetime|None), ref_msgid (str|None)`; `is_busta(msg: email.message.Message) -> bool`; `map_tipo(tipo_raw: str | None, subject: str, is_busta: bool) -> str` (valori di `TipoPec`).

- [ ] **Step 1: Scrivi i test che falliscono**

Append a `tests/test_ingest_pec_mbox.py`:

```python
DATICERT_CONSEGNA = b"""<?xml version="1.0" encoding="UTF-8"?>
<postacert tipo="avvenuta-consegna" errore="nessuno">
  <intestazione>
    <mittente>in.tur@pec.it</mittente>
    <destinatari tipo="certificato">controparte@pec.it</destinatari>
    <oggetto>Disdetta contratto</oggetto>
  </intestazione>
  <dati>
    <gestore-emittente>Aruba PEC S.p.A.</gestore-emittente>
    <data zona="+0200"><giorno>25/03/2024</giorno><ora>10:15:32</ora></data>
    <identificativo>opec296.consegna.123@pec.aruba.it</identificativo>
    <msgid>&lt;original.msgid.456@pec.it&gt;</msgid>
    <ricevuta tipo="completa"/>
    <consegna>controparte@pec.it</consegna>
  </dati>
</postacert>"""


def test_parse_daticert_consegna():
    from ingest.flussi.ingest_pec_mbox import parse_daticert

    d = parse_daticert(DATICERT_CONSEGNA)
    assert d["tipo_raw"] == "avvenuta-consegna"
    assert d["msgid"] == "opec296.consegna.123@pec.aruba.it"
    assert d["ref_msgid"] == "original.msgid.456@pec.it"  # senza <>
    assert d["mittente"] == "in.tur@pec.it"
    assert d["destinatari"] == ["controparte@pec.it"]
    assert d["data_evento"].year == 2024 and d["data_evento"].month == 3


def test_parse_daticert_malformato_ritorna_none():
    from ingest.flussi.ingest_pec_mbox import parse_daticert

    assert parse_daticert(b"not xml at all <<<") is None


def test_is_busta():
    import email.message

    from ingest.flussi.ingest_pec_mbox import is_busta

    busta = email.message.EmailMessage()
    busta["From"] = "Per conto di X <posta-certificata@pec.aruba.it>"
    inviata = email.message.EmailMessage()
    inviata["From"] = "in.tur <in.tur@pec.it>"
    assert is_busta(busta) is True
    assert is_busta(inviata) is False


def test_map_tipo():
    from ingest.flussi.ingest_pec_mbox import map_tipo

    assert map_tipo("posta-certificata", "x", True) == "POSTA_CERTIFICATA"
    assert map_tipo("accettazione", "x", True) == "ACCETTAZIONE"
    assert map_tipo("avvenuta-consegna", "x", True) == "CONSEGNA"
    assert map_tipo("errore-consegna", "x", True) == "ANOMALIA"
    # fallback dal subject quando daticert manca
    assert map_tipo(None, "CONSEGNA: Disdetta", True) == "CONSEGNA"
    assert map_tipo(None, "ACCETTAZIONE: Disdetta", True) == "ACCETTAZIONE"
    assert map_tipo(None, "POSTA CERTIFICATA: Diffida", True) == "POSTA_CERTIFICATA"
    assert map_tipo(None, "qualunque", True) == "ALTRO"
    # inviata: sempre MESSAGGIO_INVIATO
    assert map_tipo(None, "qualunque", False) == "MESSAGGIO_INVIATO"
```

- [ ] **Step 2: Verifica che falliscano**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'ingest.flussi.ingest_pec_mbox'`

- [ ] **Step 3: Crea il modulo con le tre funzioni**

```python
# ingest/flussi/ingest_pec_mbox.py
#!/usr/bin/env python3
"""Ingest export mbox PEC → f_pec_messages + f_pec_allegati.

Due forme, distinte dal CONTENUTO (mai dal filename):
  - busta di trasporto (From=posta-certificata@...): daticert.xml è la verità
    certificata (msgid, mittente reale, timestamp opponibile, ref al messaggio
    originale per le ricevute); postacert.eml è il messaggio reale.
  - messaggio inviato (From=casella): raw, niente daticert; il timestamp
    certificato arriva dal link con la ricevuta di ACCETTAZIONE (ref_msgid).

Parser_module della source PEC_MAILBOX_INTUR_APPEND, invocato da
`hotelops promote` come: python -m ingest.flussi.ingest_pec_mbox --file X --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_pec_mbox --file <mbox> --raw-object-id <id>
    python -m ingest.flussi.ingest_pec_mbox --file <mbox> --dry-run
"""
from __future__ import annotations

import argparse
import email.message
import email.utils
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

log = logging.getLogger("ingest.pec_mbox")

CASELLA = "in.tur@pec.it"
SOCIETA = "INTUR"

# Nomi degli artefatti di busta: non sono allegati reali.
ARTEFATTI_BUSTA = {"daticert.xml", "postacert.eml", "smime.p7s"}

TIPO_MAP = {
    "posta-certificata": "POSTA_CERTIFICATA",
    "accettazione": "ACCETTAZIONE",
    "avvenuta-consegna": "CONSEGNA",
    "presa-in-carico": "ALTRO",
    "non-accettazione": "ANOMALIA",
    "errore-consegna": "ANOMALIA",
    "preavviso-errore-consegna": "ANOMALIA",
    "rilevazione-virus": "ANOMALIA",
}

SUBJECT_PREFIX_MAP = [
    ("POSTA CERTIFICATA", "POSTA_CERTIFICATA"),
    ("ACCETTAZIONE", "ACCETTAZIONE"),
    ("AVVENUTA CONSEGNA", "CONSEGNA"),
    ("CONSEGNA", "CONSEGNA"),
    ("ANOMALIA", "ANOMALIA"),
    ("MANCATA CONSEGNA", "ANOMALIA"),
]


def is_busta(msg: email.message.Message) -> bool:
    """Busta di trasporto PEC ⇔ From = posta-certificata@<provider>."""
    fr = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
    return fr.startswith("posta-certificata@")


def parse_daticert(xml_bytes: bytes) -> dict | None:
    """daticert.xml → dict con la verità certificata. None se malformato."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    def _text(path: str) -> str | None:
        el = root.find(path)
        return el.text.strip() if el is not None and el.text else None

    giorno, ora = _text(".//data/giorno"), _text(".//data/ora")
    data_evento = None
    if giorno and ora:
        try:
            data_evento = datetime.strptime(f"{giorno} {ora}", "%d/%m/%Y %H:%M:%S")
        except ValueError:
            pass

    ref = _text(".//riferimento-messaggio") or _text(".//msgid")
    return {
        "tipo_raw": root.get("tipo"),
        "msgid": _text(".//identificativo"),
        "ref_msgid": ref.strip("<>") if ref else None,
        "mittente": _text(".//intestazione/mittente"),
        "destinatari": [
            el.text.strip()
            for el in root.findall(".//intestazione/destinatari")
            if el.text
        ],
        "data_evento": data_evento,
    }


def map_tipo(tipo_raw: str | None, subject: str, busta: bool) -> str:
    """Tipo canonico: daticert autoritativo, subject come fallback, ALTRO onesto."""
    if not busta:
        return "MESSAGGIO_INVIATO"
    if tipo_raw and tipo_raw in TIPO_MAP:
        return TIPO_MAP[tipo_raw]
    subj = (subject or "").upper()
    for prefix, tipo in SUBJECT_PREFIX_MAP:
        if subj.startswith(prefix):
            return tipo
    return "ALTRO"
```

- [ ] **Step 4: Verifica che passino**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: `9 passed`

- [ ] **Step 5: Lint + commit**

```bash
ruff format ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
ruff check ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
git add ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
git commit -m "feat(pec): parse daticert + classificazione busta/inviata e tipo"
```

---

### Task 4: Estrazione body text + allegati reali

**Files:**
- Modify: `ingest/flussi/ingest_pec_mbox.py`
- Test: `tests/test_ingest_pec_mbox.py` (append)

**Interfaces:**
- Consumes: `ARTEFATTI_BUSTA` (Task 3)
- Produces: `estrai_body_text(msg: email.message.Message) -> str | None`; `inner_message(msg: email.message.Message) -> tuple[email.message.Message, bool]` (il messaggio reale: postacert se presente, altrimenti la busta stessa; bool = ha_postacert); `iter_allegati_reali(msg: email.message.Message) -> list[tuple[str, bytes, str]]` (nome, contenuto, mime).

- [ ] **Step 1: Scrivi i test che falliscono**

```python
def _busta_con_postacert() -> "email.message.EmailMessage":
    import email.message

    inner = email.message.EmailMessage()
    inner["From"] = "avvocato@pec.studiolegale.it"
    inner["To"] = "in.tur@pec.it"
    inner["Subject"] = "Diffida"
    inner["Message-ID"] = "<original.msgid.456@pec.it>"
    inner.set_content("Testo della diffida.")
    inner.add_attachment(
        b"%PDF-fake", maintype="application", subtype="pdf", filename="Diffida.pdf"
    )
    inner.add_attachment(
        b"firmato", maintype="application", subtype="pkcs7-mime",
        filename="Delega.pdf.p7m",
    )

    busta = email.message.EmailMessage()
    busta["From"] = "Per conto di: avvocato <posta-certificata@pec.aruba.it>"
    busta["To"] = "in.tur@pec.it"
    busta["Subject"] = "POSTA CERTIFICATA: Diffida"
    busta.set_content("Messaggio di posta certificata (corpo busta).")
    busta.add_attachment(
        DATICERT_CONSEGNA, maintype="application", subtype="xml",
        filename="daticert.xml",
    )
    busta.add_attachment(
        inner.as_bytes(), maintype="message", subtype="rfc822",
        filename="postacert.eml",
    )
    return busta


def test_inner_message_spacchetta_postacert():
    from ingest.flussi.ingest_pec_mbox import inner_message

    inner, ha_postacert = inner_message(_busta_con_postacert())
    assert ha_postacert is True
    assert inner["Subject"] == "Diffida"


def test_inner_message_senza_postacert_ritorna_busta():
    import email.message

    from ingest.flussi.ingest_pec_mbox import inner_message

    busta = email.message.EmailMessage()
    busta["From"] = "posta-certificata@pec.aruba.it"
    busta["Subject"] = "ACCETTAZIONE: x"
    busta.set_content("ricevuta")
    inner, ha_postacert = inner_message(busta)
    assert ha_postacert is False
    assert inner is busta


def test_iter_allegati_reali_esclude_artefatti():
    from ingest.flussi.ingest_pec_mbox import inner_message, iter_allegati_reali

    inner, _ = inner_message(_busta_con_postacert())
    allegati = iter_allegati_reali(inner)
    nomi = [a[0] for a in allegati]
    assert nomi == ["Diffida.pdf", "Delega.pdf.p7m"]
    assert allegati[0][1] == b"%PDF-fake"
    assert allegati[0][2] == "application/pdf"


def test_estrai_body_text():
    from ingest.flussi.ingest_pec_mbox import estrai_body_text, inner_message

    inner, _ = inner_message(_busta_con_postacert())
    assert "Testo della diffida" in estrai_body_text(inner)
```

- [ ] **Step 2: Verifica che falliscano**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: FAIL con `ImportError: cannot import name 'inner_message'`

- [ ] **Step 3: Implementa le tre funzioni**

Append a `ingest/flussi/ingest_pec_mbox.py`:

```python
def inner_message(
    msg: email.message.Message,
) -> tuple[email.message.Message, bool]:
    """Il messaggio reale: postacert.eml se presente, altrimenti la busta stessa.

    Le ricevute di accettazione spesso non hanno postacert: è normale (il
    contenuto informativo è nel daticert), non un errore.
    """
    import email as email_pkg

    for part in msg.walk():
        if (part.get_filename() or "").lower() == "postacert.eml":
            payload = part.get_payload(decode=True)
            if payload is None:  # message/rfc822: payload è già un Message
                sub = part.get_payload()
                if isinstance(sub, list) and sub:
                    return sub[0], True
            else:
                return email_pkg.message_from_bytes(payload), True
    return msg, False


def estrai_body_text(msg: email.message.Message) -> str | None:
    """text/plain preferito; niente HTML raw, niente binari."""
    for part in msg.walk():
        if part.get_content_type() == "text/plain" and not part.get_filename():
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace").strip()
    return None


def iter_allegati_reali(msg: email.message.Message) -> list[tuple[str, bytes, str]]:
    """(nome, bytes, mime) per ogni allegato reale — esclusi artefatti busta."""
    out: list[tuple[str, bytes, str]] = []
    for part in msg.walk():
        nome = part.get_filename()
        if not nome or nome.lower() in ARTEFATTI_BUSTA:
            continue
        if part.get_content_disposition() != "attachment":
            continue
        content = part.get_payload(decode=True)
        if content is None:
            continue
        out.append((nome, content, part.get_content_type()))
    return out
```

- [ ] **Step 4: Verifica che passino**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: `13 passed`

- [ ] **Step 5: Lint + commit**

```bash
ruff format ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
ruff check ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
git add ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
git commit -m "feat(pec): spacchettamento postacert, body text, allegati reali"
```

---

### Task 5: Store allegati content-addressed su GCS

**Files:**
- Modify: `ingest/flussi/ingest_pec_mbox.py`
- Test: `tests/test_ingest_pec_mbox.py` (append)

**Interfaces:**
- Produces: `class AllegatiStore(bucket_name: str = "hotelops-raw", dry_run: bool = False, client=None)` con metodo `store(nome: str, content: bytes) -> tuple[str, str]` → `(sha256_hex, gcs_uri)`. In dry_run non tocca la rete e ritorna l'URI calcolato. `client` iniettabile per i test (deve esporre `.bucket(name).blob(path)` con `.exists()` e `.upload_from_string(data, content_type=...)`).

- [ ] **Step 1: Scrivi i test che falliscono**

```python
class _FakeBlob:
    def __init__(self, store, path):
        self.store, self.path = store, path

    def exists(self):
        return self.path in self.store

    def upload_from_string(self, data, content_type=None):
        self.store[self.path] = data


class _FakeBucket:
    def __init__(self, store):
        self.store = store

    def blob(self, path):
        return _FakeBlob(self.store, path)


class _FakeGcsClient:
    def __init__(self):
        self.store = {}

    def bucket(self, name):
        return _FakeBucket(self.store)


def test_allegati_store_content_addressed():
    from ingest.flussi.ingest_pec_mbox import AllegatiStore

    client = _FakeGcsClient()
    s = AllegatiStore(dry_run=False, client=client)
    sha1, uri1 = s.store("Diffida.pdf", b"%PDF-fake")
    sha2, uri2 = s.store("Copia di Diffida.pdf", b"%PDF-fake")  # stesso contenuto
    assert sha1 == sha2
    assert len(client.store) == 2  # due path (nome diverso) ...
    assert uri1.startswith("gs://hotelops-raw/PEC_MAILBOX_INTUR_APPEND/allegati/")
    assert sha1[:8] in uri1
    # ... ma ricaricare lo stesso (nome, contenuto) non riscrive
    before = dict(client.store)
    s.store("Diffida.pdf", b"%PDF-fake")
    assert client.store == before


def test_allegati_store_dry_run_non_tocca_rete():
    from ingest.flussi.ingest_pec_mbox import AllegatiStore

    s = AllegatiStore(dry_run=True, client=None)  # client None: se lo tocca, esplode
    sha, uri = s.store("x.pdf", b"abc")
    assert uri.startswith("gs://")
```

- [ ] **Step 2: Verifica che falliscano**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: FAIL con `ImportError: cannot import name 'AllegatiStore'`

- [ ] **Step 3: Implementa AllegatiStore**

Append a `ingest/flussi/ingest_pec_mbox.py`:

```python
import hashlib

SOURCE_NAME = "PEC_MAILBOX_INTUR_APPEND"


class AllegatiStore:
    """Binari allegati su GCS, indirizzati per contenuto.

    Path: <SOURCE_NAME>/allegati/<sha256[:2]>/<sha256>/<nome> — lo stesso
    contenuto trasmesso N volte è un solo oggetto per nome; il fan-out sulle
    trasmissioni vive nelle righe f_pec_allegati.
    """

    def __init__(self, bucket_name: str = "hotelops-raw", dry_run: bool = False, client=None):
        self.bucket_name = bucket_name
        self.dry_run = dry_run
        self._client = client
        self.n_uploaded = 0
        self.n_riusati = 0

    def _get_client(self):
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client()
        return self._client

    def store(self, nome: str, content: bytes) -> tuple[str, str]:
        sha = hashlib.sha256(content).hexdigest()
        path = f"{SOURCE_NAME}/allegati/{sha[:2]}/{sha}/{nome}"
        uri = f"gs://{self.bucket_name}/{path}"
        if self.dry_run:
            return sha, uri
        blob = self._get_client().bucket(self.bucket_name).blob(path)
        if blob.exists():
            self.n_riusati += 1
        else:
            blob.upload_from_string(content, content_type="application/octet-stream")
            self.n_uploaded += 1
        return sha, uri
```

- [ ] **Step 4: Verifica che passino**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: `15 passed`

- [ ] **Step 5: Lint + commit**

```bash
ruff format ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
ruff check ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
git add ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
git commit -m "feat(pec): AllegatiStore content-addressed su GCS (dry-run e client iniettabile)"
```

---

### Task 6: extract_message — dalle forme alle righe

**Files:**
- Modify: `ingest/flussi/ingest_pec_mbox.py`
- Test: `tests/test_ingest_pec_mbox.py` (append)

**Interfaces:**
- Consumes: tutto da Task 3-5.
- Produces: `extract_message(msg, raw_object_id: str, store: AllegatiStore, now: datetime) -> tuple[dict, list[dict]]` — (riga f_pec_messages come dict, righe f_pec_allegati come dict). Usa `make_hash` di core.schemas per `hash_riga`.

- [ ] **Step 1: Scrivi i test che falliscano**

```python
def _extract(msg):
    from datetime import datetime

    from ingest.flussi.ingest_pec_mbox import AllegatiStore, extract_message

    return extract_message(
        msg, raw_object_id="raw-001",
        store=AllegatiStore(dry_run=True),
        now=datetime(2026, 7, 8, 12, 0),
    )


def test_extract_busta_completa():
    riga, allegati = _extract(_busta_con_postacert())
    assert riga["source_folder"] == "RECEIVED"
    assert riga["tipo"] == "CONSEGNA"  # dal daticert (autoritativo), non dal subject
    assert riga["msgid"] == "opec296.consegna.123@pec.aruba.it"
    assert riga["ref_msgid"] == "original.msgid.456@pec.it"
    assert riga["mittente"] == "in.tur@pec.it"  # dal daticert, non dalla busta
    assert riga["data_certificata"] is True
    assert riga["provider"] == "pec.aruba.it"
    assert riga["ha_postacert"] is True
    assert riga["subject"] == "Diffida"  # del messaggio reale
    assert riga["n_allegati"] == 2
    assert riga["parse_warning"] is None
    assert len(allegati) == 2
    assert allegati[1]["is_firmato"] is True  # .p7m
    assert allegati[0]["gcs_uri"].startswith("gs://")


def test_extract_inviata():
    import email.message

    inviata = email.message.EmailMessage()
    inviata["From"] = "in.tur@pec.it"
    inviata["To"] = "a@pec.it, b@pec.it"
    inviata["Subject"] = "Disdetta"
    inviata["Message-ID"] = "<sent.789@pec.it>"
    inviata["Date"] = "Mon, 25 Mar 2024 10:00:00 +0100"
    inviata.set_content("testo disdetta")

    riga, allegati = _extract(inviata)
    assert riga["source_folder"] == "SENT"
    assert riga["tipo"] == "MESSAGGIO_INVIATO"
    assert riga["msgid"] == "sent.789@pec.it"
    assert riga["data_certificata"] is False  # Date header, non daticert
    assert riga["n_destinatari"] == 2
    assert riga["provider"] is None
    assert allegati == []


def test_extract_busta_senza_daticert_ha_warning_e_msgid_sintetico():
    import email.message

    busta = email.message.EmailMessage()
    busta["From"] = "posta-certificata@pec.aruba.it"
    busta["Subject"] = "ACCETTAZIONE: Disdetta"
    busta["Date"] = "Mon, 25 Mar 2024 10:00:00 +0100"
    busta.set_content("ricevuta di accettazione")

    riga, _ = _extract(busta)
    assert riga["tipo"] == "ACCETTAZIONE"  # fallback dal subject
    assert riga["parse_warning"] is not None
    assert riga["msgid"]  # sintetico ma presente (sha256 del raw)
    assert riga["data_certificata"] is False


def test_extract_idempotente_hash_stabile():
    r1, _ = _extract(_busta_con_postacert())
    r2, _ = _extract(_busta_con_postacert())
    assert r1["hash_riga"] == r2["hash_riga"]
```

- [ ] **Step 2: Verifica che falliscano**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: FAIL con `ImportError: cannot import name 'extract_message'`

- [ ] **Step 3: Implementa extract_message**

Append a `ingest/flussi/ingest_pec_mbox.py`:

```python
from core.schemas import make_hash


def _msgid_sintetico(msg: email.message.Message) -> str:
    return "synthetic-" + hashlib.sha256(bytes(msg)).hexdigest()[:32]


def extract_message(
    msg: email.message.Message,
    raw_object_id: str,
    store: AllegatiStore,
    now: datetime,
) -> tuple[dict, list[dict]]:
    """Una busta/inviata → (riga f_pec_messages, righe f_pec_allegati)."""
    busta = is_busta(msg)
    warning = None

    daticert = None
    if busta:
        for part in msg.walk():
            if (part.get_filename() or "").lower() == "daticert.xml":
                daticert = parse_daticert(part.get_payload(decode=True) or b"")
                break
        if daticert is None:
            warning = "daticert assente o malformato: fallback su header busta"

    inner, ha_postacert = inner_message(msg) if busta else (msg, False)

    # msgid: daticert (certificato) > Message-ID header > sintetico
    header_msgid = (str(msg.get("Message-ID", "")) or "").strip().strip("<>")
    if daticert and daticert.get("msgid"):
        msgid = daticert["msgid"]
    elif header_msgid:
        msgid = header_msgid
    else:
        msgid = _msgid_sintetico(msg)
        warning = (warning or "") + " msgid sintetico da sha256"

    # data: daticert (certificata) > Date header
    data_evento, certificata = None, False
    if daticert and daticert.get("data_evento"):
        data_evento, certificata = daticert["data_evento"], True
    else:
        try:
            data_evento = email.utils.parsedate_to_datetime(str(msg.get("Date")))
        except (TypeError, ValueError):
            warning = (warning or "") + " data non parsabile"
    if data_evento is not None and data_evento.tzinfo is not None:
        data_evento = data_evento.astimezone(tz=None).replace(tzinfo=None)

    if daticert and daticert.get("mittente"):
        mittente = daticert["mittente"]
        destinatari = daticert.get("destinatari") or []
    else:
        mittente = email.utils.parseaddr(str(inner.get("From", "")))[1] or None
        destinatari = [
            a for _, a in email.utils.getaddresses([str(inner.get("To", ""))]) if a
        ]

    provider = None
    if busta:
        fr_busta = email.utils.parseaddr(str(msg.get("From", "")))[1]
        provider = fr_busta.split("@", 1)[1] if "@" in fr_busta else None

    subject_inner = str(inner.get("Subject", "")) or str(msg.get("Subject", ""))

    allegati_rows: list[dict] = []
    for nome, content, mime in iter_allegati_reali(inner):
        sha, uri = store.store(nome, content)
        allegati_rows.append(
            {
                "msgid": msgid,
                "nome_file": nome,
                "mime_type": mime,
                "size_bytes": len(content),
                "sha256": sha,
                "is_firmato": nome.lower().endswith((".p7m", ".p7s")),
                "gcs_uri": uri,
                "hash_riga": make_hash(msgid, sha, nome),
                "raw_object_id": raw_object_id,
                "data_caricamento": now,
            }
        )

    riga = {
        "msgid": msgid,
        "source_folder": "RECEIVED" if busta else "SENT",
        "tipo": map_tipo(
            daticert.get("tipo_raw") if daticert else None, subject_inner, busta
        ),
        "ref_msgid": daticert.get("ref_msgid") if daticert else None,
        "data_evento": data_evento or now,
        "data_certificata": certificata,
        "mittente": mittente,
        "destinatari": ";".join(destinatari) or None,
        "n_destinatari": len(destinatari),
        "subject": subject_inner or None,
        "body_text": estrai_body_text(inner),
        "provider": provider,
        "casella": CASELLA,
        "societa_id": SOCIETA,
        "n_allegati": len(allegati_rows),
        "ha_postacert": ha_postacert,
        "parse_warning": warning.strip() if warning else None,
        "hash_riga": make_hash(msgid),
        "raw_object_id": raw_object_id,
        "data_caricamento": now,
    }
    return riga, allegati_rows
```

- [ ] **Step 4: Verifica che passino**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: `19 passed`

- [ ] **Step 5: Lint + commit**

```bash
ruff format ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
ruff check ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
git add ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
git commit -m "feat(pec): extract_message — busta/inviata/ricevuta-senza-postacert in righe"
```

---

### Task 7: ingest_file + report no-silent-skips + main()

**Files:**
- Modify: `ingest/flussi/ingest_pec_mbox.py`
- Test: `tests/test_ingest_pec_mbox.py` (append)

**Interfaces:**
- Consumes: `extract_message` (Task 6), `filter_new_rows_by_hash(table, rows, hash_column)` da `core.bq.dedup`, `bq_write_validated(table, rows, mode="append")` da `core.bq.write`, `F_PEC_MESSAGES`/`F_PEC_ALLEGATI` da config, `PecMessageRow`/`PecAllegatoRow`/`validate_batch`.
- Produces: `coverage_gaps(dates: list, min_gap_days: int = 14) -> list[tuple]`; `ingest_file(path: Path, raw_object_id: str | None, dry_run: bool) -> dict` (il report); `main()` con argparse `--file --raw-object-id --dry-run` (contratto del promote).

- [ ] **Step 1: Scrivi i test che falliscano**

```python
def test_coverage_gaps():
    from datetime import date

    from ingest.flussi.ingest_pec_mbox import coverage_gaps

    dates = [date(2024, 1, 1), date(2024, 1, 5), date(2024, 2, 20), date(2024, 2, 25)]
    gaps = coverage_gaps(dates, min_gap_days=14)
    assert gaps == [(date(2024, 1, 5), date(2024, 2, 20), 46)]
    assert coverage_gaps([], min_gap_days=14) == []


def test_ingest_file_dry_run_su_mbox_sintetico(tmp_path, monkeypatch):
    import mailbox

    from ingest.flussi import ingest_pec_mbox as mod

    mbox_path = tmp_path / "test.mbox"
    mb = mailbox.mbox(str(mbox_path))
    mb.add(_busta_con_postacert())
    mb.add(_busta_con_postacert())  # duplicato esatto: stesso msgid
    mb.flush()

    report = mod.ingest_file(mbox_path, raw_object_id="raw-001", dry_run=True)
    assert report["messaggi_letti"] == 2
    assert report["righe_messaggi"] == 1  # dedup in-file su msgid
    assert report["dedup_in_file"] == 1
    assert report["righe_allegati"] == 2
    assert report["con_warning"] == 0
    assert report["per_tipo"] == {"CONSEGNA": 1}
```

- [ ] **Step 2: Verifica che falliscano**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q`
Expected: FAIL con `AttributeError ... coverage_gaps`

- [ ] **Step 3: Implementa report, ingest_file e main**

Append a `ingest/flussi/ingest_pec_mbox.py`:

```python
import mailbox
from collections import Counter

from core.config import F_PEC_ALLEGATI, F_PEC_MESSAGES
from core.schemas import PecAllegatoRow, PecMessageRow, validate_batch


def coverage_gaps(dates: list, min_gap_days: int = 14) -> list[tuple]:
    """Vuoti > min_gap_days nella serie date (per il report no-silent-skips)."""
    out = []
    ordered = sorted(set(dates))
    for prev, cur in zip(ordered, ordered[1:]):
        gap = (cur - prev).days
        if gap > min_gap_days:
            out.append((prev, cur, gap))
    return out


def ingest_file(path: Path, raw_object_id: str | None = None, dry_run: bool = False) -> dict:
    """Un mbox → righe nuove in f_pec_messages/f_pec_allegati + report."""
    store = AllegatiStore(dry_run=dry_run)
    now = datetime.now()

    righe: dict[str, dict] = {}          # msgid → riga (dedup in-file)
    allegati: dict[str, list[dict]] = {}  # msgid → righe allegato
    letti = dedup_in_file = 0

    for msg in mailbox.mbox(str(path)):
        letti += 1
        riga, alls = extract_message(msg, raw_object_id or "", store, now)
        if riga["msgid"] in righe:
            dedup_in_file += 1
            continue
        righe[riga["msgid"]] = riga
        allegati[riga["msgid"]] = alls

    msg_rows = list(righe.values())
    all_rows = [a for alls in allegati.values() for a in alls]

    dedup_bq = 0
    if not dry_run:
        from core.bq.dedup import filter_new_rows_by_hash
        from core.bq.write import bq_write_validated

        nuove = filter_new_rows_by_hash(F_PEC_MESSAGES, msg_rows, "hash_riga")
        dedup_bq = len(msg_rows) - len(nuove)
        nuovi_msgid = {r["msgid"] for r in nuove}
        nuove_all = [a for a in all_rows if a["msgid"] in nuovi_msgid]

        validate_batch(nuove, PecMessageRow, context="f_pec_messages")
        validate_batch(nuove_all, PecAllegatoRow, context="f_pec_allegati")
        if nuove:
            bq_write_validated(
                F_PEC_MESSAGES, [PecMessageRow(**r) for r in nuove], mode="append"
            )
        if nuove_all:
            bq_write_validated(
                F_PEC_ALLEGATI, [PecAllegatoRow(**a) for a in nuove_all], mode="append"
            )
        msg_rows, all_rows = nuove, nuove_all

    report = {
        "file": path.name,
        "messaggi_letti": letti,
        "dedup_in_file": dedup_in_file,
        "dedup_bq": dedup_bq,
        "righe_messaggi": len(msg_rows),
        "righe_allegati": len(all_rows),
        "con_warning": sum(1 for r in msg_rows if r["parse_warning"]),
        "senza_postacert": sum(1 for r in msg_rows if not r["ha_postacert"]),
        "per_tipo": dict(Counter(r["tipo"] for r in msg_rows)),
        "coverage_gaps": [
            (str(a), str(b), g)
            for a, b, g in coverage_gaps([r["data_evento"].date() for r in msg_rows])
        ],
        "allegati_caricati": store.n_uploaded,
        "allegati_riusati": store.n_riusati,
    }
    for k, v in report.items():
        log.info("  %s: %s", k, v)
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Ingest mbox PEC → f_pec_messages")
    ap.add_argument("--file", required=True, type=Path, help="export mbox PEC")
    ap.add_argument(
        "--raw-object-id", default=None,
        help="FK a f_raw_objects (stampato su ogni riga — promotion path)",
    )
    ap.add_argument("--dry-run", action="store_true", help="parse senza scrivere")
    args = ap.parse_args()

    report = ingest_file(args.file, raw_object_id=args.raw_object_id, dry_run=args.dry_run)
    log.info(
        "DONE %s: %d nuove righe messaggi, %d allegati",
        args.file.name, report["righe_messaggi"], report["righe_allegati"],
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verifica che passino tutti + suite intera**

Run: `python -m pytest tests/test_ingest_pec_mbox.py -q && python -m pytest tests/ -q -m "not bq" 2>&1 | tail -1`
Expected: `21 passed` e suite verde.

- [ ] **Step 5: Smoke dry-run su un file reale**

Run: `python -m ingest.flussi.ingest_pec_mbox --file "/Users/stefanodellapietra/Downloads/PEC Webmail Export.mbox" --dry-run`
Expected: report con `messaggi_letti: 80`, per_tipo con POSTA_CERTIFICATA/CONSEGNA/ACCETTAZIONE, 0 crash. Ispeziona i `con_warning` e annota nel PR eventuali pattern non previsti.

- [ ] **Step 6: Lint + commit**

```bash
ruff format ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
ruff check ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
git add ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py
git commit -m "feat(pec): ingest_file con dedup BQ, report no-silent-skips e main promote-ready"
```

---

### Task 8: Vista v_pec_conversazioni

**Files:**
- Create: `core/bq/views/v_pec_conversazioni.sql`
- Modify: `core/config.py` (costante vista)

**Interfaces:**
- Consumes: `f_pec_messages` (Task 1-7).
- Produces: vista `v_pec_conversazioni` — una riga per messaggio (MESSAGGIO_INVIATO o POSTA_CERTIFICATA) con stato del ciclo di consegna. Consumatori futuri (search/timeline) leggono da qui, mai ricostruendo il join.

- [ ] **Step 1: Scrivi la vista**

```sql
-- v_pec_conversazioni: un messaggio PEC + il suo ciclo certificato.
--
-- Grana: una riga per messaggio "primario" (MESSAGGIO_INVIATO dal sent,
-- POSTA_CERTIFICATA dal received). Le ricevute (ACCETTAZIONE/CONSEGNA/ANOMALIA)
-- si agganciano via ref_msgid. Ogni semantica derivata ("direzione", stato)
-- vive QUI, non nei fatti (I8).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_pec_conversazioni` AS

WITH ricevute AS (
  SELECT
    ref_msgid,
    MIN(IF(tipo = 'ACCETTAZIONE', data_evento, NULL)) AS data_accettazione,
    MIN(IF(tipo = 'CONSEGNA',     data_evento, NULL)) AS data_consegna,
    COUNTIF(tipo = 'CONSEGNA')                        AS n_consegne,
    COUNTIF(tipo = 'ANOMALIA')                        AS n_anomalie
  FROM `hotelops-suite.hotelops.f_pec_messages`
  WHERE ref_msgid IS NOT NULL
  GROUP BY ref_msgid
)

SELECT
  m.msgid,
  m.source_folder,
  CASE m.source_folder WHEN 'SENT' THEN 'INVIATA' ELSE 'RICEVUTA' END AS direzione,
  m.data_evento,
  m.data_certificata,
  m.mittente,
  m.destinatari,
  m.subject,
  m.n_allegati,
  r.data_accettazione,
  r.data_consegna,
  r.n_anomalie,
  CASE
    WHEN m.source_folder = 'RECEIVED'   THEN 'RICEVUTA'
    WHEN r.n_anomalie > 0               THEN 'ANOMALIA'
    WHEN r.data_consegna IS NOT NULL    THEN 'CONSEGNATA'
    WHEN r.data_accettazione IS NOT NULL THEN 'ACCETTATA'
    ELSE 'SENZA_RICEVUTE'
  END AS stato,
  m.casella,
  m.societa_id
FROM `hotelops-suite.hotelops.f_pec_messages` m
LEFT JOIN ricevute r
  ON r.ref_msgid = m.msgid
WHERE m.tipo IN ('MESSAGGIO_INVIATO', 'POSTA_CERTIFICATA')
```

- [ ] **Step 2: Aggiungi la costante**

In `core/config.py`, nel blocco `# Views`:

```python
V_PEC_CONVERSAZIONI         = _t("v_pec_conversazioni")
```

- [ ] **Step 3: Deploy e verifica**

```bash
bq query --use_legacy_sql=false < core/bq/views/v_pec_conversazioni.sql
```
Expected: `Replaced/Created hotelops-suite.hotelops.v_pec_conversazioni`. (Prima del run reale di Task 9 la vista è vuota: `SELECT COUNT(*)` = 0 è ok. NB: la vista compila solo se f_pec_messages esiste già — eseguire questo task DOPO il primo promote di Task 9, o creare prima la tabella con un promote di un solo file.)

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_pec_conversazioni.sql core/config.py
git commit -m "feat(pec): vista v_pec_conversazioni — ciclo inviata/accettazione/consegna"
```

---

### Task 9: Esecuzione — intake dei 32 file, promote, verifica

Questo task è operativo (nessun codice nuovo): mette il corpus al sicuro e lo promuove. Da eseguire con `gcloud auth` valida.

- [ ] **Step 1: Intake dei 32 mbox**

```bash
cd /Users/stefanodellapietra/dev/Projects/hotelops
for f in /Users/stefanodellapietra/Downloads/*.mbox; do
  hotelops intake "$f" --source-name PEC_MAILBOX_INTUR_APPEND
done
```
Expected: 32 intake; i quadruplicati byte-identici segnalati `deduped` (non è un errore). Annotare quanti oggetti unici risultano.

- [ ] **Step 2: Verifica raw objects**

```bash
bq query --use_legacy_sql=false 'SELECT COUNT(*) n, COUNT(DISTINCT content_hash) uniq FROM `hotelops-suite.hotelops.f_raw_objects` WHERE source_name="PEC_MAILBOX_INTUR_APPEND"'
```
Expected: `uniq` < 32 (i duplicati file-level collassati), tutti con raw_uri gs://.

- [ ] **Step 3: Promote di UN file, poi verifica, poi tutti**

Promuovi un file piccolo, controlla il report (warning, per_tipo), poi cicla sugli altri raw-object-id:

```bash
hotelops promote --raw-object-id <id-del-primo>
# report ok? allora:
for id in $(bq query --use_legacy_sql=false --format=csv 'SELECT raw_object_id FROM `hotelops-suite.hotelops.f_raw_objects` WHERE source_name="PEC_MAILBOX_INTUR_APPEND"' | tail -n +2); do
  hotelops promote --raw-object-id "$id"
done
```

- [ ] **Step 4: Verifiche output-based (mai exit-code-based)**

```sql
-- FK coverage (I9): 100%
SELECT COUNT(*) tot, COUNTIF(raw_object_id IS NOT NULL) con_fk
FROM `hotelops-suite.hotelops.f_pec_messages`;

-- dedup: zero doppioni su msgid
SELECT COUNT(*) - COUNT(DISTINCT msgid) AS doppioni FROM `hotelops-suite.hotelops.f_pec_messages`;

-- volumi attesi: ~1.500-2.300 messaggi totali (received unici + sent), per_tipo sensato
SELECT source_folder, tipo, COUNT(*) n FROM `hotelops-suite.hotelops.f_pec_messages` GROUP BY 1,2 ORDER BY 1,2;

-- copertura: received 2021-02→2026-07 continuo, sent 2018-06→2026-06
SELECT source_folder, MIN(DATE(data_evento)) dal, MAX(DATE(data_evento)) al
FROM `hotelops-suite.hotelops.f_pec_messages` GROUP BY 1;

-- ciclo consegna: le inviate con ricevute devono agganciarsi
SELECT stato, COUNT(*) FROM `hotelops-suite.hotelops.v_pec_conversazioni`
WHERE source_folder='SENT' GROUP BY 1;
```
Expected: con_fk = tot; doppioni = 0; una quota significativa di SENT in stato CONSEGNATA/ACCETTATA (se quasi tutte SENZA_RICEVUTE, il link ref_msgid non aggancia → indagare i formati di ref_msgid prima di dichiarare successo).

- [ ] **Step 5: Idempotenza sul corpus reale**

Ripromuovi un file già promosso: attese 0 righe nuove (`dedup_bq` = tutte).

- [ ] **Step 6: Chiusura**

STATUS.md: nuova voce sessione con volumi reali, warning trovati, gap flaggati. Commit docs.

---

## Self-Review (eseguita)

- **Spec coverage:** registry ✓(T2), due forme ✓(T3/T6), dedup 3 livelli ✓(intake/T7/T5), schema BQ ✓(T1), allegati GCS ✓(T5), vista ✓(T8), report no-silent-skips ✓(T7), error handling ✓(T6: warning/msgid sintetico; T3: daticert malformato → None), testing ✓(fixture sintetiche, idempotenza, dedup). Fuori scope rispettato (no LLM, no search).
- **Placeholder:** nessuno — ogni step ha codice o comando eseguibile.
- **Type consistency:** `extract_message(msg, raw_object_id, store, now)` coerente tra T6 e T7; `store(nome, content) -> (sha, uri)` coerente T5/T6; enum Literal T1 = valori prodotti in T3/T6.
- **Nota corretta in review:** `gcs_uri` è Optional nello schema (spec §error handling); la vista T8 richiede `f_pec_messages` esistente → ordine T9-step3(un file) prima del deploy vista è annotato in T8 step 3.
