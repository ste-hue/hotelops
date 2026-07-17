# PEC multi-casella + pannello CEO — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalizzare la pipeline PEC di hotelops a 4 caselle (INTUR, ORTI, VIGNA, STEFANO_PERSONALE), aggiungere classificazione spiegabile a ruleset versionato, projection dei documenti importanti sul pannello CEO Drive e digest di monitoraggio con checkpoint.

**Architecture:** Raw bucket separati per soggetto giuridico → parser unico con contesto risolto dal source registry (`--source` obbligatorio) → registro unificato BQ (`f_pec_messages` + `entity_id`) → classificatore (`core/pec_ruleset.yaml` → `f_pec_classificazioni`) → projection (`f_pec_panel_projections` canonico, Drive solo copia) + digest (`f_pec_digest_runs` checkpoint, markdown output umano).

**Tech Stack:** Python 3.11+, Pydantic v2, google-cloud-bigquery, google-cloud-storage, PyYAML, pytest. Repo: `/Users/stefanodellapietra/dev/Projects/hotelops`.

**Spec:** `docs/superpowers/specs/2026-07-17-pec-multicasella-pannello-ceo-design.md` — leggerla PRIMA di iniziare. Gli invarianti I-PEC-1…8 della spec sono requisiti di ogni task.

## Global Constraints

- `SocietaId` resta `Literal["ORTI", "INTUR"]` — NON estenderlo mai.
- Nuovo `EntityId = Literal["INTUR", "ORTI", "VIGNA", "STEFANO_PERSONALE"]`.
- GCS/BQ canonici; il mirror Drive (`AMM_CEO`) è solo projection. Nessuno stato applicativo vive solo su Drive.
- Whitelist projection: `PANEL_ENTITIES = ["INTUR", "ORTI", "VIGNA"]` — esclusione positiva, mai `!= PERSONALE`.
- Chiave projection: `md5(msgid|sha256|destination_path)`.
- Solo aggiunte sul pannello: mai delete/overwrite di file esistenti.
- Ogni scrittura BQ passa da `bq_write_validated` (I1 del repo).
- Nessuno skip silenzioso: tutto ciò che viene saltato compare in un report.
- Datetime BQ: wall time Roma naive (convenzione parser esistente, `TZ_ROMA`).
- Test: `pytest` dalla root del repo, venv del progetto.
- Commit frequenti, messaggi in stile repo (`feat:`/`fix:`/`spec:` + corpo breve).
- ⚠️ Il repo ha modifiche NON committate preesistenti a `core/schemas.py`, `core/source_registry.yaml`, `ingest/flussi/ingest_vendite_fb.py`: PRIMA del Task 1, mostrarle a Stefano (`git diff core/schemas.py core/source_registry.yaml`) e decidere con lui se committarle o stasharle. Non lavorare sopra un working tree ambiguo.

## File Structure

| File | Azione | Responsabilità |
|---|---|---|
| `core/schemas.py` | Modify | `EntityId`, `PecMessageRow.entity_id`, `PecClassificazioneRow`, `PecPanelProjectionRow`, `PecDigestRunRow` |
| `core/lineage/schemas.py` | Modify | `SourceDefinition` + `casella`/`entity_id`/`input_formats` |
| `core/source_registry.yaml` | Modify | 3 nuove entry PEC + campi nuovi sull'entry INTUR |
| `core/config.py` | Modify | Nuove tabelle, `PANEL_ENTITIES`, `PANEL_ROOT`, cartelle categoria |
| `core/pec_ruleset.yaml` | Create | Regole di classificazione versionate v1 |
| `core/bq/migrations/2026_07_17_add_entity_id_f_pec_messages.py` | Create | ALTER + backfill |
| `ingest/flussi/ingest_pec_mbox.py` | Modify | Generalizzazione: `PecSource`, `--source`, supporto .eml |
| `ingest/promotion.py` | Modify | Passa `--source` ai parser di sorgenti `system: PEC` |
| `ingest/pec/__init__.py` | Create | Package layer CEO |
| `ingest/pec/classify.py` | Create | Ruleset loader + classificatore + runner BQ |
| `ingest/pec/panel.py` | Create | sync-panel: projection su Drive |
| `ingest/pec/digest.py` | Create | Digest con checkpoint |
| `cli.py` | Modify | Sottocomando `pec` (classify / sync-panel / digest) |
| `scripts/bonifica_pec_manuali.py` | Create | Rimozione verificata copie manuali |
| `tests/test_pec_multicasella.py` | Create | Parser generalizzato + registry |
| `tests/test_pec_classify.py` | Create | Classificatore |
| `tests/test_pec_panel.py` | Create | Projection (incl. path traversal) |
| `tests/test_pec_digest.py` | Create | Digest/checkpoint |
| `tests/test_pec_e2e.py` | Create | Pipeline end-to-end su fixture |
| `tests/test_ingest_pec_mbox.py` | Modify | Adattamento firma `extract_message`/`ingest_file` |

---

### Task 1: EntityId e schema righe PEC

**Files:**
- Modify: `core/schemas.py` (riga ~23 per il tipo; classe `PecMessageRow` riga ~636)
- Test: `tests/test_pec_multicasella.py` (nuovo)
- Modify: `tests/test_ingest_pec_mbox.py` (builder `_msg_row`)

**Interfaces:**
- Produces: `EntityId = Literal["INTUR","ORTI","VIGNA","STEFANO_PERSONALE"]`; `PecMessageRow` con `entity_id: EntityId` e `societa_id: Optional[SocietaId] = None`. Tutti i task successivi usano questi nomi esatti.

- [ ] **Step 1: Scrivere i test che falliscono**

Creare `tests/test_pec_multicasella.py`:

```python
"""PEC multi-casella — EntityId, schema righe, registry, parser generalizzato."""

from __future__ import annotations

from datetime import datetime

import pytest

from core.schemas import PecMessageRow, validate_batch


def _row(**over) -> dict:
    base = {
        "msgid": "m1@pec.aruba.it",
        "source_folder": "RECEIVED",
        "tipo": "POSTA_CERTIFICATA",
        "ref_msgid": None,
        "data_evento": datetime(2026, 7, 1, 10, 0),
        "data_certificata": True,
        "mittente": "x@pec.it",
        "destinatari": "orti@pec.it",
        "n_destinatari": 1,
        "subject": "s",
        "body_text": None,
        "provider": "pec.aruba.it",
        "casella": "orti@pec.it",
        "entity_id": "ORTI",
        "societa_id": "ORTI",
        "n_allegati": 0,
        "ha_postacert": False,
        "parse_warning": None,
        "hash_riga": "h1",
        "raw_object_id": "raw-1",
        "data_caricamento": datetime(2026, 7, 17, 12, 0),
    }
    base.update(over)
    return base


def test_entity_id_literal_completo():
    from core.schemas import EntityId
    from typing import get_args

    assert set(get_args(EntityId)) == {"INTUR", "ORTI", "VIGNA", "STEFANO_PERSONALE"}


def test_societa_id_non_esteso():
    from core.schemas import SocietaId
    from typing import get_args

    assert set(get_args(SocietaId)) == {"ORTI", "INTUR"}


def test_riga_personale_senza_societa():
    row = _row(
        casella="stefanojunior.dellapietra@mpspec.it",
        entity_id="STEFANO_PERSONALE",
        societa_id=None,
    )
    validate_batch([row], PecMessageRow, context="test")


def test_riga_vigna_con_societa_rifiutata():
    from core.schemas import SchemaViolationError

    with pytest.raises(SchemaViolationError):
        validate_batch(
            [_row(entity_id="VIGNA", societa_id="VIGNA")], PecMessageRow, context="test"
        )


def test_entity_id_obbligatorio():
    from core.schemas import SchemaViolationError

    row = _row()
    del row["entity_id"]
    with pytest.raises(SchemaViolationError):
        validate_batch([row], PecMessageRow, context="test")
```

- [ ] **Step 2: Verificare che falliscano**

Run: `cd /Users/stefanodellapietra/dev/Projects/hotelops && pytest tests/test_pec_multicasella.py -v`
Expected: FAIL — `ImportError: cannot import name 'EntityId'`

- [ ] **Step 3: Implementare in `core/schemas.py`**

Alla riga ~23, accanto a `SocietaId`:

```python
SocietaId = Literal["ORTI", "INTUR"]
# Soggetti giuridici monitorati (PEC/pannello CEO). NON è SocietaId: la PEC
# personale è un perimetro documentale, non una società (spec 2026-07-17).
EntityId = Literal["INTUR", "ORTI", "VIGNA", "STEFANO_PERSONALE"]
```

In `PecMessageRow`, sostituire la riga `societa_id: SocietaId` con:

```python
    entity_id: EntityId
    societa_id: Optional[SocietaId] = None  # solo società; NULL per STEFANO_PERSONALE
```

Aggiornare il docstring della classe aggiungendo: `entity_id dal registry della
sorgente (I-PEC-2); societa_id deprecata nelle query nuove, popolata solo per
ORTI/INTUR.`

- [ ] **Step 4: Aggiornare il builder dei test esistenti**

In `tests/test_ingest_pec_mbox.py`, nel dict `base` di `_msg_row` aggiungere
dopo `"casella": "in.tur@pec.it",`:

```python
        "entity_id": "INTUR",
```

- [ ] **Step 5: Verificare che tutto passi**

Run: `pytest tests/test_pec_multicasella.py tests/test_ingest_pec_mbox.py -v`
Expected: i 5 test nuovi PASS; i test esistenti di schema PASS. I test del
parser che costruiscono righe via `extract_message` possono ancora fallire per
`entity_id` mancante — è atteso, si sistemano nel Task 4. Annotare quali sono.

- [ ] **Step 6: Commit**

```bash
git add core/schemas.py tests/test_pec_multicasella.py tests/test_ingest_pec_mbox.py
git commit -m "feat(pec): EntityId + entity_id su PecMessageRow (societa_id opzionale)"
```

---

### Task 2: SourceDefinition esteso + 3 nuove entry registry

**Files:**
- Modify: `core/lineage/schemas.py` (classe `SourceDefinition`, riga ~117)
- Modify: `core/source_registry.yaml` (entry `PEC_MAILBOX_INTUR_APPEND` + 3 nuove)
- Test: `tests/test_pec_multicasella.py` (append)

**Interfaces:**
- Produces: `SourceDefinition.casella: Optional[str]`, `.entity_id: Optional[EntityId]`, `.input_formats: list` — usati dal parser (Task 4) e da promotion (Task 5). Nomi sorgente esatti: `PEC_MAILBOX_ORTI_APPEND`, `PEC_MAILBOX_VIGNA_APPEND`, `PEC_MAILBOX_PERSONALE_APPEND`.

- [ ] **Step 1: Test che falliscono** — append a `tests/test_pec_multicasella.py`:

```python
def test_registry_quattro_sorgenti_pec():
    from core.lineage.source_resolver import load_registry

    reg = load_registry()
    attese = {
        "PEC_MAILBOX_INTUR_APPEND": ("in.tur@pec.it", "INTUR", "hotelops-raw"),
        "PEC_MAILBOX_ORTI_APPEND": ("orti@pec.it", "ORTI", "orti-raw"),
        "PEC_MAILBOX_VIGNA_APPEND": ("vineyardamalficoast@pec.it", "VIGNA", "vigna-raw"),
        "PEC_MAILBOX_PERSONALE_APPEND": (
            "stefanojunior.dellapietra@mpspec.it",
            "STEFANO_PERSONALE",
            "stefano-raw",
        ),
    }
    for name, (casella, entity, bucket) in attese.items():
        s = reg.get(name)
        assert s is not None, name
        assert s.casella == casella
        assert s.entity_id == entity
        assert s.raw_storage.bucket == bucket
        assert s.parser_module == "ingest.flussi.ingest_pec_mbox"
        assert s.system == "PEC"


def test_registry_personale_accetta_eml():
    from core.lineage.source_resolver import load_registry

    s = load_registry().get("PEC_MAILBOX_PERSONALE_APPEND")
    assert "eml" in s.input_formats


def test_source_pec_senza_casella_rifiutata():
    from core.lineage.schemas import SourceDefinition
    from pydantic import ValidationError

    base = dict(
        source_name="PEC_MAILBOX_TEST_APPEND",
        system="PEC",
        dataset="MAILBOX",
        societa="INTUR",
        lifecycle="APPEND",
        canonical_table="f_pec_messages",
        parser_module="ingest.flussi.ingest_pec_mbox",
        promotion_policy="AUTO",
        detector_category="pec_mbox",
        raw_storage={"backend": "gcs", "bucket": "b", "path_template": "p"},
    )
    with pytest.raises(ValidationError):
        SourceDefinition(**base)  # PEC senza casella/entity_id
```

Run: `pytest tests/test_pec_multicasella.py -v -k registry or senza_casella`
Expected: FAIL (`AttributeError: casella` / nessuna ValidationError / entry mancanti)

- [ ] **Step 2: Estendere `SourceDefinition`** in `core/lineage/schemas.py`:

Nella classe, dopo la riga `societa: Literal["ORTI", "INTUR", "GROUP"]` sostituire con:

```python
    societa: Literal["ORTI", "INTUR", "GROUP", "VIGNA", "STEFANO_PERSONALE"]
```

(dimensione di lookup del registry, distinta da `core.schemas.SocietaId` che
resta intoccata). Dopo il campo `raw_storage: RawStorage` aggiungere:

```python
    # Sorgenti PEC (system == "PEC"): identità della casella. La policy di
    # visibilità sul pannello NON sta qui: vive in PANEL_ENTITIES (whitelist).
    casella: Optional[str] = None
    entity_id: Optional[
        Literal["INTUR", "ORTI", "VIGNA", "STEFANO_PERSONALE"]
    ] = None
    input_formats: list[Literal["mbox", "eml"]] = Field(
        default_factory=lambda: ["mbox"]
    )
```

E in fondo alla classe (import `model_validator` da pydantic in testa al file):

```python
    @model_validator(mode="after")
    def _pec_richiede_identita_casella(self):
        if self.system == "PEC" and (not self.casella or not self.entity_id):
            raise ValueError(
                f"{self.source_name}: sorgente PEC richiede casella ed entity_id"
            )
        return self
```

- [ ] **Step 3: Aggiornare il registry** in `core/source_registry.yaml`:

All'entry `PEC_MAILBOX_INTUR_APPEND` aggiungere (dopo `societa: INTUR`):

```yaml
    casella: in.tur@pec.it
    entity_id: INTUR
    input_formats: [mbox]
```

Dopo l'entry INTUR, aggiungere le tre nuove (stessa grammar, stessa indentazione):

```yaml
  # ── PEC orti@pec.it — export webmail mbox ─────────────────────────────────
  PEC_MAILBOX_ORTI_APPEND:
    system: PEC
    dataset: MAILBOX
    dataset_label: "PEC orti@pec.it — buste ricevute + messaggi inviati (export webmail mbox)"
    societa: ORTI
    casella: orti@pec.it
    entity_id: ORTI
    input_formats: [mbox]
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
    notes: |
      Stessa grammar di PEC_MAILBOX_INTUR_APPEND; entity dal registry (I-PEC-2).
      Spec: docs/superpowers/specs/2026-07-17-pec-multicasella-pannello-ceo-design.md

  # ── PEC vineyardamalficoast@pec.it — export webmail mbox ──────────────────
  PEC_MAILBOX_VIGNA_APPEND:
    system: PEC
    dataset: MAILBOX
    dataset_label: "PEC vineyardamalficoast@pec.it — export webmail mbox"
    societa: VIGNA
    casella: vineyardamalficoast@pec.it
    entity_id: VIGNA
    input_formats: [mbox]
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
    notes: |
      VIGNA è soggetto monitorato (EntityId), non SocietaId contabile.

  # ── PEC stefanojunior.dellapietra@mpspec.it — export .eml/.mbox ───────────
  PEC_MAILBOX_PERSONALE_APPEND:
    system: PEC
    dataset: MAILBOX
    dataset_label: "PEC personale Stefano — export webmail (.eml singoli o mbox)"
    societa: STEFANO_PERSONALE
    casella: stefanojunior.dellapietra@mpspec.it
    entity_id: STEFANO_PERSONALE
    input_formats: [eml, mbox]
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
      bucket: stefano-raw
      path_template: "pec/mailbox/PERSONALE"
    notes: |
      Perimetro personale: MAI nel pannello AMM_CEO (I-PEC-3, whitelist
      PANEL_ENTITIES). Compare solo nel digest.
```

- [ ] **Step 4: Verificare**

Run: `pytest tests/test_pec_multicasella.py tests/test_ingest_pec_mbox.py -v -k "registry or casella"`
Expected: PASS (incluso il test esistente `test_registry_pec_mailbox_intur`)

- [ ] **Step 5: Commit**

```bash
git add core/lineage/schemas.py core/source_registry.yaml tests/test_pec_multicasella.py
git commit -m "feat(pec): registry multi-casella (ORTI, VIGNA, PERSONALE) + campi casella/entity_id/input_formats"
```

---

### Task 3: Migrazione BQ — entity_id su f_pec_messages

**Files:**
- Create: `core/bq/migrations/2026_07_17_add_entity_id_f_pec_messages.py`

**Interfaces:**
- Produces: colonna `entity_id STRING` su `f_pec_messages`, backfillata da `societa_id`.

- [ ] **Step 1: Scrivere la migrazione** (pattern di `2026_05_08_add_raw_object_id_f_movimenti_contabili.py`):

```python
"""One-shot: ALTER f_pec_messages ADD entity_id STRING + backfill da societa_id.

Idempotente: probe INFORMATION_SCHEMA; il backfill tocca solo righe con
entity_id NULL. Le righe esistenti sono tutte INTUR (unica casella ingerita).
Run: python -m core.bq.migrations.2026_07_17_add_entity_id_f_pec_messages
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"
TABLE = "f_pec_messages"
COLUMN = "entity_id"


def column_exists() -> bool:
    from core.bq.client import get_client

    sql = f"""
    SELECT 1
    FROM `{PROJECT}.{DATASET}.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = '{TABLE}' AND column_name = '{COLUMN}'
    """
    return any(get_client().query(sql).result())


def run(dry_run: bool = False) -> None:
    from core.bq.client import get_client

    alter = (
        f"ALTER TABLE `{PROJECT}.{DATASET}.{TABLE}` "
        f"ADD COLUMN {COLUMN} STRING "
        f'OPTIONS(description="Soggetto giuridico (EntityId): INTUR|ORTI|VIGNA|STEFANO_PERSONALE. '
        f'Fonte: registry della sorgente (I-PEC-2)")'
    )
    backfill = (
        f"UPDATE `{PROJECT}.{DATASET}.{TABLE}` "
        f"SET {COLUMN} = societa_id WHERE {COLUMN} IS NULL AND societa_id IS NOT NULL"
    )
    if dry_run:
        log.info("[DRY RUN] %s ; %s", alter, backfill)
        return
    client = get_client()
    if column_exists():
        log.info("Colonna già presente — salto ALTER.")
    else:
        client.query(alter).result()
        log.info("ALTER ok: %s.%s", TABLE, COLUMN)
    job = client.query(backfill)
    job.result()
    log.info("Backfill ok: %s righe", job.num_dml_affected_rows)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run**

Run: `python -m core.bq.migrations.2026_07_17_add_entity_id_f_pec_messages --dry-run`
Expected: log `[DRY RUN] ALTER TABLE ... ; UPDATE ...`, exit 0

- [ ] **Step 3: Eseguire**

Run: `python -m core.bq.migrations.2026_07_17_add_entity_id_f_pec_messages`
Expected: `ALTER ok` + `Backfill ok: N righe` (N = righe INTUR esistenti).
Verifica: `bq query --use_legacy_sql=false "SELECT entity_id, COUNT(*) FROM \`hotelops-suite.hotelops.f_pec_messages\` GROUP BY 1"` → solo `INTUR`, zero NULL.
(Se `bq`/BQ chiede riautenticazione: farla fare a Stefano con `gcloud auth login` prima di questo step.)

- [ ] **Step 4: Commit**

```bash
git add core/bq/migrations/2026_07_17_add_entity_id_f_pec_messages.py
git commit -m "feat(pec): migrazione entity_id su f_pec_messages con backfill"
```

---

### Task 4: Parser generalizzato (--source, PecSource, .eml)

**Files:**
- Modify: `ingest/flussi/ingest_pec_mbox.py`
- Test: `tests/test_pec_multicasella.py` (append), `tests/test_ingest_pec_mbox.py` (adattamento firme)

**Interfaces:**
- Consumes: `SourceDefinition.casella/entity_id/input_formats` (Task 2), `EntityId` (Task 1).
- Produces:
  - `PecSource(source_name: str, casella: str, entity_id: str, bucket: str, input_formats: list[str])` — dataclass frozen.
  - `resolve_pec_source(source_name: str) -> PecSource`
  - `extract_message(msg, src: PecSource, raw_object_id: str, store, now) -> tuple[dict, list[dict]]`
  - `ingest_file(path: Path, src: PecSource, raw_object_id=None, dry_run=False) -> dict`
  - `AllegatiStore(bucket_name: str, prefix: str, dry_run=False, client=None)` — bucket ora obbligatorio.
  - CLI: `python -m ingest.flussi.ingest_pec_mbox --file X --source SOURCE_NAME [--raw-object-id Y] [--dry-run]` — `--source` SEMPRE obbligatorio.

- [ ] **Step 1: Test che falliscono** — append a `tests/test_pec_multicasella.py`:

```python
# ── Parser generalizzato ─────────────────────────────────────────────────────

from email.message import EmailMessage
from pathlib import Path


def _make_eml(path: Path, from_addr: str, to_addr: str, subject: str,
              attach: tuple[str, bytes] | None = None) -> Path:
    m = EmailMessage()
    m["From"] = from_addr
    m["To"] = to_addr
    m["Subject"] = subject
    m["Message-ID"] = f"<{abs(hash((from_addr, subject)))}@test.pec.it>"
    m["Date"] = "Wed, 15 Jul 2026 16:38:59 +0200"
    m.set_content("corpo del messaggio")
    if attach:
        nome, contenuto = attach
        m.add_attachment(
            contenuto, maintype="application", subtype="pdf", filename=nome
        )
    path.write_bytes(bytes(m))
    return path


def _src_personale():
    from ingest.flussi.ingest_pec_mbox import resolve_pec_source

    return resolve_pec_source("PEC_MAILBOX_PERSONALE_APPEND")


def test_resolve_pec_source_orti():
    from ingest.flussi.ingest_pec_mbox import resolve_pec_source

    src = resolve_pec_source("PEC_MAILBOX_ORTI_APPEND")
    assert src.casella == "orti@pec.it"
    assert src.entity_id == "ORTI"
    assert src.bucket == "orti-raw"


def test_resolve_pec_source_rifiuta_non_pec():
    from ingest.flussi.ingest_pec_mbox import resolve_pec_source

    with pytest.raises((KeyError, ValueError)):
        resolve_pec_source("ESOLVER_MOVIMENTI_ORTI_APPEND")


def test_ingest_eml_personale(tmp_path):
    from ingest.flussi.ingest_pec_mbox import ingest_file

    src = _src_personale()
    eml = _make_eml(
        tmp_path / "msg.eml",
        "stefanojunior.dellapietra@mpspec.it",
        "controparte@pec.it",
        "Test invio",
    )
    report = ingest_file(eml, src, dry_run=True)
    assert report["messaggi_letti"] == 1
    assert report["righe_messaggi"] == 1


def test_entity_dal_registry_mai_dal_contenuto(tmp_path):
    """I-PEC-2: un .eml 'della casella sbagliata' resta attribuito alla
    sorgente dichiarata, con warning — mai riattribuito a un'altra entity."""
    import mailbox as mb

    from ingest.flussi.ingest_pec_mbox import extract_message, AllegatiStore

    eml = _make_eml(
        tmp_path / "alien.eml", "orti@pec.it", "x@pec.it", "Da altra casella"
    )
    import email as email_pkg

    msg = email_pkg.message_from_bytes(eml.read_bytes())
    src = _src_personale()
    store = AllegatiStore(bucket_name=src.bucket, prefix=src.source_name, dry_run=True)
    riga, _ = extract_message(msg, src, "raw-x", store, datetime(2026, 7, 17))
    assert riga["entity_id"] == "STEFANO_PERSONALE"
    assert riga["casella"] == "stefanojunior.dellapietra@mpspec.it"
    assert "from!=casella" in (riga["parse_warning"] or "")


def test_formato_non_ammesso_rifiutato(tmp_path):
    from ingest.flussi.ingest_pec_mbox import ingest_file, resolve_pec_source

    src = resolve_pec_source("PEC_MAILBOX_ORTI_APPEND")  # solo mbox
    eml = _make_eml(tmp_path / "x.eml", "orti@pec.it", "y@pec.it", "s")
    with pytest.raises(ValueError, match="formato"):
        ingest_file(eml, src, dry_run=True)


def test_allegati_store_prefix_per_source():
    from ingest.flussi.ingest_pec_mbox import AllegatiStore

    store = AllegatiStore(bucket_name="orti-raw", prefix="PEC_MAILBOX_ORTI_APPEND", dry_run=True)
    sha, uri = store.store("doc.pdf", b"contenuto")
    assert uri.startswith("gs://orti-raw/PEC_MAILBOX_ORTI_APPEND/allegati/")
```

Run: `pytest tests/test_pec_multicasella.py -v -k "resolve or eml or entity_dal or formato or prefix"`
Expected: FAIL (`ImportError: resolve_pec_source`)

- [ ] **Step 2: Implementare in `ingest/flussi/ingest_pec_mbox.py`**

(a) Rimuovere le costanti `CASELLA`, `SOCIETA` (righe 45-46) e `SOURCE_NAME`
(riga 213). Aggiungere dopo gli import:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class PecSource:
    """Contesto della casella, risolto dal registry — mai hardcoded (I-PEC-2)."""

    source_name: str
    casella: str
    entity_id: str
    bucket: str
    input_formats: tuple[str, ...]

    @property
    def societa_id(self) -> str | None:
        return self.entity_id if self.entity_id in ("ORTI", "INTUR") else None


def resolve_pec_source(source_name: str) -> PecSource:
    from core.lineage.source_resolver import load_registry

    sd = load_registry().get(source_name)
    if sd is None:
        raise KeyError(f"sorgente non nel registry: {source_name}")
    if sd.system != "PEC":
        raise ValueError(f"{source_name} non è una sorgente PEC (system={sd.system})")
    return PecSource(
        source_name=source_name,
        casella=sd.casella.lower(),
        entity_id=sd.entity_id,
        bucket=sd.raw_storage.bucket,
        input_formats=tuple(sd.input_formats),
    )
```

(b) `AllegatiStore.__init__` diventa (bucket e prefix obbligatori):

```python
    def __init__(self, bucket_name: str, prefix: str, dry_run: bool = False, client=None):
        self.bucket_name = bucket_name
        self.prefix = prefix
        self.dry_run = dry_run
        self._client = client
        self.n_uploaded = 0
        self.n_riusati = 0
```

e in `store()` il path usa `self.prefix` al posto di `SOURCE_NAME`:

```python
        path = f"{self.prefix}/allegati/{sha[:2]}/{sha}/{_safe_object_name(nome)}"
```

(c) `extract_message(msg, src: PecSource, raw_object_id, store, now)`: nuova
firma con `src` secondo parametro. Dentro, ogni occorrenza di `CASELLA` diventa
`src.casella`; la riga finale usa:

```python
        "casella": src.casella,
        "entity_id": src.entity_id,
        "societa_id": src.societa_id,
```

(d) `_riga_fallback(msg, src: PecSource, raw_object_id, now, exc)`: stessa
sostituzione (`"casella": src.casella, "entity_id": src.entity_id,
"societa_id": src.societa_id`).

(e) Iteratore dei messaggi + guardia formato — aggiungere:

```python
def _iter_messages(path: Path):
    """mbox → N messaggi; .eml → 1 messaggio. Stesso modello canonico a valle."""
    if path.suffix.lower() == ".eml":
        import email as email_pkg

        yield email_pkg.message_from_bytes(path.read_bytes())
    else:
        yield from mailbox.mbox(str(path))
```

(f) `ingest_file(path, src: PecSource, raw_object_id=None, dry_run=False)`:
subito dopo il check su raw_object_id aggiungere:

```python
    fmt = "eml" if path.suffix.lower() == ".eml" else "mbox"
    if fmt not in src.input_formats:
        raise ValueError(
            f"formato {fmt} non ammesso per {src.source_name} "
            f"(input_formats={list(src.input_formats)})"
        )
```

poi `store = AllegatiStore(bucket_name=src.bucket, prefix=src.source_name,
dry_run=dry_run)` e il loop diventa `for msg in _iter_messages(path):` con le
chiamate aggiornate `extract_message(msg, src, ro_id, store, now)` e
`_riga_fallback(msg, src, ro_id, now, e)`.

(g) `main()`: sostituire l'argomento `--societa` con:

```python
    ap.add_argument(
        "--source",
        required=True,
        help="source_name del registry (es. PEC_MAILBOX_ORTI_APPEND) — "
        "risolve casella/entity/bucket; nessun default (I-PEC-2)",
    )
```

e prima di `ingest_file`: `src = resolve_pec_source(args.source)` poi
`ingest_file(args.file, src, raw_object_id=args.raw_object_id, dry_run=args.dry_run)`.
Aggiornare il docstring del modulo: il parser serve TUTTE le sorgenti
`system: PEC`; usage con `--source`.

- [ ] **Step 3: Adattare i test esistenti**

In `tests/test_ingest_pec_mbox.py`: individuare le chiamate con
`grep -n "extract_message(\|ingest_file(\|AllegatiStore(" tests/test_ingest_pec_mbox.py`.
In testa al file (dopo gli import) aggiungere:

```python
from ingest.flussi.ingest_pec_mbox import PecSource

SRC_INTUR = PecSource(
    source_name="PEC_MAILBOX_INTUR_APPEND",
    casella="in.tur@pec.it",
    entity_id="INTUR",
    bucket="hotelops-raw",
    input_formats=("mbox",),
)
```

e aggiornare meccanicamente: `extract_message(msg, <resto>)` →
`extract_message(msg, SRC_INTUR, <resto>)`; `ingest_file(path, <kwargs>)` →
`ingest_file(path, SRC_INTUR, <kwargs>)`; `AllegatiStore(dry_run=True)` →
`AllegatiStore(bucket_name="hotelops-raw", prefix="PEC_MAILBOX_INTUR_APPEND", dry_run=True)`.

- [ ] **Step 4: Verificare tutto il perimetro PEC**

Run: `pytest tests/test_ingest_pec_mbox.py tests/test_pec_multicasella.py -v`
Expected: PASS totale (inclusi i test annotati come rotti al Task 1 Step 5).

- [ ] **Step 5: Smoke dry-run reale su un export ORTI**

Run: `python -m ingest.flussi.ingest_pec_mbox --file "/Users/stefanodellapietra/Downloads/Email Export (1).mbox" --source PEC_MAILBOX_ORTI_APPEND --dry-run`
Expected: report con `messaggi_letti > 0`, `per_tipo` popolato, exit 0.

- [ ] **Step 6: Commit**

```bash
git add ingest/flussi/ingest_pec_mbox.py tests/test_ingest_pec_mbox.py tests/test_pec_multicasella.py
git commit -m "feat(pec): parser generalizzato multi-casella (--source dal registry, supporto .eml)"
```

---

### Task 5: Promotion passa --source alle sorgenti PEC

**Files:**
- Modify: `ingest/promotion.py` (funzione `_invoke_parser`, righe 92-96)
- Test: `tests/test_pec_multicasella.py` (append)

**Interfaces:**
- Consumes: `SourceDefinition.system` (Task 2).
- Produces: comando parser `... --file X --source <SOURCE_NAME> --raw-object-id Y` per `system == "PEC"`; comportamento invariato per tutte le altre sorgenti.

- [ ] **Step 1: Test che fallisce** — append a `tests/test_pec_multicasella.py`:

```python
def test_promotion_passa_source_alle_pec(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace

    from ingest.promotion import _invoke_parser

    catturato = {}

    def fake_run(cmd, **kw):
        catturato["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    f = tmp_path / "x.mbox"
    f.write_bytes(b"")

    sd_pec = SimpleNamespace(
        system="PEC", societa="ORTI", source_name="PEC_MAILBOX_ORTI_APPEND",
        parser_module="ingest.flussi.ingest_pec_mbox",
    )
    _invoke_parser("ingest.flussi.ingest_pec_mbox", f"file://{f}", sd_pec,
                   raw_object_id="raw-1")
    assert "--source" in catturato["cmd"]
    assert "PEC_MAILBOX_ORTI_APPEND" in catturato["cmd"]
    assert "--societa" not in catturato["cmd"]

    sd_altro = SimpleNamespace(
        system="ESOLVER", societa="ORTI", source_name="ESOLVER_X_ORTI_APPEND",
        parser_module="ingest.flussi.qualcosa",
    )
    _invoke_parser("ingest.flussi.qualcosa", f"file://{f}", sd_altro)
    assert "--societa" in catturato["cmd"]
    assert "--source" not in catturato["cmd"]
```

Run: `pytest tests/test_pec_multicasella.py -v -k promotion_passa`
Expected: FAIL (`--source` assente)

- [ ] **Step 2: Implementare** — in `_invoke_parser`, sostituire le righe:

```python
    cmd = [sys.executable, "-m", parser_module, "--file", local_path]
    if source_def.societa in ("ORTI", "INTUR"):
        cmd += ["--societa", source_def.societa]
```

con:

```python
    cmd = [sys.executable, "-m", parser_module, "--file", local_path]
    if getattr(source_def, "system", None) == "PEC":
        # Parser PEC multi-casella: contesto dal registry, mai default (I-PEC-2)
        cmd += ["--source", source_def.source_name]
    elif source_def.societa in ("ORTI", "INTUR"):
        cmd += ["--societa", source_def.societa]
```

- [ ] **Step 3: Verificare** — Run: `pytest tests/test_pec_multicasella.py -v -k promotion_passa` → PASS. Poi l'intera suite: `pytest tests/ -x -q` → nessuna regressione.

- [ ] **Step 4: Commit**

```bash
git add ingest/promotion.py tests/test_pec_multicasella.py
git commit -m "feat(pec): promotion passa --source ai parser delle sorgenti PEC"
```

---

### Task 6: Classificatore a ruleset versionato

**Files:**
- Create: `core/pec_ruleset.yaml`
- Create: `ingest/pec/__init__.py` (vuoto: `"""Layer CEO sulla PEC: classify, panel, digest."""`)
- Create: `ingest/pec/classify.py`
- Modify: `core/schemas.py` (nuova `PecClassificazioneRow`)
- Modify: `core/config.py` (`F_PEC_CLASSIFICAZIONI`)
- Test: `tests/test_pec_classify.py`

**Interfaces:**
- Produces:
  - `load_ruleset(path=None) -> Ruleset` (`Ruleset.version: str`, `.rules: list[Rule]`)
  - `classify_message(mittente: str|None, subject: str|None, nomi_allegati: list[str], ruleset: Ruleset) -> dict` con chiavi `stato, primary_category, importance, document_type, matches` (matches = lista id regola).
  - `run_classify(dry_run: bool = False) -> dict` (report) — classifica su BQ i messaggi senza classificazione alla versione corrente.
  - Tabella `F_PEC_CLASSIFICAZIONI = _t("f_pec_classificazioni")`.
  - `PecClassificazioneRow` con campi: `msgid, entity_id, stato, primary_category, importance, document_type, matches (str JSON), ruleset_version, classified_at, override_source, override_note, hash_riga, data_caricamento`.
- Stati: `CLASSIFICATO | NON_CLASSIFICATO | AMBIGUO | ERRORE_CLASSIFICAZIONE`.

- [ ] **Step 1: `core/pec_ruleset.yaml`** (v1 completo — priorità: più alto vince):

```yaml
# Ruleset di classificazione PEC — configurazione versionata (I-PEC-8).
# Ogni modifica alle regole DEVE incrementare version (semver): la
# riclassificazione scrive righe nuove, mai sovrascritture.
version: "1.0.0"

rules:
  - id: legale-mittente
    priority: 100
    match: {mittente_domain: [legalmail.it, pec.giustizia.it]}
    assign: {category: LEGALE, importance: ALTA, document_type: ALTRO}
  - id: legale-oggetto
    priority: 100
    match: {subject_regex: '(?i)\b(diffid|atto giudiziari|decreto ingiuntiv|precett|pignorament|citazion|ricors)'}
    assign: {category: LEGALE, importance: ALTA, document_type: ATTO_GIUDIZIARIO}
  - id: fisco
    priority: 90
    match: {mittente_domain: [pec.agenziaentrate.gov.it, pec.agenziaentrateriscossione.gov.it]}
    assign: {category: FISCO, importance: ALTA, document_type: ALTRO}
  - id: registro-imprese
    priority: 80
    match: {mittente_domain: [certpec.camcom.it, cert.infocamere.it]}
    assign: {category: REGISTRO_IMPRESE, importance: ALTA, document_type: ALTRO}
  - id: banca
    priority: 70
    match: {mittente_domain: [pec.gruppobper.it, pec.intesasanpaolo.com, postacert.gruppo.mps.it, pec.bancaditalia.it]}
    assign: {category: BANCA, importance: NORMALE, document_type: ALTRO}
  - id: assicurazione
    priority: 60
    match: {mittente_domain: [pec.agenzie.generali.com, pec.intesasanpaoloassicura.com]}
    assign: {category: ASSICURAZIONE, importance: NORMALE, document_type: ALTRO}
  # ── document_type da nome allegato/oggetto (non decidono la category) ──
  - id: doc-bilancio
    priority: 10
    match: {allegato_regex: '(?i)bilanci'}
    assign: {document_type: BILANCIO, importance: ALTA}
  - id: doc-verbale
    priority: 10
    match: {allegato_regex: '(?i)verbale'}
    assign: {document_type: VERBALE, importance: ALTA}
  - id: doc-contratto
    priority: 10
    match: {allegato_regex: '(?i)contratt'}
    assign: {document_type: CONTRATTO, importance: ALTA}
  - id: doc-fattura
    priority: 10
    match: {allegato_regex: '(?i)fattur|\bft\s?\d'}
    assign: {document_type: FATTURA, importance: NORMALE}
```

- [ ] **Step 2: Test che falliscono** — creare `tests/test_pec_classify.py`:

```python
"""Classificatore PEC: multi-match, priorità, AMBIGUO, versioning."""

from __future__ import annotations

import pytest

from ingest.pec.classify import Rule, Ruleset, classify_message, load_ruleset


def _rs(rules) -> Ruleset:
    return Ruleset(version="9.9.9", rules=rules)


def test_load_ruleset_reale():
    rs = load_ruleset()
    assert rs.version == "1.0.0"
    assert any(r.id == "legale-oggetto" for r in rs.rules)


def test_match_singolo_banca():
    out = classify_message("filiale@pec.gruppobper.it", "Estratto conto", [], load_ruleset())
    assert out["stato"] == "CLASSIFICATO"
    assert out["primary_category"] == "BANCA"
    assert out["importance"] == "NORMALE"
    assert "banca" in out["matches"]


def test_multi_match_vince_priorita():
    # banca + oggetto legale → LEGALE (priority 100 > 70), entrambi in matches
    out = classify_message(
        "filiale@pec.gruppobper.it", "Diffida ad adempiere", [], load_ruleset()
    )
    assert out["primary_category"] == "LEGALE"
    assert out["importance"] == "ALTA"
    assert set(out["matches"]) >= {"banca", "legale-oggetto"}


def test_pari_priorita_categorie_diverse_ambiguo():
    rs = _rs([
        Rule(id="a", priority=50, match={"subject_regex": "x"},
             assign={"category": "BANCA"}),
        Rule(id="b", priority=50, match={"subject_regex": "x"},
             assign={"category": "FISCO"}),
    ])
    out = classify_message("chiunque@pec.it", "x", [], rs)
    assert out["stato"] == "AMBIGUO"
    assert set(out["matches"]) == {"a", "b"}


def test_nessun_match_non_classificato():
    out = classify_message("ignoto@pec.qualcosa.it", "Ciao", [], load_ruleset())
    assert out["stato"] == "NON_CLASSIFICATO"
    assert out["primary_category"] is None
    assert out["importance"] == "DA_RIVEDERE"


def test_document_type_da_allegato_non_decide_categoria():
    out = classify_message(
        "filiale@pec.gruppobper.it", "Invio", ["BILANCIO 2025.pdf"], load_ruleset()
    )
    assert out["primary_category"] == "BANCA"
    assert out["document_type"] == "BILANCIO"
    assert out["importance"] == "ALTA"  # doc-bilancio alza l'importanza


def test_regex_rotta_errore_classificazione():
    rs = _rs([Rule(id="rotta", priority=1, match={"subject_regex": "("},
                   assign={"category": "BANCA"})])
    out = classify_message("x@pec.it", "s", [], rs)
    assert out["stato"] == "ERRORE_CLASSIFICAZIONE"


def test_riga_classificazione_valida():
    from datetime import datetime

    from core.schemas import PecClassificazioneRow, validate_batch

    row = {
        "msgid": "m1", "entity_id": "ORTI", "stato": "CLASSIFICATO",
        "primary_category": "BANCA", "importance": "NORMALE",
        "document_type": "ALTRO", "matches": '["banca"]',
        "ruleset_version": "1.0.0", "classified_at": datetime(2026, 7, 17),
        "override_source": None, "override_note": None,
        "hash_riga": "h", "data_caricamento": datetime(2026, 7, 17),
    }
    validate_batch([row], PecClassificazioneRow, context="test")
```

Run: `pytest tests/test_pec_classify.py -v` → FAIL (`ModuleNotFoundError: ingest.pec`)

- [ ] **Step 3: Schema riga** — in `core/schemas.py`, dopo `PecAllegatoRow`:

```python
class PecClassificazioneRow(BaseModel):
    """Schema for f_pec_classificazioni — una classificazione per messaggio+versione.

    APPEND-only: riclassificare = riga nuova con ruleset_version più recente;
    l'override umano è una riga con override_source=HUMAN. La "corrente" è
    responsabilità della vista v_pec_classificazione_corrente (I-PEC-8).
    Dedup su hash_riga = md5(msgid|ruleset_version|override_source).
    """

    msgid: str
    entity_id: EntityId
    stato: Literal["CLASSIFICATO", "NON_CLASSIFICATO", "AMBIGUO", "ERRORE_CLASSIFICAZIONE"]
    primary_category: Optional[
        Literal["BANCA", "LEGALE", "FISCO", "REGISTRO_IMPRESE",
                "ASSICURAZIONE", "PA", "FORNITORE", "ALTRO"]
    ] = None
    importance: Literal["ALTA", "NORMALE", "DA_RIVEDERE"]
    document_type: Optional[
        Literal["CONTRATTO", "VERBALE", "BILANCIO", "DIFFIDA", "FATTURA",
                "ATTO_GIUDIZIARIO", "RICEVUTA_PEC", "ALTRO"]
    ] = None
    matches: str  # JSON array di id regola
    ruleset_version: str
    classified_at: datetime
    override_source: Optional[Literal["HUMAN"]] = None
    override_note: Optional[str] = None
    hash_riga: str
    data_caricamento: datetime

    @field_validator("msgid", "ruleset_version", "hash_riga")
    @classmethod
    def pec_class_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("campo vuoto")
        return v
```

In `core/config.py`, dopo `F_PEC_ALLEGATI`:

```python
F_PEC_CLASSIFICAZIONI       = _t("f_pec_classificazioni")
```

- [ ] **Step 4: `ingest/pec/classify.py`** (completo):

```python
"""Classificatore PEC a ruleset versionato → f_pec_classificazioni.

Tre dimensioni separate (category / importance / document_type), tutti i match
conservati, primary per priorità esplicita. Stati: CLASSIFICATO,
NON_CLASSIFICATO, AMBIGUO, ERRORE_CLASSIFICAZIONE. Spec 2026-07-17, I-PEC-8.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from core.config import F_PEC_CLASSIFICAZIONI, F_PEC_MESSAGES, F_PEC_ALLEGATI
from core.schemas import PecClassificazioneRow, make_hash, validate_batch

log = logging.getLogger("ingest.pec.classify")

RULESET_PATH = Path(__file__).resolve().parents[2] / "core" / "pec_ruleset.yaml"


@dataclass(frozen=True)
class Rule:
    id: str
    priority: int
    match: dict
    assign: dict


@dataclass(frozen=True)
class Ruleset:
    version: str
    rules: list[Rule] = field(default_factory=list)


def load_ruleset(path: Path | None = None) -> Ruleset:
    data = yaml.safe_load((path or RULESET_PATH).read_text())
    rules = [Rule(**r) for r in data["rules"]]
    if len({r.id for r in rules}) != len(rules):
        raise ValueError("id regola duplicati nel ruleset")
    return Ruleset(version=str(data["version"]), rules=rules)


def _rule_matches(rule: Rule, mittente: str, subject: str, nomi: list[str]) -> bool:
    m = rule.match
    if "mittente_domain" in m:
        dominio = mittente.rsplit("@", 1)[-1].lower() if "@" in mittente else ""
        if dominio not in [d.lower() for d in m["mittente_domain"]]:
            return False
    if "subject_regex" in m and not re.search(m["subject_regex"], subject or ""):
        return False
    if "allegato_regex" in m and not any(
        re.search(m["allegato_regex"], n or "") for n in nomi
    ):
        return False
    return True


_IMPORTANCE_ORD = {"DA_RIVEDERE": 0, "NORMALE": 1, "ALTA": 2}


def classify_message(
    mittente: str | None, subject: str | None, nomi_allegati: list[str],
    ruleset: Ruleset,
) -> dict:
    out = {
        "stato": "NON_CLASSIFICATO", "primary_category": None,
        "importance": "DA_RIVEDERE", "document_type": None, "matches": [],
    }
    try:
        matched = [
            r for r in ruleset.rules
            if _rule_matches(r, mittente or "", subject or "", nomi_allegati)
        ]
    except re.error as e:
        log.warning("regex rotta nel ruleset: %s", e)
        return {**out, "stato": "ERRORE_CLASSIFICAZIONE"}

    if not matched:
        return out
    out["matches"] = [r.id for r in matched]

    # category: vince la priorità più alta; pari priorità con categorie
    # diverse al vertice → AMBIGUO (si conservano comunque tutti i match).
    con_cat = sorted(
        (r for r in matched if r.assign.get("category")),
        key=lambda r: -r.priority,
    )
    if con_cat:
        top = [r for r in con_cat if r.priority == con_cat[0].priority]
        categorie_top = {r.assign["category"] for r in top}
        if len(categorie_top) > 1:
            return {**out, "stato": "AMBIGUO"}
        out["primary_category"] = con_cat[0].assign["category"]
        out["stato"] = "CLASSIFICATO"

    # importance: la massima tra tutti i match (default NORMALE se classificato)
    livelli = [r.assign["importance"] for r in matched if r.assign.get("importance")]
    if livelli:
        out["importance"] = max(livelli, key=_IMPORTANCE_ORD.__getitem__)
    elif out["stato"] == "CLASSIFICATO":
        out["importance"] = "NORMALE"

    # document_type: il match più prioritario che lo assegna
    con_tipo = sorted(
        (r for r in matched if r.assign.get("document_type")),
        key=lambda r: -r.priority,
    )
    if con_tipo:
        out["document_type"] = con_tipo[0].assign["document_type"]

    if out["stato"] == "NON_CLASSIFICATO" and out["matches"]:
        # match solo di document_type: comunque materiale classificato
        out["stato"] = "CLASSIFICATO"
    return out


def run_classify(dry_run: bool = False) -> dict:
    """Classifica su BQ i messaggi privi di riga alla versione corrente."""
    from core.bq.client import get_client

    rs = load_ruleset()
    client = get_client()
    sql = f"""
    SELECT m.msgid, m.entity_id, m.mittente, m.subject,
           ARRAY_AGG(a.nome_file IGNORE NULLS) AS nomi
    FROM `{F_PEC_MESSAGES}` m
    LEFT JOIN `{F_PEC_ALLEGATI}` a USING (msgid)
    LEFT JOIN `{F_PEC_CLASSIFICAZIONI}` c
      ON c.msgid = m.msgid AND c.ruleset_version = @v
    WHERE c.msgid IS NULL AND m.entity_id IS NOT NULL
    GROUP BY 1, 2, 3, 4
    """
    from google.cloud import bigquery

    job = client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("v", "STRING", rs.version)]
    ))
    now = datetime.now()
    rows, per_stato = [], {}
    for r in job.result():
        esito = classify_message(r.mittente, r.subject, list(r.nomi or []), rs)
        per_stato[esito["stato"]] = per_stato.get(esito["stato"], 0) + 1
        rows.append({
            "msgid": r.msgid, "entity_id": r.entity_id, "stato": esito["stato"],
            "primary_category": esito["primary_category"],
            "importance": esito["importance"],
            "document_type": esito["document_type"],
            "matches": json.dumps(esito["matches"]),
            "ruleset_version": rs.version, "classified_at": now,
            "override_source": None, "override_note": None,
            "hash_riga": make_hash(r.msgid, rs.version, ""),
            "data_caricamento": now,
        })
    validate_batch(rows, PecClassificazioneRow, context="f_pec_classificazioni")
    if not dry_run and rows:
        from core.bq.write import bq_write_validated

        bq_write_validated(
            F_PEC_CLASSIFICAZIONI,
            [PecClassificazioneRow(**r) for r in rows], mode="append",
        )
    report = {"ruleset_version": rs.version, "classificati": len(rows),
              "per_stato": per_stato, "dry_run": dry_run}
    log.info("classify: %s", report)
    return report
```

- [ ] **Step 5: Verificare** — Run: `pytest tests/test_pec_classify.py -v` → PASS (8 test).

- [ ] **Step 6: Vista "corrente"** — creare il file SQL seguendo la convenzione dei file già presenti in `core/bq/views/` (guardare un file esistente per header/formatting e replicarlo). Contenuto della vista `v_pec_classificazione_corrente`:

```sql
-- Ultima classificazione per msgid: override umano > ruleset più recente.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_pec_classificazione_corrente` AS
SELECT * EXCEPT (rn) FROM (
  SELECT c.*,
         ROW_NUMBER() OVER (
           PARTITION BY msgid
           ORDER BY (override_source = 'HUMAN') DESC, classified_at DESC
         ) AS rn
  FROM `hotelops-suite.hotelops.f_pec_classificazioni` c
)
WHERE rn = 1
```

Deploy con il comando del repo: `python cli.py deploy-views` (o l'equivalente
esposto da `hotelops deploy-views` — verificare `python cli.py help`).

- [ ] **Step 7: Commit**

```bash
git add core/pec_ruleset.yaml ingest/pec/ core/schemas.py core/config.py core/bq/views/ tests/test_pec_classify.py
git commit -m "feat(pec): classificatore a ruleset versionato + f_pec_classificazioni + vista corrente"
```

---

### Task 7: Projection pannello CEO (sync-panel)

**Files:**
- Create: `ingest/pec/panel.py`
- Modify: `core/schemas.py` (`PecPanelProjectionRow`), `core/config.py` (`F_PEC_PANEL_PROJECTIONS`, `PANEL_ENTITIES`, `PANEL_ROOT`, `PANEL_CATEGORY_FOLDERS`, `PANEL_MAX_ATTACHMENT_BYTES`)
- Test: `tests/test_pec_panel.py`

**Interfaces:**
- Consumes: `v_pec_classificazione_corrente` (Task 6), `f_pec_allegati` (esistente).
- Produces:
  - `sync_panel(dry_run: bool = False, verify: bool = False) -> dict` (report)
  - `_sanitize_filename(nome: str) -> str`, `_destination_path(entity, category, data_evento, nome) -> Path` (relativa al root), `projection_key(msgid, sha256, dest_rel: str) -> str`
  - Tabella `F_PEC_PANEL_PROJECTIONS = _t("f_pec_panel_projections")`.

- [ ] **Step 1: Config** — in `core/config.py` aggiungere in fondo:

```python
# ── Pannello CEO (projection PEC su Drive) — spec 2026-07-17 ─────────────────
F_PEC_PANEL_PROJECTIONS     = _t("f_pec_panel_projections")
F_PEC_DIGEST_RUNS           = _t("f_pec_digest_runs")

# Whitelist POSITIVA delle entity ammesse nel pannello (I-PEC-3): una entity
# nuova NON entra finché non viene aggiunta qui deliberatamente.
PANEL_ENTITIES = ["INTUR", "ORTI", "VIGNA"]

# Root della projection: mirror locale Drive di 01_societario/AMM_CEO.
# Override nei test/ambienti: env HOTELOPS_PANEL_ROOT.
import os

PANEL_ROOT = os.environ.get(
    "HOTELOPS_PANEL_ROOT",
    "/Users/stefanodellapietra/My Drive (stefano@panoramagroup.it)/01_societario/AMM_CEO",
)

# Cartelle leggibili per categoria (decisione spec: nomi umani, enum nel dato)
PANEL_CATEGORY_FOLDERS = {
    "BANCA": "Banca", "LEGALE": "Legale", "FISCO": "Fisco",
    "REGISTRO_IMPRESE": "Registro Imprese", "ASSICURAZIONE": "Assicurazione",
    "PA": "PA", "FORNITORE": "Fornitori", "ALTRO": "Altro",
}

PANEL_MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024
```

- [ ] **Step 2: Schema riga** — in `core/schemas.py` dopo `PecClassificazioneRow`:

```python
class PecPanelProjectionRow(BaseModel):
    """Schema for f_pec_panel_projections — stato CANONICO della projection.

    Il pannello Drive è solo una copia consultabile (spec 2026-07-17): la
    verità su cosa è stato proiettato sta in questa tabella. projection_key =
    md5(msgid|sha256|destination_path): lo stesso PDF in due PEC diverse è due
    proiezioni legittime. APPEND; mai delete (I-PEC-4, I-PEC-5).
    """

    projection_key: str
    msgid: str
    sha256: str
    entity_id: EntityId
    gcs_uri: str
    destination_path: str  # relativo a PANEL_ROOT
    run_id: str
    projected_at: datetime
    status: Literal["COPIED", "SKIPPED_EXISTS", "FAILED"]

    @field_validator("projection_key", "msgid", "sha256", "destination_path")
    @classmethod
    def pec_proj_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("campo vuoto")
        return v
```

- [ ] **Step 3: Test che falliscono** — creare `tests/test_pec_panel.py`:

```python
"""Projection pannello CEO: sanitizzazione, whitelist, idempotenza, traversal."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.pec.panel import (
    _destination_path,
    _sanitize_filename,
    projection_key,
)


def test_sanitize_basename_e_traversal():
    assert _sanitize_filename("../../evil.pdf") == "evil.pdf"
    assert _sanitize_filename("..\\..\\evil.pdf") == "evil.pdf"
    assert _sanitize_filename("a/b/c.pdf") == "c.pdf"
    assert ".." not in _sanitize_filename("do..c.pdf../..")
    assert _sanitize_filename("  ") == "allegato"


def test_sanitize_control_chars_e_lunghezza():
    assert "\n" not in _sanitize_filename("a\nb.pdf")
    lungo = "x" * 400 + ".pdf"
    out = _sanitize_filename(lungo)
    assert len(out) <= 180 and out.endswith(".pdf")


def test_destination_dentro_root():
    from datetime import datetime

    rel = _destination_path("ORTI", "LEGALE", datetime(2026, 7, 3), "diffida.pdf")
    assert rel == Path("ORTI/PEC/Legale/2026-07 - diffida.pdf")


def test_destination_entity_fuori_whitelist_rifiutata():
    from datetime import datetime

    with pytest.raises(ValueError, match="whitelist"):
        _destination_path("STEFANO_PERSONALE", "LEGALE", datetime(2026, 7, 3), "x.pdf")


def test_destination_traversal_nel_nome_resta_sotto_root():
    from datetime import datetime

    rel = _destination_path("ORTI", "BANCA", datetime(2026, 1, 1), "../../../etc/passwd")
    assert not str(rel).startswith("..")
    assert rel.parts[0] == "ORTI"


def test_projection_key_deterministica_e_sensibile():
    k1 = projection_key("m1", "sha", "ORTI/PEC/Banca/x.pdf")
    assert k1 == projection_key("m1", "sha", "ORTI/PEC/Banca/x.pdf")
    assert k1 != projection_key("m2", "sha", "ORTI/PEC/Banca/x.pdf")
    assert k1 != projection_key("m1", "sha", "ORTI/PEC/Banca/y.pdf")


def test_riga_projection_valida():
    from datetime import datetime

    from core.schemas import PecPanelProjectionRow, validate_batch

    validate_batch([{
        "projection_key": "k", "msgid": "m", "sha256": "s", "entity_id": "ORTI",
        "gcs_uri": "gs://orti-raw/x", "destination_path": "ORTI/PEC/Banca/x.pdf",
        "run_id": "r", "projected_at": datetime(2026, 7, 17), "status": "COPIED",
    }], PecPanelProjectionRow, context="test")


def test_riga_projection_personale_rifiutata():
    """I-PEC-3 anche a livello schema/whitelist: il runner non deve mai
    costruire path per STEFANO_PERSONALE (il test di _destination_path sopra);
    qui si verifica che la whitelist sia quella di config, non un'esclusione."""
    from core.config import PANEL_ENTITIES

    assert PANEL_ENTITIES == ["INTUR", "ORTI", "VIGNA"]
    assert "STEFANO_PERSONALE" not in PANEL_ENTITIES
```

Run: `pytest tests/test_pec_panel.py -v` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 4: Implementare `ingest/pec/panel.py`**:

```python
"""sync-panel: projection degli allegati importanti su AMM_CEO (Drive mirror).

GCS/BQ canonici; il pannello è una copia consultabile. Stato autoritativo:
f_pec_panel_projections. Whitelist positiva PANEL_ENTITIES (I-PEC-3). Solo
aggiunte, mai delete/overwrite (I-PEC-4/5/6). Spec 2026-07-17.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from core.config import (
    F_PEC_ALLEGATI,
    F_PEC_MESSAGES,
    F_PEC_PANEL_PROJECTIONS,
    PANEL_CATEGORY_FOLDERS,
    PANEL_ENTITIES,
    PANEL_MAX_ATTACHMENT_BYTES,
    PANEL_ROOT,
    PROJECT,
)
from core.schemas import PecPanelProjectionRow, validate_batch

log = logging.getLogger("ingest.pec.panel")

_SAFE_CHARS = re.compile(r"[^\w\s\.\-\(\)àèéìòùÀÈÉÌÒÙ']", re.UNICODE)


def _sanitize_filename(nome: str, max_len: int = 180) -> str:
    """Solo basename, niente traversal/control char, charset sicuro, cap."""
    nome = (nome or "").replace("\\", "/").rsplit("/", 1)[-1]
    nome = _SAFE_CHARS.sub("_", nome)
    nome = re.sub(r"\.\.+", ".", nome).strip(" .") or "allegato"
    if len(nome) > max_len:
        stem, dot, ext = nome.rpartition(".")
        if dot and len(ext) <= 10:
            nome = stem[: max_len - len(ext) - 1] + "." + ext
        else:
            nome = nome[:max_len]
    return nome


def _destination_path(
    entity_id: str, category: str | None, data_evento: datetime, nome_file: str
) -> Path:
    """Path RELATIVO al root: <ENTITY>/PEC/<Categoria>/<AAAA-MM> - <nome>."""
    if entity_id not in PANEL_ENTITIES:
        raise ValueError(f"entity {entity_id} non in whitelist PANEL_ENTITIES")
    cartella = PANEL_CATEGORY_FOLDERS.get(category or "ALTRO", "Altro")
    nome = _sanitize_filename(nome_file)
    return Path(entity_id) / "PEC" / cartella / f"{data_evento:%Y-%m} - {nome}"


def projection_key(msgid: str, sha256: str, dest_rel: str) -> str:
    return hashlib.md5(f"{msgid}|{sha256}|{dest_rel}".encode()).hexdigest()


def _assert_under_root(dest_abs: Path, root: Path) -> None:
    if root.resolve() not in dest_abs.resolve().parents:
        raise ValueError(f"path fuori dal root pannello: {dest_abs}")


def _candidati(client) -> list:
    """Allegati con importance=ALTA di entity in whitelist, non ancora proiettati."""
    from google.cloud import bigquery

    entities = ", ".join(f"'{e}'" for e in PANEL_ENTITIES)
    sql = f"""
    SELECT a.msgid, a.sha256, a.nome_file, a.gcs_uri, a.size_bytes,
           m.entity_id, m.data_evento, c.primary_category
    FROM `{F_PEC_ALLEGATI}` a
    JOIN `{F_PEC_MESSAGES}` m USING (msgid)
    JOIN `{PROJECT}.hotelops.v_pec_classificazione_corrente` c USING (msgid)
    WHERE m.entity_id IN ({entities})
      AND c.importance = 'ALTA'
      AND a.gcs_uri IS NOT NULL
    """
    return list(client.query(sql).result())


def _gia_proiettate(client) -> set[str]:
    sql = f"SELECT projection_key FROM `{F_PEC_PANEL_PROJECTIONS}`"
    try:
        return {r.projection_key for r in client.query(sql).result()}
    except Exception:  # tabella non ancora creata: primo run
        return set()


def sync_panel(dry_run: bool = False, verify: bool = False) -> dict:
    from core.bq.client import get_client

    client = get_client()
    root = Path(PANEL_ROOT)
    run_id = f"panel-{uuid.uuid4().hex[:12]}"
    now = datetime.now()
    report = {"run_id": run_id, "copiati": 0, "skippati": 0, "falliti": 0,
              "oversize": 0, "dry_run": dry_run, "anomalie_verify": []}

    if not root.exists():
        raise FileNotFoundError(
            f"root pannello non trovato (Drive spento?): {root}"
        )

    esistenti = _gia_proiettate(client)
    rows: list[dict] = []

    for cand in _candidati(client):
        dest_rel = _destination_path(
            cand.entity_id, cand.primary_category, cand.data_evento, cand.nome_file
        )
        key = projection_key(cand.msgid, cand.sha256, str(dest_rel))
        if key in esistenti:
            continue
        if cand.size_bytes and cand.size_bytes > PANEL_MAX_ATTACHMENT_BYTES:
            report["oversize"] += 1
            continue  # segnalato dal digest (allegati non sincronizzati)
        dest_abs = root / dest_rel
        _assert_under_root(dest_abs, root)
        if dest_abs.exists():
            status = "SKIPPED_EXISTS"
            report["skippati"] += 1
        elif dry_run:
            status = "COPIED"
            report["copiati"] += 1
        else:
            try:
                dest_abs.parent.mkdir(parents=True, exist_ok=True)
                _download_gcs(cand.gcs_uri, dest_abs)
                status = "COPIED"
                report["copiati"] += 1
            except Exception as e:
                log.warning("copia fallita %s: %s", cand.gcs_uri, e)
                status = "FAILED"
                report["falliti"] += 1
        rows.append({
            "projection_key": key, "msgid": cand.msgid, "sha256": cand.sha256,
            "entity_id": cand.entity_id, "gcs_uri": cand.gcs_uri,
            "destination_path": str(dest_rel), "run_id": run_id,
            "projected_at": now, "status": status,
        })

    validate_batch(rows, PecPanelProjectionRow, context="f_pec_panel_projections")
    if rows and not dry_run:
        from core.bq.write import bq_write_validated

        bq_write_validated(
            F_PEC_PANEL_PROJECTIONS,
            [PecPanelProjectionRow(**r) for r in rows], mode="append",
        )

    if verify:
        report["anomalie_verify"] = _verify(client, root)

    _scrivi_indice(root, client, dry_run)
    log.info("sync-panel: %s", report)
    return report


def _download_gcs(gcs_uri: str, dest: Path) -> None:
    from google.cloud import storage

    bucket_name, _, blob_path = gcs_uri.removeprefix("gs://").partition("/")
    storage.Client(project=PROJECT).bucket(bucket_name).blob(
        blob_path
    ).download_to_filename(str(dest))


def _verify(client, root: Path) -> list[str]:
    """Riconciliazione nei due sensi: riferisce, MAI cancella."""
    anomalie = []
    sql = (
        f"SELECT destination_path FROM `{F_PEC_PANEL_PROJECTIONS}` "
        f"WHERE status = 'COPIED'"
    )
    attesi = {r.destination_path for r in client.query(sql).result()}
    for rel in attesi:
        if not (root / rel).exists():
            anomalie.append(f"riga COPIED senza file: {rel}")
    su_disco = {
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and p.parts[len(root.parts)] in PANEL_ENTITIES
        and "PEC" in p.parts
    }
    for rel in sorted(su_disco - attesi):
        anomalie.append(f"file senza riga projection: {rel}")
    return anomalie


def _scrivi_indice(root: Path, client, dry_run: bool) -> None:
    """Copia leggibile e rigenerabile dell'indice — informativa, non autorevole."""
    if dry_run:
        return
    try:
        sql = (
            f"SELECT entity_id, destination_path, projected_at "
            f"FROM `{F_PEC_PANEL_PROJECTIONS}` WHERE status='COPIED' "
            f"ORDER BY projected_at DESC LIMIT 500"
        )
        righe = list(client.query(sql).result())
        testo = ["# Indice documenti proiettati (rigenerato, non autorevole)", ""]
        testo += [f"- `{r.destination_path}` ({r.projected_at:%Y-%m-%d})" for r in righe]
        (root / "_indice.md").write_text("\n".join(testo) + "\n")
    except Exception as e:  # l'indice non deve mai far fallire il run
        log.warning("indice non aggiornato: %s", e)
```

- [ ] **Step 5: Verificare** — Run: `pytest tests/test_pec_panel.py -v` → PASS (8 test).

- [ ] **Step 6: Commit**

```bash
git add ingest/pec/panel.py core/schemas.py core/config.py tests/test_pec_panel.py
git commit -m "feat(pec): sync-panel — projection su AMM_CEO con stato canonico in BQ e whitelist entity"
```

---

### Task 8: Digest con checkpoint

**Files:**
- Create: `ingest/pec/digest.py`
- Modify: `core/schemas.py` (`PecDigestRunRow`)
- Test: `tests/test_pec_digest.py`

**Interfaces:**
- Consumes: tabelle dei task 6-7; `F_PEC_DIGEST_RUNS` (config già aggiunta al Task 7).
- Produces: `run_digest(da=None, a=None, casella=None, entity=None, solo_anomalie=False, fmt="markdown", dry_run=False) -> str` (il report reso); checkpoint su `f_pec_digest_runs`; file `PANEL_ROOT/_digest/AAAA/MM/AAAA-MM-GG.md` + `latest.md`.

- [ ] **Step 1: Schema riga** — in `core/schemas.py` dopo `PecPanelProjectionRow`:

```python
class PecDigestRunRow(BaseModel):
    """Schema for f_pec_digest_runs — checkpoint tecnico del digest.

    Il markdown su Drive è output umano; lo stato applicativo è QUI (spec
    2026-07-17). Il default --da del run successivo è il to_ts dell'ultimo
    run SUCCESS. Un solo run RUNNING alla volta.
    """

    run_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    status: Literal["RUNNING", "SUCCESS", "FAILED"]
    from_ts: datetime
    to_ts: datetime
    params: Optional[str] = None  # JSON dei filtri richiesti
```

- [ ] **Step 2: Test** — creare `tests/test_pec_digest.py`:

```python
"""Digest PEC: finestra, formato, sezioni, checkpoint."""

from __future__ import annotations

from datetime import datetime

from ingest.pec.digest import _render_markdown, _percorso_file


def _dati_finti() -> dict:
    return {
        "finestra": (datetime(2026, 7, 10), datetime(2026, 7, 17)),
        "importanti": [
            {"entity_id": "ORTI", "subject": "Diffida", "mittente": "avv@legalmail.it",
             "primary_category": "LEGALE", "proiettato": True},
        ],
        "anomalie_ricevute": [
            {"entity_id": "INTUR", "subject": "x", "tipo": "ANOMALIA"},
        ],
        "errori_parsing": [], "non_sincronizzati": [],
        "ambigui": [], "non_classificati": [
            {"entity_id": "STEFANO_PERSONALE", "subject": "Ciao", "mittente": "a@b.it"},
        ],
        "risolti": [], "totali_per_casella": {"orti@pec.it": 12},
    }


def test_render_markdown_sezioni_in_ordine():
    md = _render_markdown(_dati_finti(), solo_anomalie=False)
    i_imp = md.index("## Messaggi importanti")
    i_ano = md.index("## Ricevute anomale")
    i_ncl = md.index("## Da rivedere")
    assert i_imp < i_ano < i_ncl
    assert "Diffida" in md and "STEFANO_PERSONALE" in md


def test_solo_anomalie_esclude_importanti():
    md = _render_markdown(_dati_finti(), solo_anomalie=True)
    assert "## Messaggi importanti" not in md
    assert "## Ricevute anomale" in md


def test_percorso_file_per_data():
    p = _percorso_file(datetime(2026, 7, 17))
    assert str(p).endswith("_digest/2026/07/2026-07-17.md")


def test_digest_run_row_valida():
    from core.schemas import PecDigestRunRow, validate_batch

    validate_batch([{
        "run_id": "d-1", "started_at": datetime(2026, 7, 17, 8, 0),
        "finished_at": None, "status": "RUNNING",
        "from_ts": datetime(2026, 7, 10), "to_ts": datetime(2026, 7, 17),
        "params": "{}",
    }], PecDigestRunRow, context="test")
```

Run: `pytest tests/test_pec_digest.py -v` → FAIL

- [ ] **Step 3: Implementare `ingest/pec/digest.py`**:

```python
"""Digest CEO: cosa è successo sulle 4 caselle, azionabile prima del rumore.

Checkpoint tecnico su f_pec_digest_runs (default finestra: dall'ultimo
SUCCESS). Il markdown su AMM_CEO/_digest/ è output umano. Spec 2026-07-17.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from core.config import (
    F_PEC_ALLEGATI,
    F_PEC_DIGEST_RUNS,
    F_PEC_MESSAGES,
    F_PEC_PANEL_PROJECTIONS,
    PANEL_ROOT,
    PROJECT,
)
from core.schemas import PecDigestRunRow, validate_batch

log = logging.getLogger("ingest.pec.digest")

EPOCA_CORPUS = datetime(2018, 1, 1)
_V_CORRENTE = f"{PROJECT}.hotelops.v_pec_classificazione_corrente"


def _percorso_file(giorno: datetime) -> Path:
    return (
        Path(PANEL_ROOT) / "_digest" / f"{giorno:%Y}" / f"{giorno:%m}"
        / f"{giorno:%Y-%m-%d}.md"
    )


def _ultimo_success(client) -> datetime | None:
    sql = (
        f"SELECT MAX(to_ts) AS t FROM `{F_PEC_DIGEST_RUNS}` "
        f"WHERE status = 'SUCCESS'"
    )
    try:
        rows = list(client.query(sql).result())
        return rows[0].t if rows and rows[0].t else None
    except Exception:
        return None  # tabella assente: primo run


def _run_aperto(client) -> bool:
    sql = f"SELECT 1 FROM `{F_PEC_DIGEST_RUNS}` WHERE status = 'RUNNING' LIMIT 1"
    try:
        return any(client.query(sql).result())
    except Exception:
        return False


def _q(client, sql: str, **params):
    from google.cloud import bigquery

    qp = [
        bigquery.ScalarQueryParameter(
            k, "DATETIME" if isinstance(v, datetime) else "STRING", v
        )
        for k, v in params.items()
    ]
    return [dict(r) for r in client.query(
        sql, job_config=bigquery.QueryJobConfig(query_parameters=qp)
    ).result()]


def _raccogli(client, da: datetime, a: datetime,
              casella: str | None, entity: str | None) -> dict:
    filtro = "AND m.data_caricamento > @da AND m.data_caricamento <= @a"
    extra = {}
    if casella:
        filtro += " AND m.casella = @casella"
        extra["casella"] = casella
    if entity:
        filtro += " AND m.entity_id = @entity"
        extra["entity"] = entity
    base = dict(da=da, a=a, **extra)

    importanti = _q(client, f"""
        SELECT m.entity_id, m.subject, m.mittente, c.primary_category,
               EXISTS(SELECT 1 FROM `{F_PEC_PANEL_PROJECTIONS}` p
                      WHERE p.msgid = m.msgid AND p.status='COPIED') AS proiettato
        FROM `{F_PEC_MESSAGES}` m JOIN `{_V_CORRENTE}` c USING (msgid)
        WHERE c.importance = 'ALTA' {filtro} ORDER BY m.data_evento DESC""", **base)
    anomalie = _q(client, f"""
        SELECT m.entity_id, m.subject, m.tipo FROM `{F_PEC_MESSAGES}` m
        WHERE m.tipo = 'ANOMALIA' {filtro}""", **base)
    errori = _q(client, f"""
        SELECT m.entity_id, m.subject, m.parse_warning FROM `{F_PEC_MESSAGES}` m
        WHERE m.parse_warning IS NOT NULL {filtro}""", **base)
    non_sync = _q(client, f"""
        SELECT m.entity_id, a.nome_file, a.gcs_uri, a.size_bytes
        FROM `{F_PEC_ALLEGATI}` a JOIN `{F_PEC_MESSAGES}` m USING (msgid)
        JOIN `{_V_CORRENTE}` c USING (msgid)
        LEFT JOIN `{F_PEC_PANEL_PROJECTIONS}` p
          ON p.msgid = a.msgid AND p.sha256 = a.sha256 AND p.status = 'COPIED'
        WHERE c.importance = 'ALTA' AND p.projection_key IS NULL
          AND m.entity_id IN ('INTUR','ORTI','VIGNA') {filtro}""", **base)
    ambigui = _q(client, f"""
        SELECT m.entity_id, m.subject, m.mittente
        FROM `{F_PEC_MESSAGES}` m JOIN `{_V_CORRENTE}` c USING (msgid)
        WHERE c.stato = 'AMBIGUO' {filtro}""", **base)
    non_class = _q(client, f"""
        SELECT m.entity_id, m.subject, m.mittente
        FROM `{F_PEC_MESSAGES}` m JOIN `{_V_CORRENTE}` c USING (msgid)
        WHERE c.stato IN ('NON_CLASSIFICATO','ERRORE_CLASSIFICAZIONE') {filtro}""",
        **base)
    risolti = _q(client, f"""
        SELECT c.msgid, c.primary_category, c.override_note
        FROM `{_V_CORRENTE}` c
        WHERE c.override_source = 'HUMAN'
          AND c.classified_at > @da AND c.classified_at <= @a""", da=da, a=a)
    totali = _q(client, f"""
        SELECT m.casella, COUNT(*) AS n FROM `{F_PEC_MESSAGES}` m
        WHERE TRUE {filtro} GROUP BY 1""", **base)

    return {
        "finestra": (da, a), "importanti": importanti,
        "anomalie_ricevute": anomalie, "errori_parsing": errori,
        "non_sincronizzati": non_sync, "ambigui": ambigui,
        "non_classificati": non_class, "risolti": risolti,
        "totali_per_casella": {r["casella"]: r["n"] for r in totali},
    }


def _sezione(titolo: str, righe: list[dict], fmt_riga) -> list[str]:
    out = [f"## {titolo}", ""]
    out += [f"- {fmt_riga(r)}" for r in righe] if righe else ["_niente_"]
    out.append("")
    return out


def _render_markdown(dati: dict, solo_anomalie: bool) -> str:
    da, a = dati["finestra"]
    out = [f"# Digest PEC — {a:%Y-%m-%d}", "",
           f"Finestra: {da:%Y-%m-%d %H:%M} → {a:%Y-%m-%d %H:%M}", ""]
    if not solo_anomalie:
        out += _sezione(
            "Messaggi importanti", dati["importanti"],
            lambda r: f"**{r['entity_id']}** [{r['primary_category']}] "
                      f"{r['subject']} — da {r['mittente']}"
                      f"{' → nel pannello' if r['proiettato'] else ' (non proiettato)'}",
        )
    out += _sezione("Ricevute anomale", dati["anomalie_ricevute"],
                    lambda r: f"**{r['entity_id']}** {r['subject']} ({r['tipo']})")
    out += _sezione("Errori di parsing", dati["errori_parsing"],
                    lambda r: f"**{r['entity_id']}** {r['subject']}: {r['parse_warning']}")
    out += _sezione("Allegati importanti non sincronizzati", dati["non_sincronizzati"],
                    lambda r: f"**{r['entity_id']}** {r['nome_file']} — {r['gcs_uri']}")
    if not solo_anomalie:
        out += _sezione("Classificazioni ambigue", dati["ambigui"],
                        lambda r: f"**{r['entity_id']}** {r['subject']} — {r['mittente']}")
        out += _sezione("Da rivedere (non classificati)", dati["non_classificati"],
                        lambda r: f"**{r['entity_id']}** {r['subject']} — {r['mittente']}")
        out += _sezione("Risolti dall'ultimo digest", dati["risolti"],
                        lambda r: f"{r['msgid']} → {r['primary_category']} ({r['override_note'] or 'override'})")
        out += ["## Totali nuovi messaggi", ""]
        out += [f"- {c}: {n}" for c, n in dati["totali_per_casella"].items()] or ["_niente_"]
        out.append("")
    return "\n".join(out)


def run_digest(da: datetime | None = None, a: datetime | None = None,
               casella: str | None = None, entity: str | None = None,
               solo_anomalie: bool = False, fmt: str = "markdown",
               dry_run: bool = False) -> str:
    from core.bq.client import get_client
    from core.bq.write import bq_write_validated

    client = get_client()
    if _run_aperto(client):
        raise RuntimeError("un digest è già RUNNING: attendere o marcarlo FAILED")

    a = a or datetime.now()
    da = da or _ultimo_success(client) or EPOCA_CORPUS
    run_id = f"digest-{uuid.uuid4().hex[:12]}"
    started = datetime.now()
    params = json.dumps({"casella": casella, "entity": entity,
                         "solo_anomalie": solo_anomalie, "format": fmt})

    def _checkpoint(status: str, finished: datetime | None) -> None:
        if dry_run:
            return
        row = {"run_id": run_id, "started_at": started, "finished_at": finished,
               "status": status, "from_ts": da, "to_ts": a, "params": params}
        validate_batch([row], PecDigestRunRow, context="f_pec_digest_runs")
        bq_write_validated(F_PEC_DIGEST_RUNS, [PecDigestRunRow(**row)], mode="append")

    _checkpoint("RUNNING", None)
    try:
        dati = _raccogli(client, da, a, casella, entity)
        if fmt == "json":
            reso = json.dumps(dati, default=str, ensure_ascii=False, indent=2)
        else:
            reso = _render_markdown(dati, solo_anomalie)
            if not dry_run:
                dest = _percorso_file(a)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(reso)
                (Path(PANEL_ROOT) / "_digest" / "latest.md").write_text(reso)
    except Exception:
        _checkpoint("FAILED", datetime.now())
        raise
    _checkpoint("SUCCESS", datetime.now())
    return reso
```

Nota: `f_pec_digest_runs` è APPEND-only come tutto il resto — lo "stato" di un
run è l'ultima riga per `run_id` (RUNNING poi SUCCESS/FAILED); `_run_aperto`
va quindi implementato come: esiste un run_id la cui ULTIMA riga è RUNNING:

```python
def _run_aperto(client) -> bool:
    sql = f"""
    SELECT 1 FROM (
      SELECT run_id, ARRAY_AGG(status ORDER BY COALESCE(finished_at, started_at) DESC
             LIMIT 1)[OFFSET(0)] AS ultimo
      FROM `{F_PEC_DIGEST_RUNS}` GROUP BY run_id
    ) WHERE ultimo = 'RUNNING' LIMIT 1
    """
    try:
        return any(client.query(sql).result())
    except Exception:
        return False
```

(usare QUESTA versione, non quella semplice mostrata sopra).

- [ ] **Step 4: Verificare** — Run: `pytest tests/test_pec_digest.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add ingest/pec/digest.py core/schemas.py tests/test_pec_digest.py
git commit -m "feat(pec): digest CEO con checkpoint f_pec_digest_runs e output su _digest/YYYY/MM"
```

---

### Task 9: CLI `hotelops pec`

**Files:**
- Modify: `cli.py` (nuovo `cmd_pec` + parser + entry nel dict `handlers`)
- Test: smoke manuale (il CLI del repo non ha test dedicati)

**Interfaces:**
- Consumes: `run_classify` (Task 6), `sync_panel` (Task 7), `run_digest` (Task 8).
- Produces: `hotelops pec classify [--dry-run]`, `hotelops pec sync-panel [--dry-run] [--verify]`, `hotelops pec digest [--da YYYY-MM-DD] [--a YYYY-MM-DD] [--casella X] [--entity E] [--solo-anomalie] [--format markdown|json] [--dry-run]`.

- [ ] **Step 1: Implementare** — in `cli.py`, vicino agli altri `cmd_*`:

```python
def cmd_pec(args):
    """Layer CEO sulla PEC: classify / sync-panel / digest."""
    from datetime import datetime

    if args.pec_cmd == "classify":
        from ingest.pec.classify import run_classify

        r = run_classify(dry_run=args.dry_run)
        print(f"ruleset {r['ruleset_version']}: {r['classificati']} righe {r['per_stato']}")
    elif args.pec_cmd == "sync-panel":
        from ingest.pec.panel import sync_panel

        r = sync_panel(dry_run=args.dry_run, verify=args.verify)
        print(
            f"copiati={r['copiati']} skippati={r['skippati']} "
            f"falliti={r['falliti']} oversize={r['oversize']}"
        )
        for a in r["anomalie_verify"]:
            print(f"  VERIFY: {a}")
    elif args.pec_cmd == "digest":
        from ingest.pec.digest import run_digest

        parse = lambda s: datetime.strptime(s, "%Y-%m-%d") if s else None
        print(run_digest(
            da=parse(args.da), a=parse(args.a), casella=args.casella,
            entity=args.entity, solo_anomalie=args.solo_anomalie,
            fmt=args.format, dry_run=args.dry_run,
        ))
    else:
        print("uso: hotelops pec {classify|sync-panel|digest}")
        sys.exit(1)
```

Nella sezione dei parser (accanto a `p_reviews`):

```python
    p_pec = sub.add_parser("pec", help="PEC multi-casella: classify, pannello CEO, digest")
    pec_sub = p_pec.add_subparsers(dest="pec_cmd")
    pp_cl = pec_sub.add_parser("classify", help="Classifica i messaggi non classificati")
    pp_cl.add_argument("--dry-run", action="store_true")
    pp_sp = pec_sub.add_parser("sync-panel", help="Proietta i documenti ALTA su AMM_CEO")
    pp_sp.add_argument("--dry-run", action="store_true")
    pp_sp.add_argument("--verify", action="store_true", help="Riconcilia pannello vs BQ")
    pp_dg = pec_sub.add_parser("digest", help="Digest monitoraggio caselle")
    pp_dg.add_argument("--da", type=str, default=None)
    pp_dg.add_argument("--a", type=str, default=None)
    pp_dg.add_argument("--casella", type=str, default=None)
    pp_dg.add_argument("--entity", type=str, default=None,
                       choices=["INTUR", "ORTI", "VIGNA", "STEFANO_PERSONALE"])
    pp_dg.add_argument("--solo-anomalie", action="store_true")
    pp_dg.add_argument("--format", choices=["markdown", "json"], default="markdown")
    pp_dg.add_argument("--dry-run", action="store_true")
```

Nel dict `handlers` (riga ~1380): aggiungere `"pec": cmd_pec,`.

- [ ] **Step 2: Smoke** — Run: `python cli.py pec` → stampa l'uso, exit 1. `python cli.py pec digest --dry-run --format json` → JSON su stdout (richiede BQ; se auth manca, farla rinnovare a Stefano).

- [ ] **Step 3: Commit**

```bash
git add cli.py
git commit -m "feat(pec): CLI hotelops pec (classify / sync-panel / digest)"
```

---

### Task 10: Bonifica copie manuali

**Files:**
- Create: `scripts/bonifica_pec_manuali.py`
- Test: `tests/test_pec_multicasella.py` (append — sola logica di verifica)

**Interfaces:**
- Consumes: `f_raw_objects` (lineage), GCS.
- Produces: script `python -m scripts.bonifica_pec_manuali [--esegui]` — default report-only; con `--esegui` rimuove SOLO gli oggetti che superano le 4 verifiche della spec.

- [ ] **Step 1: Test della logica** — append a `tests/test_pec_multicasella.py`:

```python
def test_bonifica_richiede_tutte_le_verifiche():
    from scripts.bonifica_pec_manuali import puo_rimuovere

    ok = dict(promoted=True, canonico_esiste=True, hash_combacia=True,
              lineage_persistita=True)
    assert puo_rimuovere(**ok)
    for k in ok:
        kw = {**ok, k: False}
        assert not puo_rimuovere(**kw), f"doveva bloccare con {k}=False"
```

- [ ] **Step 2: Implementare `scripts/bonifica_pec_manuali.py`**:

```python
"""Bonifica one-shot delle copie PEC caricate a mano il 2026-07-16.

Prefissi manuali: gs://orti-raw/pec/** e gs://stefano-raw/pec/** (VIGNA solo
dopo che sarà ingerita dal nuovo flusso). Rimozione SOLO se, per ogni file:
promote SUCCESS + oggetto canonico presente + hash combaciante + lineage in
BQ (spec 2026-07-17 §bonifica). Default: report-only. --esegui per rimuovere.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import logging

from core.config import PROJECT

log = logging.getLogger("scripts.bonifica_pec")

PREFISSI_MANUALI = [("orti-raw", "pec/"), ("stefano-raw", "pec/")]
# I path canonici delle sorgenti PEC (raw_storage.path_template) NON stanno
# sotto pec/ ma sotto pec/mailbox/<ENTITY>/... tramite intake: qui si
# escludono per non toccare mai il canonico.
PREFISSI_CANONICI = ("pec/mailbox/",)


def puo_rimuovere(promoted: bool, canonico_esiste: bool,
                  hash_combacia: bool, lineage_persistita: bool) -> bool:
    return promoted and canonico_esiste and hash_combacia and lineage_persistita


def _md5_hex(blob) -> str:
    return binascii.hexlify(base64.b64decode(blob.md5_hash)).decode()


def _stato_lineage(client, content_hash: str) -> tuple[bool, bool, str | None]:
    """(promoted, lineage_persistita, raw_uri_canonico) per content_hash."""
    sql = f"""
    SELECT r.raw_object_id, r.raw_uri,
      (SELECT ARRAY_AGG(e.to_status IGNORE NULLS ORDER BY e.event_at DESC LIMIT 1)[OFFSET(0)]
       FROM `{PROJECT}.hotelops.f_lineage_events` e
       WHERE e.raw_object_id = r.raw_object_id) AS stato
    FROM `{PROJECT}.hotelops.f_raw_objects` r
    WHERE r.content_hash = @h
    """
    from google.cloud import bigquery

    rows = list(client.query(sql, job_config=bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("h", "STRING", content_hash)]
    )).result())
    if not rows:
        return False, False, None
    r = rows[0]
    return (r.stato == "PROMOTED"), True, r.raw_uri


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--esegui", action="store_true",
                    help="rimuove davvero (default: solo report)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from google.cloud import storage

    from core.bq.client import get_client

    gcs = storage.Client(project=PROJECT)
    bq = get_client()
    rimossi, bloccati = [], []

    for bucket_name, prefisso in PREFISSI_MANUALI:
        bucket = gcs.bucket(bucket_name)
        for blob in bucket.list_blobs(prefix=prefisso):
            if blob.name.startswith(PREFISSI_CANONICI):
                continue
            h = _md5_hex(blob)
            promoted, lineage, raw_uri = _stato_lineage(bq, h)
            canonico, combacia = False, False
            if raw_uri and raw_uri.startswith("gs://"):
                b2, _, p2 = raw_uri.removeprefix("gs://").partition("/")
                can = gcs.bucket(b2).get_blob(p2)
                canonico = can is not None
                combacia = canonico and _md5_hex(can) == h
            verdetto = puo_rimuovere(promoted, canonico, combacia, lineage)
            riga = (f"gs://{bucket_name}/{blob.name} → promoted={promoted} "
                    f"canonico={canonico} hash_ok={combacia} lineage={lineage}")
            if verdetto:
                rimossi.append(riga)
                if args.esegui:
                    blob.delete()
            else:
                bloccati.append(riga)

    azione = "RIMOSSO" if args.esegui else "RIMOVIBILE"
    for r in rimossi:
        log.info("%s: %s", azione, r)
    for r in bloccati:
        log.warning("BLOCCATO: %s", r)
    log.info("totale: %d %s, %d bloccati", len(rimossi), azione.lower(), len(bloccati))


if __name__ == "__main__":
    main()
```

⚠️ Prima di eseguire: verificare i nomi reali della tabella eventi lineage
(`f_lineage_events` vs altro) con `grep -n "F_RAW_OBJECTS\|lineage_events" core/lineage/raw_manifest.py`
e adeguare la query.

- [ ] **Step 3: Verificare** — Run: `pytest tests/test_pec_multicasella.py -v -k bonifica` → PASS. Poi `python -m scripts.bonifica_pec_manuali` (report-only) → con gli intake non ancora fatti, tutto BLOCCATO: corretto.

- [ ] **Step 4: Commit**

```bash
git add scripts/bonifica_pec_manuali.py tests/test_pec_multicasella.py
git commit -m "feat(pec): bonifica verificata delle copie manuali nei bucket raw"
```

---

### Task 11: Test end-to-end e invarianti

**Files:**
- Create: `tests/test_pec_e2e.py`

**Interfaces:**
- Consumes: tutto quanto sopra. BQ e GCS mockati; filesystem reale in `tmp_path`.

- [ ] **Step 1: Scrivere il test e2e**:

```python
"""E2E su fixture: parse → classify → panel, con BQ/GCS finti.

Invarianti coperti: I-PEC-2 (entity dal registry), I-PEC-3 (personale mai nel
pannello), I-PEC-4 (idempotenza), I-PEC-6 (no path traversal). Il resto della
pipeline (intake/promote) ha i suoi test di lineage già esistenti.
"""

from __future__ import annotations

from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import pytest


def _eml_con_allegato(path: Path, casella_from: str, nome_allegato: str) -> Path:
    m = EmailMessage()
    m["From"] = casella_from
    m["To"] = "avvocato@legalmail.it"
    m["Subject"] = "Diffida ad adempiere"
    m["Message-ID"] = f"<e2e-{nome_allegato}@test>"
    m["Date"] = "Wed, 15 Jul 2026 16:38:59 +0200"
    m.set_content("testo")
    m.add_attachment(b"%PDF-fake", maintype="application", subtype="pdf",
                     filename=nome_allegato)
    path.write_bytes(bytes(m))
    return path


def test_e2e_parse_classify_panel(tmp_path, monkeypatch):
    from ingest.flussi.ingest_pec_mbox import ingest_file, resolve_pec_source
    from ingest.pec.classify import classify_message, load_ruleset

    # 1. Parse (dry-run: niente GCS/BQ) — entity dal registry
    src = resolve_pec_source("PEC_MAILBOX_PERSONALE_APPEND")
    eml = _eml_con_allegato(
        tmp_path / "m.eml", "stefanojunior.dellapietra@mpspec.it",
        "../../evil contratto.pdf",
    )
    report = ingest_file(eml, src, dry_run=True)
    assert report["righe_messaggi"] == 1

    # 2. Classify: oggetto legale → LEGALE/ALTA
    esito = classify_message(
        "avvocato@legalmail.it", "Diffida ad adempiere",
        ["../../evil contratto.pdf"], load_ruleset(),
    )
    assert esito["primary_category"] == "LEGALE"
    assert esito["importance"] == "ALTA"

    # 3. Panel: STEFANO_PERSONALE mai proiettabile (I-PEC-3)
    from ingest.pec.panel import _destination_path

    with pytest.raises(ValueError, match="whitelist"):
        _destination_path("STEFANO_PERSONALE", "LEGALE",
                          datetime(2026, 7, 15), "evil contratto.pdf")

    # 4. Per un'entity ammessa, il nome malevolo resta sotto root (I-PEC-6)
    rel = _destination_path("ORTI", "LEGALE", datetime(2026, 7, 15),
                            "../../evil contratto.pdf")
    assert rel.parts[0] == "ORTI" and ".." not in str(rel)


def test_e2e_idempotenza_parse(tmp_path):
    """Stesso file due volte: dedup in-file su msgid, stesse righe (I-PEC-4)."""
    import mailbox

    from ingest.flussi.ingest_pec_mbox import ingest_file, resolve_pec_source

    src = resolve_pec_source("PEC_MAILBOX_ORTI_APPEND")
    mb_path = tmp_path / "doppio.mbox"
    box = mailbox.mbox(str(mb_path))
    m = EmailMessage()
    m["From"] = "orti@pec.it"
    m["To"] = "x@pec.it"
    m["Subject"] = "s"
    m["Message-ID"] = "<dup-1@test>"
    m["Date"] = "Wed, 15 Jul 2026 16:38:59 +0200"
    m.set_content("c")
    box.add(m)
    box.add(m)  # duplicato nello stesso container
    box.flush()

    report = ingest_file(mb_path, src, dry_run=True)
    assert report["messaggi_letti"] == 2
    assert report["dedup_in_file"] == 1
    assert report["righe_messaggi"] == 1
```

- [ ] **Step 2: Verificare** — Run: `pytest tests/test_pec_e2e.py -v` → PASS. Poi TUTTA la suite: `pytest tests/ -q` → nessuna regressione.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pec_e2e.py
git commit -m "test(pec): e2e parse→classify→panel + invarianti I-PEC-2/3/4/6"
```

---

### Task 12: Messa in produzione (runbook operativo)

Nessun codice nuovo: esecuzione ordinata con verifiche. Richiede BQ/GCS
autenticati e Google Drive per Desktop attivo.

- [ ] **Step 1: Migrazione** — Task 3 Step 3 se non già eseguito.

- [ ] **Step 2: Intake + promote ORTI** (originali in `~/Downloads`):

```bash
cd /Users/stefanodellapietra/dev/Projects/hotelops
for f in "Email Export (1).mbox" "Email Export (2).mbox" "Email Export.mbox" "export (1).mbox" "export (2).mbox"; do
  python cli.py intake --file "/Users/stefanodellapietra/Downloads/$f" --source-name PEC_MAILBOX_ORTI_APPEND
done
```

Per ogni `raw_object_id` stampato: `python cli.py promote --raw-object-id <id>`.
Expected: `status=PROMOTED`. (Verificare il nome esatto del flag di intake con
`python cli.py intake --help` prima di partire: `--source-name` vs `--source_name`.)

- [ ] **Step 3: Intake + promote PERSONALE** (6 .eml):

```bash
for f in "/Users/stefanodellapietra/Downloads/Messages Archive/"*.eml; do
  python cli.py intake --file "$f" --source-name PEC_MAILBOX_PERSONALE_APPEND
done
```

poi promote di ciascun raw_object_id → `PROMOTED`.

- [ ] **Step 4: Intake + promote VIGNA** (download da GCS → intake, decisione spec):

```bash
mkdir -p /tmp/vigna_pec && gcloud storage cp -r "gs://vigna-raw/pec/*" /tmp/vigna_pec/
find /tmp/vigna_pec -name "*.mbox" -exec python cli.py intake --file {} --source-name PEC_MAILBOX_VIGNA_APPEND \;
```

poi promote → `PROMOTED`.

- [ ] **Step 5: Verifica registro unificato**:

```bash
bq query --use_legacy_sql=false "SELECT entity_id, COUNT(*) n FROM \`hotelops-suite.hotelops.f_pec_messages\` GROUP BY 1 ORDER BY 1"
```

Expected: quattro entity con conteggi > 0.

- [ ] **Step 6: Classify + vista**: `python cli.py pec classify` poi deploy della vista (Task 6 Step 6) se non già fatto. Expected: report con `per_stato` sensato; rivedere a campione 5 righe AMBIGUO/NON_CLASSIFICATO.

- [ ] **Step 7: Primo sync-panel**: prima `python cli.py pec sync-panel --dry-run` (contare i candidati e mostrarli a Stefano), poi `python cli.py pec sync-panel`. Expected: file in `AMM_CEO/<ENTITY>/PEC/<Categoria>/`, zero file sotto entity non whitelisted; `python cli.py pec sync-panel --verify` → zero anomalie.

- [ ] **Step 8: Primo digest**: `python cli.py pec digest`. Expected: markdown a video + file in `AMM_CEO/_digest/2026/07/` + `latest.md`.

- [ ] **Step 9: Bonifica**: `python -m scripts.bonifica_pec_manuali` (report) — se tutto RIMOVIBILE, con conferma di Stefano: `python -m scripts.bonifica_pec_manuali --esegui`. Includere ora anche i prefissi VIGNA aggiungendo `("vigna-raw", "pec/")` a `PREFISSI_MANUALI` SOLO dopo il promote VIGNA riuscito.

- [ ] **Step 10: Commit finale + save-game**: commit di eventuali ritocchi, poi invocare la skill `save-game` per allineare il CLAUDE.md del repo (nuovo package `ingest/pec/`, comando `pec`, tabelle nuove).

---

## Self-Review (eseguita)

1. **Spec coverage**: EntityId→T1; registry/formati→T2; migrazione→T3; parser/--source/.eml/dedup→T4; promotion→T5; classificatore 3 dimensioni+stati+versioning→T6; projection canonica+whitelist+traversal→T7; digest+checkpoint+struttura file→T8; CLI→T9; bonifica 4 verifiche→T10; e2e invarianti→T11; runbook (VIGNA download→intake)→T12. Nessun gap rilevato.
2. **Placeholder**: nessun TBD; i due punti dove il piano rimanda a una verifica sul repo (nome tabella lineage in T10, flag intake in T12, convenzione file in `core/bq/views/` in T6) sono verifiche esplicite con comando, non lacune.
3. **Type consistency**: `PecSource` (T4) usato in T4/T11; `classify_message` firma identica T6/T11; `projection_key(msgid, sha256, dest_rel)` T7 coerente col digest T8 (join su msgid+sha256); nomi tabella via `core/config.py` ovunque.
