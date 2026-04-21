# Projects MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `progetti/` as the 4th HotelOps vertical — project subledger with forward-flow to CONDGES. Seed with `HPAN25PIANO1` (Camere Primo Piano Hotel Panorama, cap 1.2M EUR).

**Architecture:** New `progetti/` top-level package (peer of `condges/`, `reviews/`). 7 entity Pydantic models + 8 BQ tables + 6 views. LLM extraction via Claude Haiku with human review. Forward-flow solver emits to `f_piano_finanziario_input` fonte=`PROGETTI`. Streamlit `app_projects.py` with 4 views. Respects I1–I8; I9 candidato declared (subledger + forward-flow, not retroactive tagging). I10 retired as vertical business rule.

**Tech Stack:** Python 3.11, Pydantic v2, BigQuery (`hotelops-suite.hotelops`), Streamlit, Anthropic SDK (`claude-haiku-4-5-20251001`), `rapidfuzz` for fuzzy supplier matching (new dep), existing `core/bq/client.get_client()`, existing `core/datahub_sync` for rclone.

**Spec:** `docs/superpowers/specs/2026-04-20-projects-mvp-design.md`.
**Seed doc:** `docs/progetti/HPAN25PIANO1-walkthrough.md`.
**Branch:** `projects-mvp-hpan25piano1` (create at Task 0).

---

## Task 0: Branch + scaffold `progetti/` package

**Files:**
- Create: `progetti/__init__.py`
- Create: `progetti/models.py`, `progetti/extract.py`, `progetti/fuzzy.py`, `progetti/forward_flow.py`, `progetti/cli_commands.py`, `progetti/app_projects.py`, `progetti/config.py` (empty stubs)
- Modify: `pyproject.toml`

- [ ] **Step 1: Create branch**

```bash
git checkout -b projects-mvp-hpan25piano1
```

- [ ] **Step 2: Create package skeleton**

```bash
mkdir -p progetti
touch progetti/__init__.py progetti/models.py progetti/extract.py progetti/fuzzy.py progetti/forward_flow.py progetti/cli_commands.py progetti/app_projects.py progetti/config.py
```

- [ ] **Step 3: Add deps to `pyproject.toml`**

Open `pyproject.toml`, find the `dependencies = [...]` list, add:

```toml
"rapidfuzz>=3.6",
```

Check if `anthropic` is already in deps (reviews vertical uses it). If yes, skip. If no, add:

```toml
"anthropic>=0.34",
```

- [ ] **Step 4: Install**

Run: `pip install -e ".[dev]"`
Expected: `rapidfuzz` importable; `anthropic` importable.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml progetti/
git commit -m "chore(progetti): scaffold 4th vertical package + deps (rapidfuzz)"
```

---

## Task 1: Pydantic models — Project + ScopePackage

**Files:**
- Modify: `progetti/models.py`
- Create: `tests/test_projects_models.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_projects_models.py
from datetime import date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from progetti.models import Project, ScopePackage


def test_project_minimum_valid():
    p = Project(
        progetto_id="HPAN25PIANO1",
        nome="Camere Primo Piano - Hotel Panorama",
        societa_beneficiaria_id="INTUR",
        business_unit_id="HOTEL",
        struttura="Hotel Panorama",
        data_inizio=date(2026, 2, 1),
        data_fine_prevista=date(2026, 5, 31),
        budget_cap_eur=Decimal("1200000"),
        stato="IN_CORSO",
        owner="Stefano Della Pietra Jr",
        direzione_lavori="Amalia Pisacane",
    )
    assert p.progetto_id == "HPAN25PIANO1"
    assert p.budget_cap_eur == Decimal("1200000")


def test_project_rejects_unknown_societa():
    with pytest.raises(ValidationError):
        Project(
            progetto_id="X",
            nome="X",
            societa_beneficiaria_id="ACME",
            business_unit_id="HOTEL",
            struttura="X",
            data_inizio=date.today(),
            data_fine_prevista=None,
            budget_cap_eur=Decimal("1"),
            stato="IN_CORSO",
            owner="X",
            direzione_lavori=None,
        )


def test_scope_package_categoria_enum():
    s = ScopePackage(
        scope_id="uuid-1",
        progetto_id="HPAN25PIANO1",
        codice="SP-PORTE-STD",
        descrizione="Porte standard camere",
        categoria="PORTE",
        importo_stimato_eur=Decimal("42000"),
        stato="PREVENTIVATO",
        data_stato=datetime(2026, 3, 1, 9, 0),
        note=None,
    )
    assert s.categoria == "PORTE"


def test_scope_package_rejects_unknown_categoria():
    with pytest.raises(ValidationError):
        ScopePackage(
            scope_id="x",
            progetto_id="HPAN25PIANO1",
            codice="x",
            descrizione="x",
            categoria="GARDENING",
            importo_stimato_eur=Decimal("1"),
            stato="IDENTIFICATO",
            data_stato=datetime.now(),
            note=None,
        )
```

- [ ] **Step 2: Run tests — verify fail**

Run: `pytest tests/test_projects_models.py -v`
Expected: FAIL — `ImportError` (Project/ScopePackage not defined).

- [ ] **Step 3: Implement models**

```python
# progetti/models.py
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Project(BaseModel):
    model_config = ConfigDict(frozen=False)
    progetto_id: str
    nome: str
    societa_beneficiaria_id: Literal["ORTI", "INTUR"]
    business_unit_id: str
    struttura: str
    data_inizio: date
    data_fine_prevista: date | None
    budget_cap_eur: Decimal
    stato: Literal["PIANIFICATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    owner: str
    direzione_lavori: str | None


ScopeCategoria = Literal[
    "OPERE_MURARIE",
    "IMPIANTI",
    "ARREDI",
    "FINITURE",
    "PORTE",
    "CONSULENZE",
    "PROGETTAZIONE",
    "PM",
    "ALTRO",
]

ScopeStato = Literal["IDENTIFICATO", "PREVENTIVATO", "IMPEGNATO", "CHIUSO"]


class ScopePackage(BaseModel):
    scope_id: str
    progetto_id: str
    codice: str
    descrizione: str
    categoria: ScopeCategoria
    importo_stimato_eur: Decimal
    stato: ScopeStato
    data_stato: datetime
    note: str | None
```

- [ ] **Step 4: Run tests — verify pass**

Run: `pytest tests/test_projects_models.py -v`
Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add progetti/models.py tests/test_projects_models.py
git commit -m "feat(progetti): Project + ScopePackage Pydantic models"
```

---

## Task 2: Pydantic models — Document + DocumentExtraction

**Files:**
- Modify: `progetti/models.py`
- Modify: `tests/test_projects_models.py`

- [ ] **Step 1: Append failing tests**

```python
# tests/test_projects_models.py (append)
from progetti.models import Document, DocumentExtraction


def test_document_preventivo_stato():
    d = Document(
        document_id="uuid-doc1",
        scope_package_id="uuid-scope1",
        tipo="PREVENTIVO",
        fornitore_id="STE",
        fornitore_denorm="STE Srl",
        numero_documento="P-2026-042",
        data_documento=date(2026, 3, 1),
        importo_eur=Decimal("85000"),
        stato_preventivo="ACCETTATO",
        drive_path="investimenti2026/HPAN25PIANO1/preventivi/STE.pdf",
        file_hash_md5="a" * 32,
        estratto_confidence=0.92,
        estratto_reviewed=True,
        note=None,
    )
    assert d.stato_preventivo == "ACCETTATO"


def test_document_extraction_audit():
    e = DocumentExtraction(
        extraction_id="ex-1",
        document_id="uuid-doc1",
        model="claude-haiku-4-5-20251001",
        raw_output='{"importo": 85000}',
        parsed_fields={"importo": 85000},
        confidence_per_field={"importo": 0.95},
        ts_extraction=datetime(2026, 4, 21, 10, 0),
        reviewed_by="stefano",
        ts_reviewed=datetime(2026, 4, 21, 10, 5),
    )
    assert e.model == "claude-haiku-4-5-20251001"
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/test_projects_models.py -v`
Expected: ImportError on new symbols.

- [ ] **Step 3: Add models**

```python
# progetti/models.py (append)
DocumentTipo = Literal["PREVENTIVO", "CONTRATTO", "ORDINE", "FATTURA", "SAL", "ALTRO"]
PreventivoStato = Literal["RICEVUTO", "ACCETTATO", "RIFIUTATO", "SCADUTO"]


class Document(BaseModel):
    document_id: str
    scope_package_id: str
    tipo: DocumentTipo
    fornitore_id: str | None
    fornitore_denorm: str
    numero_documento: str | None
    data_documento: date | None
    importo_eur: Decimal | None
    stato_preventivo: PreventivoStato | None
    drive_path: str
    file_hash_md5: str
    estratto_confidence: float
    estratto_reviewed: bool
    note: str | None


class DocumentExtraction(BaseModel):
    extraction_id: str
    document_id: str
    model: str
    raw_output: str
    parsed_fields: dict
    confidence_per_field: dict
    ts_extraction: datetime
    reviewed_by: str | None
    ts_reviewed: datetime | None
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/test_projects_models.py -v`
Expected: 6/6 PASS.

- [ ] **Step 5: Commit**

```bash
git add progetti/models.py tests/test_projects_models.py
git commit -m "feat(progetti): Document + DocumentExtraction models"
```

---

## Task 3: Pydantic models — Commitment + PaymentSchedule + ScopeCommitmentLink + InvoiceLink

**Files:**
- Modify: `progetti/models.py`
- Modify: `tests/test_projects_models.py`

- [ ] **Step 1: Append failing tests**

```python
# tests/test_projects_models.py (append)
from progetti.models import (
    Commitment,
    PaymentSchedule,
    ScopeCommitmentLink,
    InvoiceLink,
)


def test_commitment_capex_intur():
    c = Commitment(
        commitment_id="c-1",
        progetto_id="HPAN25PIANO1",
        descrizione="Contratto STE impianti",
        fornitore_id="STE",
        fornitore_denorm="STE Srl",
        societa_pagante_id="INTUR",
        tipo_spesa="CAPEX",
        importo_impegnato_eur=Decimal("85000"),
        stato="FIRMATO",
        data_stato=datetime(2026, 2, 27, 15, 0),
        from_document_id="uuid-doc1",
        voce_pf_target="INVESTIMENTI_CAPEX",
        note=None,
    )
    assert c.tipo_spesa == "CAPEX"


def test_commitment_immutable_importo_after_firma():
    # importo_impegnato_eur is set at firma; verified immutable via audit pattern
    c = Commitment(
        commitment_id="c-1",
        progetto_id="HPAN25PIANO1",
        descrizione="X",
        fornitore_id="STE",
        fornitore_denorm="STE",
        societa_pagante_id="INTUR",
        tipo_spesa="CAPEX",
        importo_impegnato_eur=Decimal("85000"),
        stato="FIRMATO",
        data_stato=datetime.now(),
        from_document_id=None,
        voce_pf_target="INVESTIMENTI_CAPEX",
        note=None,
    )
    # Contract: downstream code asserts importo never changes across Commitment APPEND
    # (enforced at write-time in repository, not at model level)
    assert c.importo_impegnato_eur == Decimal("85000")


def test_scope_commitment_link_quota():
    lk = ScopeCommitmentLink(
        link_id="lk-1",
        scope_package_id="sp-1",
        commitment_id="c-1",
        quota_importo_eur=Decimal("42000"),
    )
    assert lk.quota_importo_eur == Decimal("42000")


def test_payment_schedule_rata():
    r = PaymentSchedule(
        rate_id="r-1",
        commitment_id="c-1",
        seq=1,
        data_prevista=date(2026, 3, 15),
        importo_eur=Decimal("25500"),
        descrizione="Acconto 30% alla firma",
        stato="PIANIFICATA",
        data_stato=datetime.now(),
    )
    assert r.stato == "PIANIFICATA"


def test_invoice_link_minimal():
    il = InvoiceLink(
        link_id="il-1",
        commitment_id="c-1",
        movimento_row_hash="b" * 32,
        payment_schedule_rate_id="r-1",
        note=None,
    )
    assert il.movimento_row_hash == "b" * 32
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/test_projects_models.py -v`
Expected: ImportError.

- [ ] **Step 3: Add models**

```python
# progetti/models.py (append)
CommitmentStato = Literal["FIRMATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
RataStato = Literal["PIANIFICATA", "EMESSA", "PAGATA", "ANNULLATA"]


class Commitment(BaseModel):
    commitment_id: str
    progetto_id: str
    descrizione: str
    fornitore_id: str | None
    fornitore_denorm: str
    societa_pagante_id: Literal["ORTI", "INTUR"]
    tipo_spesa: Literal["CAPEX", "OPEX"]
    importo_impegnato_eur: Decimal
    stato: CommitmentStato
    data_stato: datetime
    from_document_id: str | None
    voce_pf_target: str
    note: str | None


class ScopeCommitmentLink(BaseModel):
    link_id: str
    scope_package_id: str
    commitment_id: str
    quota_importo_eur: Decimal


class PaymentSchedule(BaseModel):
    rate_id: str
    commitment_id: str
    seq: int
    data_prevista: date
    importo_eur: Decimal
    descrizione: str
    stato: RataStato
    data_stato: datetime


class InvoiceLink(BaseModel):
    link_id: str
    commitment_id: str
    movimento_row_hash: str
    payment_schedule_rate_id: str | None
    note: str | None
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/test_projects_models.py -v`
Expected: 11/11 PASS.

- [ ] **Step 5: Commit**

```bash
git add progetti/models.py tests/test_projects_models.py
git commit -m "feat(progetti): Commitment + PaymentSchedule + ScopeCommitmentLink + InvoiceLink"
```

---

## Task 4: BigQuery DDL — d_progetti + f_progetto_scopes + f_progetto_commitments + f_progetto_scope_commitment_link

**Files:**
- Create: `core/bq/ddl/progetti/d_progetti.sql`
- Create: `core/bq/ddl/progetti/f_progetto_scopes.sql`
- Create: `core/bq/ddl/progetti/f_progetto_commitments.sql`
- Create: `core/bq/ddl/progetti/f_progetto_scope_commitment_link.sql`
- Create: `tests/test_progetti_ddl.py`

- [ ] **Step 1: Write failing SQL existence test**

```python
# tests/test_progetti_ddl.py
from pathlib import Path

import pytest

DDL_DIR = Path("core/bq/ddl/progetti")


def test_ddl_files_exist():
    required = [
        "d_progetti.sql",
        "f_progetto_scopes.sql",
        "f_progetto_commitments.sql",
        "f_progetto_scope_commitment_link.sql",
    ]
    for name in required:
        assert (DDL_DIR / name).exists(), f"missing {name}"


def test_ddl_d_progetti_has_required_cols():
    sql = (DDL_DIR / "d_progetti.sql").read_text()
    for col in [
        "progetto_id",
        "nome",
        "societa_beneficiaria_id",
        "budget_cap_eur",
        "stato",
    ]:
        assert col in sql


def test_ddl_commitments_append_audit():
    sql = (DDL_DIR / "f_progetto_commitments.sql").read_text()
    # Append audit = includes data_stato as partition/ordering key
    assert "data_stato" in sql
    assert "importo_impegnato_eur" in sql
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/test_progetti_ddl.py -v`
Expected: FAIL — files not found.

- [ ] **Step 3: Write DDL files**

```sql
-- core/bq/ddl/progetti/d_progetti.sql
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.d_progetti` (
  progetto_id STRING NOT NULL,
  nome STRING NOT NULL,
  societa_beneficiaria_id STRING NOT NULL,
  business_unit_id STRING NOT NULL,
  struttura STRING,
  data_inizio DATE NOT NULL,
  data_fine_prevista DATE,
  budget_cap_eur NUMERIC NOT NULL,
  stato STRING NOT NULL,
  owner STRING,
  direzione_lavori STRING,
  ts_ingest TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
);
```

```sql
-- core/bq/ddl/progetti/f_progetto_scopes.sql
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.f_progetto_scopes` (
  scope_id STRING NOT NULL,
  progetto_id STRING NOT NULL,
  codice STRING NOT NULL,
  descrizione STRING NOT NULL,
  categoria STRING NOT NULL,
  importo_stimato_eur NUMERIC,
  stato STRING NOT NULL,
  data_stato TIMESTAMP NOT NULL,
  note STRING,
  ts_ingest TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(data_stato)
CLUSTER BY progetto_id, scope_id;
```

```sql
-- core/bq/ddl/progetti/f_progetto_commitments.sql
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.f_progetto_commitments` (
  commitment_id STRING NOT NULL,
  progetto_id STRING NOT NULL,
  descrizione STRING NOT NULL,
  fornitore_id STRING,
  fornitore_denorm STRING NOT NULL,
  societa_pagante_id STRING NOT NULL,
  tipo_spesa STRING NOT NULL,
  importo_impegnato_eur NUMERIC NOT NULL,
  stato STRING NOT NULL,
  data_stato TIMESTAMP NOT NULL,
  from_document_id STRING,
  voce_pf_target STRING NOT NULL,
  note STRING,
  ts_ingest TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(data_stato)
CLUSTER BY progetto_id, commitment_id;
```

```sql
-- core/bq/ddl/progetti/f_progetto_scope_commitment_link.sql
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.f_progetto_scope_commitment_link` (
  link_id STRING NOT NULL,
  scope_package_id STRING NOT NULL,
  commitment_id STRING NOT NULL,
  quota_importo_eur NUMERIC NOT NULL,
  ts_ingest TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY commitment_id, scope_package_id;
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/test_progetti_ddl.py -v`
Expected: 3/3 PASS.

- [ ] **Step 5: Apply DDL to BQ**

```bash
bq query --use_legacy_sql=false < core/bq/ddl/progetti/d_progetti.sql
bq query --use_legacy_sql=false < core/bq/ddl/progetti/f_progetto_scopes.sql
bq query --use_legacy_sql=false < core/bq/ddl/progetti/f_progetto_commitments.sql
bq query --use_legacy_sql=false < core/bq/ddl/progetti/f_progetto_scope_commitment_link.sql
```

Verify: `bq ls hotelops | grep -E "(d_progetti|f_progetto_scope|f_progetto_commitment)"`
Expected: 4 new tables.

- [ ] **Step 6: Commit**

```bash
git add core/bq/ddl/progetti/ tests/test_progetti_ddl.py
git commit -m "feat(progetti): BQ DDL — d_progetti + scopes + commitments + link"
```

---

## Task 5: BigQuery DDL — documenti + payment_schedules + invoice_link + extractions

**Files:**
- Create: `core/bq/ddl/progetti/f_progetto_documenti.sql`
- Create: `core/bq/ddl/progetti/f_progetto_payment_schedules.sql`
- Create: `core/bq/ddl/progetti/f_progetto_invoice_link.sql`
- Create: `core/bq/ddl/progetti/f_progetto_extractions.sql`
- Modify: `tests/test_progetti_ddl.py`

- [ ] **Step 1: Append tests**

```python
# tests/test_progetti_ddl.py (append)
def test_ddl_all_8_tables():
    required = [
        "d_progetti.sql",
        "f_progetto_scopes.sql",
        "f_progetto_commitments.sql",
        "f_progetto_scope_commitment_link.sql",
        "f_progetto_documenti.sql",
        "f_progetto_payment_schedules.sql",
        "f_progetto_invoice_link.sql",
        "f_progetto_extractions.sql",
    ]
    for name in required:
        assert (DDL_DIR / name).exists(), f"missing {name}"


def test_ddl_invoice_link_fk_row_hash():
    sql = (DDL_DIR / "f_progetto_invoice_link.sql").read_text()
    assert "movimento_row_hash" in sql


def test_ddl_documenti_md5_dedup():
    sql = (DDL_DIR / "f_progetto_documenti.sql").read_text()
    assert "file_hash_md5" in sql
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/test_progetti_ddl.py -v`
Expected: FAIL on missing tables.

- [ ] **Step 3: Write DDL**

```sql
-- core/bq/ddl/progetti/f_progetto_documenti.sql
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.f_progetto_documenti` (
  document_id STRING NOT NULL,
  scope_package_id STRING NOT NULL,
  tipo STRING NOT NULL,
  fornitore_id STRING,
  fornitore_denorm STRING NOT NULL,
  numero_documento STRING,
  data_documento DATE,
  importo_eur NUMERIC,
  stato_preventivo STRING,
  drive_path STRING NOT NULL,
  file_hash_md5 STRING NOT NULL,
  estratto_confidence FLOAT64,
  estratto_reviewed BOOL NOT NULL,
  note STRING,
  ts_ingest TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY scope_package_id, tipo, file_hash_md5;
```

```sql
-- core/bq/ddl/progetti/f_progetto_payment_schedules.sql
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.f_progetto_payment_schedules` (
  rate_id STRING NOT NULL,
  commitment_id STRING NOT NULL,
  seq INT64 NOT NULL,
  data_prevista DATE NOT NULL,
  importo_eur NUMERIC NOT NULL,
  descrizione STRING,
  stato STRING NOT NULL,
  data_stato TIMESTAMP NOT NULL,
  ts_ingest TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY data_prevista
CLUSTER BY commitment_id, rate_id;
```

```sql
-- core/bq/ddl/progetti/f_progetto_invoice_link.sql
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.f_progetto_invoice_link` (
  link_id STRING NOT NULL,
  commitment_id STRING NOT NULL,
  movimento_row_hash STRING NOT NULL,
  payment_schedule_rate_id STRING,
  note STRING,
  ts_ingest TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY commitment_id, movimento_row_hash;
```

```sql
-- core/bq/ddl/progetti/f_progetto_extractions.sql
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.f_progetto_extractions` (
  extraction_id STRING NOT NULL,
  document_id STRING NOT NULL,
  model STRING NOT NULL,
  raw_output STRING,
  parsed_fields JSON,
  confidence_per_field JSON,
  ts_extraction TIMESTAMP NOT NULL,
  reviewed_by STRING,
  ts_reviewed TIMESTAMP,
  ts_ingest TIMESTAMP DEFAULT CURRENT_TIMESTAMP()
)
PARTITION BY DATE(ts_extraction);
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/test_progetti_ddl.py -v`
Expected: 6/6 PASS.

- [ ] **Step 5: Apply DDL to BQ**

```bash
for f in core/bq/ddl/progetti/f_progetto_{documenti,payment_schedules,invoice_link,extractions}.sql; do
  bq query --use_legacy_sql=false < "$f"
done
```

Verify: `bq ls hotelops | grep f_progetto_ | wc -l` → 6 (scopes, commitments, link, documenti, payment_schedules, invoice_link, extractions = 7; plus d_progetti = 8 total).

- [ ] **Step 6: Commit**

```bash
git add core/bq/ddl/progetti/ tests/test_progetti_ddl.py
git commit -m "feat(progetti): BQ DDL — documenti + payment_schedules + invoice_link + extractions"
```

---

## Task 6: Latest-state views (scopes, commitments, payment_schedules)

**Files:**
- Create: `core/bq/views/v_progetto_scopes_current.sql`
- Create: `core/bq/views/v_progetto_commitments_current.sql`
- Create: `core/bq/views/v_progetto_payment_schedules_current.sql`
- Create: `tests/test_progetti_views.py`

- [ ] **Step 1: Write failing existence test**

```python
# tests/test_progetti_views.py
from pathlib import Path

VIEWS = Path("core/bq/views")


def test_latest_state_views_exist():
    for name in [
        "v_progetto_scopes_current.sql",
        "v_progetto_commitments_current.sql",
        "v_progetto_payment_schedules_current.sql",
    ]:
        assert (VIEWS / name).exists(), f"missing {name}"


def test_views_use_row_number_dedup():
    for name in [
        "v_progetto_scopes_current.sql",
        "v_progetto_commitments_current.sql",
        "v_progetto_payment_schedules_current.sql",
    ]:
        sql = (VIEWS / name).read_text()
        assert "ROW_NUMBER" in sql
        assert "PARTITION BY" in sql
        assert "ORDER BY data_stato DESC" in sql
```

- [ ] **Step 2: Run — verify fail**

Run: `pytest tests/test_progetti_views.py -v`
Expected: FAIL.

- [ ] **Step 3: Write views**

```sql
-- core/bq/views/v_progetto_scopes_current.sql
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_progetto_scopes_current` AS
SELECT *
FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY scope_id ORDER BY data_stato DESC, ts_ingest DESC) AS rn
  FROM `hotelops-suite.hotelops.f_progetto_scopes`
)
WHERE rn = 1;
```

```sql
-- core/bq/views/v_progetto_commitments_current.sql
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_progetto_commitments_current` AS
SELECT *
FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY commitment_id ORDER BY data_stato DESC, ts_ingest DESC) AS rn
  FROM `hotelops-suite.hotelops.f_progetto_commitments`
)
WHERE rn = 1;
```

```sql
-- core/bq/views/v_progetto_payment_schedules_current.sql
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_progetto_payment_schedules_current` AS
SELECT *
FROM (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY rate_id ORDER BY data_stato DESC, ts_ingest DESC) AS rn
  FROM `hotelops-suite.hotelops.f_progetto_payment_schedules`
)
WHERE rn = 1;
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/test_progetti_views.py -v`
Expected: 2/2 PASS.

- [ ] **Step 5: Apply views to BQ**

```bash
for v in v_progetto_scopes_current v_progetto_commitments_current v_progetto_payment_schedules_current; do
  bq query --use_legacy_sql=false < "core/bq/views/${v}.sql"
done
```

- [ ] **Step 6: Commit**

```bash
git add core/bq/views/v_progetto_*_current.sql tests/test_progetti_views.py
git commit -m "feat(progetti): latest-state views (scopes/commitments/payment_schedules)"
```

---

## Task 7: `v_commitment_status` view (overrun + residuo)

**Files:**
- Create: `core/bq/views/v_commitment_status.sql`
- Modify: `tests/test_progetti_views.py`

- [ ] **Step 1: Append test**

```python
# tests/test_progetti_views.py (append)
def test_commitment_status_view_exists():
    p = VIEWS / "v_commitment_status.sql"
    assert p.exists()
    sql = p.read_text()
    assert "importo_fatturato_cum_eur" in sql
    assert "delta_overrun_eur" in sql
    assert "stato_overrun" in sql
```

- [ ] **Step 2: Run — verify fail**

Expected: FAIL.

- [ ] **Step 3: Write view**

```sql
-- core/bq/views/v_commitment_status.sql
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_commitment_status` AS
WITH commitments AS (
  SELECT * FROM `hotelops-suite.hotelops.v_progetto_commitments_current`
),
fatturato AS (
  SELECT
    il.commitment_id,
    SUM(mc.imp_dare - mc.imp_avere) AS importo_fatturato_cum_eur
  FROM `hotelops-suite.hotelops.f_progetto_invoice_link` il
  JOIN `hotelops-suite.hotelops.f_movimenti_contabili` mc
    ON mc.row_hash = il.movimento_row_hash
  GROUP BY il.commitment_id
),
pagato AS (
  SELECT
    ps.commitment_id,
    SUM(ps.importo_eur) AS importo_pagato_eur
  FROM `hotelops-suite.hotelops.v_progetto_payment_schedules_current` ps
  WHERE ps.stato = 'PAGATA'
  GROUP BY ps.commitment_id
)
SELECT
  c.commitment_id,
  c.progetto_id,
  c.fornitore_denorm,
  c.societa_pagante_id,
  c.tipo_spesa,
  c.importo_impegnato_eur,
  COALESCE(f.importo_fatturato_cum_eur, 0) AS importo_fatturato_cum_eur,
  COALESCE(p.importo_pagato_eur, 0) AS importo_pagato_eur,
  GREATEST(COALESCE(f.importo_fatturato_cum_eur, 0) - c.importo_impegnato_eur, 0) AS delta_overrun_eur,
  c.importo_impegnato_eur - COALESCE(f.importo_fatturato_cum_eur, 0) AS residuo_eur,
  CASE
    WHEN COALESCE(f.importo_fatturato_cum_eur, 0) > c.importo_impegnato_eur * 1.10 THEN 'ALERT'
    WHEN COALESCE(f.importo_fatturato_cum_eur, 0) > c.importo_impegnato_eur * 1.05 THEN 'WARN'
    ELSE 'OK'
  END AS stato_overrun,
  c.stato AS commitment_stato
FROM commitments c
LEFT JOIN fatturato f USING (commitment_id)
LEFT JOIN pagato p USING (commitment_id);
```

Note: `f_movimenti_contabili.row_hash` must exist. Verify column name — if named differently (e.g., `hash_riga`), adjust.

- [ ] **Step 4: Verify `f_movimenti_contabili` hash column name**

```bash
bq show --schema --format=prettyjson hotelops-suite:hotelops.f_movimenti_contabili | grep -i hash
```

If column is not `row_hash`, update the SQL to match.

- [ ] **Step 5: Run test + apply view**

Run: `pytest tests/test_progetti_views.py::test_commitment_status_view_exists -v`
Expected: PASS.

Apply: `bq query --use_legacy_sql=false < core/bq/views/v_commitment_status.sql`

- [ ] **Step 6: Commit**

```bash
git add core/bq/views/v_commitment_status.sql tests/test_progetti_views.py
git commit -m "feat(progetti): v_commitment_status (overrun thresholds 5%/10%)"
```

---

## Task 8: `v_progetto_overview` view (budget cascade + semaforo)

**Files:**
- Create: `core/bq/views/v_progetto_overview.sql`
- Modify: `tests/test_progetti_views.py`

- [ ] **Step 1: Append test**

```python
def test_progetto_overview_view():
    p = VIEWS / "v_progetto_overview.sql"
    assert p.exists()
    sql = p.read_text()
    for col in [
        "budget_cap_eur",
        "sum_stimato_eur",
        "sum_impegnato_eur",
        "sum_fatturato_eur",
        "pct_committed",
        "stato_budget",
    ]:
        assert col in sql
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Write view**

```sql
-- core/bq/views/v_progetto_overview.sql
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_progetto_overview` AS
WITH scopes AS (
  SELECT progetto_id, SUM(importo_stimato_eur) AS sum_stimato_eur
  FROM `hotelops-suite.hotelops.v_progetto_scopes_current`
  WHERE stato != 'CHIUSO'
  GROUP BY progetto_id
),
commitments AS (
  SELECT
    progetto_id,
    SUM(importo_impegnato_eur) AS sum_impegnato_eur
  FROM `hotelops-suite.hotelops.v_progetto_commitments_current`
  WHERE stato IN ('FIRMATO', 'IN_CORSO', 'CHIUSO')
  GROUP BY progetto_id
),
fatturato AS (
  SELECT
    c.progetto_id,
    SUM(cs.importo_fatturato_cum_eur) AS sum_fatturato_eur,
    SUM(cs.importo_pagato_eur) AS sum_pagato_eur
  FROM `hotelops-suite.hotelops.v_commitment_status` cs
  JOIN `hotelops-suite.hotelops.v_progetto_commitments_current` c USING (commitment_id)
  GROUP BY c.progetto_id
)
SELECT
  p.progetto_id,
  p.nome,
  p.societa_beneficiaria_id,
  p.business_unit_id,
  p.stato AS progetto_stato,
  p.budget_cap_eur,
  COALESCE(s.sum_stimato_eur, 0) AS sum_stimato_eur,
  COALESCE(cm.sum_impegnato_eur, 0) AS sum_impegnato_eur,
  COALESCE(f.sum_fatturato_eur, 0) AS sum_fatturato_eur,
  COALESCE(f.sum_pagato_eur, 0) AS sum_pagato_eur,
  SAFE_DIVIDE(COALESCE(cm.sum_impegnato_eur, 0), p.budget_cap_eur) AS pct_committed,
  p.budget_cap_eur - COALESCE(cm.sum_impegnato_eur, 0) - COALESCE(s.sum_stimato_eur, 0) AS buffer_residuo_eur,
  CASE
    WHEN COALESCE(cm.sum_impegnato_eur, 0) > p.budget_cap_eur THEN 'SFORATO'
    WHEN COALESCE(cm.sum_impegnato_eur, 0) + COALESCE(s.sum_stimato_eur, 0) > p.budget_cap_eur * 0.95 THEN 'NEAR_CAP'
    ELSE 'OK'
  END AS stato_budget
FROM `hotelops-suite.hotelops.d_progetti` p
LEFT JOIN scopes s USING (progetto_id)
LEFT JOIN commitments cm USING (progetto_id)
LEFT JOIN fatturato f USING (progetto_id);
```

- [ ] **Step 4: Test + apply**

```bash
pytest tests/test_progetti_views.py::test_progetto_overview_view -v
bq query --use_legacy_sql=false < core/bq/views/v_progetto_overview.sql
```

- [ ] **Step 5: Commit**

```bash
git add core/bq/views/v_progetto_overview.sql tests/test_progetti_views.py
git commit -m "feat(progetti): v_progetto_overview (budget cascade + stato_budget)"
```

---

## Task 9: `v_progetto_timeline` view (UNION ALL event log)

**Files:**
- Create: `core/bq/views/v_progetto_timeline.sql`
- Modify: `tests/test_progetti_views.py`

- [ ] **Step 1: Append test**

```python
def test_progetto_timeline_view():
    sql = (VIEWS / "v_progetto_timeline.sql").read_text()
    assert "UNION ALL" in sql
    for evt in ["SCOPE_STATO", "COMMITMENT_STATO", "FATTURA", "RATA_STATO"]:
        assert evt in sql
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Write view**

```sql
-- core/bq/views/v_progetto_timeline.sql
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_progetto_timeline` AS
SELECT
  progetto_id,
  data_stato AS ts_evento,
  'SCOPE_STATO' AS tipo_evento,
  scope_id AS entita_id,
  stato AS descrizione,
  CAST(importo_stimato_eur AS FLOAT64) AS importo_eur,
  categoria AS extra
FROM `hotelops-suite.hotelops.f_progetto_scopes`

UNION ALL

SELECT
  progetto_id,
  data_stato AS ts_evento,
  'COMMITMENT_STATO' AS tipo_evento,
  commitment_id AS entita_id,
  CONCAT(stato, ' | ', fornitore_denorm) AS descrizione,
  CAST(importo_impegnato_eur AS FLOAT64) AS importo_eur,
  societa_pagante_id AS extra
FROM `hotelops-suite.hotelops.f_progetto_commitments`

UNION ALL

SELECT
  c.progetto_id,
  CAST(mc.data_registrazione AS TIMESTAMP) AS ts_evento,
  'FATTURA' AS tipo_evento,
  il.link_id AS entita_id,
  CONCAT('Fattura ', mc.descrizione) AS descrizione,
  (mc.imp_dare - mc.imp_avere) AS importo_eur,
  c.fornitore_denorm AS extra
FROM `hotelops-suite.hotelops.f_progetto_invoice_link` il
JOIN `hotelops-suite.hotelops.v_progetto_commitments_current` c USING (commitment_id)
JOIN `hotelops-suite.hotelops.f_movimenti_contabili` mc ON mc.row_hash = il.movimento_row_hash

UNION ALL

SELECT
  c.progetto_id,
  ps.data_stato AS ts_evento,
  'RATA_STATO' AS tipo_evento,
  ps.rate_id AS entita_id,
  CONCAT('Rata ', CAST(ps.seq AS STRING), ' ', ps.stato) AS descrizione,
  CAST(ps.importo_eur AS FLOAT64) AS importo_eur,
  CAST(ps.data_prevista AS STRING) AS extra
FROM `hotelops-suite.hotelops.f_progetto_payment_schedules` ps
JOIN `hotelops-suite.hotelops.v_progetto_commitments_current` c USING (commitment_id);
```

- [ ] **Step 4: Test + apply**

```bash
pytest tests/test_progetti_views.py::test_progetto_timeline_view -v
bq query --use_legacy_sql=false < core/bq/views/v_progetto_timeline.sql
```

- [ ] **Step 5: Commit**

```bash
git add core/bq/views/v_progetto_timeline.sql tests/test_progetti_views.py
git commit -m "feat(progetti): v_progetto_timeline (UNION ALL event log)"
```

---

## Task 10: Canonicals migration — INVESTIMENTI_CAPEX voce + progetto_id column + stato_censimento

**Files:**
- Modify: `core/bq/dimensioni/d_voci_piano_finanziario.csv`
- Create: `core/bq/ddl/migrations/2026-04-21-f_piano_finanziario_input-progetto_id.sql`
- Create: `core/bq/ddl/migrations/2026-04-21-d_anagrafica_fornitori-stato_censimento.sql`
- Create: `tests/test_progetti_canonicals.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_progetti_canonicals.py
import csv
from pathlib import Path


def test_voce_investimenti_capex_exists():
    rows = list(csv.DictReader(open("core/bq/dimensioni/d_voci_piano_finanziario.csv")))
    voci_ids = [r["voce_id"] for r in rows]
    assert "INVESTIMENTI_CAPEX" in voci_ids


def test_voce_investimenti_capex_is_manuale():
    rows = list(csv.DictReader(open("core/bq/dimensioni/d_voci_piano_finanziario.csv")))
    row = next(r for r in rows if r["voce_id"] == "INVESTIMENTI_CAPEX")
    assert row["fonte"] == "MANUALE"
    assert row["direzione"] == "USCITA"


def test_migration_files_exist():
    for p in [
        "core/bq/ddl/migrations/2026-04-21-f_piano_finanziario_input-progetto_id.sql",
        "core/bq/ddl/migrations/2026-04-21-d_anagrafica_fornitori-stato_censimento.sql",
    ]:
        assert Path(p).exists()
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Add CSV row**

Open `core/bq/dimensioni/d_voci_piano_finanziario.csv`. Check existing headers. Append:

```csv
INVESTIMENTI_CAPEX,Investimenti CAPEX,USCITA,MANUALE,,,Investimenti capex progetti/cantiere
```

Adjust column order to match existing CSV header. If there's a `cod_conto_pattern` or `banca_tipo_pat` column, leave empty.

- [ ] **Step 4: Write migration SQL**

```sql
-- core/bq/ddl/migrations/2026-04-21-f_piano_finanziario_input-progetto_id.sql
ALTER TABLE `hotelops-suite.hotelops.f_piano_finanziario_input`
  ADD COLUMN IF NOT EXISTS progetto_id STRING;
```

```sql
-- core/bq/ddl/migrations/2026-04-21-d_anagrafica_fornitori-stato_censimento.sql
ALTER TABLE `hotelops-suite.hotelops.d_anagrafica_fornitori`
  ADD COLUMN IF NOT EXISTS stato_censimento STRING;

UPDATE `hotelops-suite.hotelops.d_anagrafica_fornitori`
SET stato_censimento = 'CENSITO'
WHERE stato_censimento IS NULL;
```

- [ ] **Step 5: Run test + apply migrations + reload voci**

```bash
pytest tests/test_progetti_canonicals.py -v

bq query --use_legacy_sql=false < core/bq/ddl/migrations/2026-04-21-f_piano_finanziario_input-progetto_id.sql
bq query --use_legacy_sql=false < core/bq/ddl/migrations/2026-04-21-d_anagrafica_fornitori-stato_censimento.sql

python -m core.bq.load.load_voci_piano_finanziario
```

Verify: `bq query --use_legacy_sql=false "SELECT voce_id FROM hotelops-suite.hotelops.d_voci_piano_finanziario WHERE voce_id='INVESTIMENTI_CAPEX'"` → 1 row.

- [ ] **Step 6: Commit**

```bash
git add core/bq/dimensioni/d_voci_piano_finanziario.csv core/bq/ddl/migrations/ tests/test_progetti_canonicals.py
git commit -m "feat(canonicals): INVESTIMENTI_CAPEX voce + progetto_id col + stato_censimento"
```

---

## Task 11: Seed HPAN25PIANO1 — `d_progetti` + 28 ScopePackages

**Files:**
- Create: `progetti/seeds/__init__.py`
- Create: `progetti/seeds/hpan25piano1.py`
- Create: `tests/test_progetti_seed.py`

- [ ] **Step 1: Write failing smoke**

```python
# tests/test_progetti_seed.py
from progetti.seeds.hpan25piano1 import PROJECT, SCOPES


def test_project_fixture():
    assert PROJECT.progetto_id == "HPAN25PIANO1"
    assert PROJECT.budget_cap_eur == 1_200_000


def test_scopes_count_matches_walkthrough():
    # Walkthrough lists 28 rows (25 vendor + 3 no-vendor orfani + splits)
    assert len(SCOPES) >= 25
    assert all(s.progetto_id == "HPAN25PIANO1" for s in SCOPES)


def test_categoria_coverage():
    cats = {s.categoria for s in SCOPES}
    expected_subset = {"IMPIANTI", "PORTE", "ARREDI", "PM", "CONSULENZE"}
    assert expected_subset.issubset(cats)
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Write seed**

```python
# progetti/seeds/hpan25piano1.py
"""Seed fixtures for HPAN25PIANO1 — Camere Primo Piano Hotel Panorama.

Source: docs/progetti/HPAN25PIANO1-walkthrough.md (28 vendor rows, 4 buckets).
"""
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from progetti.models import Project, ScopePackage

_NOW = datetime(2026, 4, 21, 12, 0)


def _sp(codice: str, descr: str, cat: str, stima: int | Decimal, stato: str = "IDENTIFICATO", note: str | None = None) -> ScopePackage:
    return ScopePackage(
        scope_id=f"SP-HPAN25-{codice}",
        progetto_id="HPAN25PIANO1",
        codice=codice,
        descrizione=descr,
        categoria=cat,
        importo_stimato_eur=Decimal(str(stima)),
        stato=stato,
        data_stato=_NOW,
        note=note,
    )


PROJECT = Project(
    progetto_id="HPAN25PIANO1",
    nome="Camere Primo Piano - Hotel Panorama",
    societa_beneficiaria_id="INTUR",
    business_unit_id="HOTEL",
    struttura="Hotel Panorama",
    data_inizio=date(2026, 2, 1),
    data_fine_prevista=date(2026, 5, 31),
    budget_cap_eur=Decimal("1200000"),
    stato="IN_CORSO",
    owner="Stefano Della Pietra Jr",
    direzione_lavori="Amalia Pisacane",
)


# Bucket (a) — Contratti firmati (5)
SCOPES_BUCKET_A = [
    _sp("STE-IMPIANTI", "STE — impiantistica elettrica camere 121-130", "IMPIANTI", 85000, "IMPEGNATO", "Contratto firmato 27/02/2026"),
    _sp("SANTELIA-MURARIE", "Santelia Costruzioni — opere murarie", "OPERE_MURARIE", 180000, "IMPEGNATO", "Contratto firmato 27/02/2026"),
    _sp("DIERRE-PORTE-STD", "Dierre — porte standard camere (ordine n.864)", "PORTE", 42000, "IMPEGNATO"),
    _sp("HOSPITALITY-PM-FEE", "Hospitality Project (Pignocchi+Faggioli) — PM fee", "PM", 48000, "IMPEGNATO", "OPEX — pagata da ORTI"),
    _sp("PISACANE-DL", "Amalia Pisacane — direzione lavori", "CONSULENZE", 25000, "IMPEGNATO", "Overrun risk — fatturato oltre contratto"),
]

# Bucket (b) — Preventivi accettati / in firma (7)
SCOPES_BUCKET_B = [
    _sp("NINNI-INTERIOR", "Studio Ninni (Anna Capone) — interior design", "PROGETTAZIONE", 35000, "PREVENTIVATO"),
    _sp("ATELIER-ARREDI", "Atelier Hospitality — arredi camere", "ARREDI", 120000, "PREVENTIVATO"),
    _sp("GEBERIT-SANITARI", "Geberit — sanitari + scarichi", "IMPIANTI", 28000, "PREVENTIVATO"),
    _sp("FRATTINI-RUBINETTERIA", "Frattini — rubinetteria", "IMPIANTI", 18000, "PREVENTIVATO"),
    _sp("ROCKY-PAVIMENTI", "Rocky — pavimenti camere", "FINITURE", 32000, "PREVENTIVATO"),
    _sp("COMODA-LETTI", "Comoda — letti su misura", "ARREDI", 45000, "PREVENTIVATO"),
    _sp("AMCN-FORNITURE", "AMCN — forniture varie", "ALTRO", 60000, "PREVENTIVATO", "Overrun +37K rispetto stima iniziale"),
]

# Bucket (c) — Preventivi ricevuti non accettati (8)
SCOPES_BUCKET_C = [
    _sp("CSC-PORTE-REI", "CSC — porte REI tagliafuoco corridoio", "PORTE", 28000, "PREVENTIVATO"),
    _sp("SICIGNANO-MAT", "Sicigniano — fornitura materiale piastrelle", "FINITURE", 22000, "PREVENTIVATO"),
    _sp("PIASTRELLISTA-POSA", "Piastrellista — posa piastrelle bagni", "OPERE_MURARIE", 18000, "PREVENTIVATO"),
    _sp("METAL2000", "Metal 2000 — carpenteria metallica (scope TBD)", "ALTRO", 15000, "IDENTIFICATO"),
    _sp("TV-CAPONE", "Capone (TV) — dotazione televisori", "ARREDI", 12000, "PREVENTIVATO", "Canonical name ambiguo"),
    _sp("MINIBAR-FORN", "Fornitore minibar camere", "ARREDI", 8000, "IDENTIFICATO"),
    _sp("TENDAGGI", "Tendaggi + oscuranti", "FINITURE", 14000, "IDENTIFICATO"),
    _sp("DOMOTICA", "Domotica integrata (Smart home)", "IMPIANTI", 35000, "IDENTIFICATO"),
]

# Bucket (d) — Implied / TBD (8) + orfani
SCOPES_BUCKET_D = [
    _sp("FACCHINAGGIO", "Facchinaggio + smaltimento mobili vecchi", "ALTRO", 8000, "IDENTIFICATO"),
    _sp("PULIZIE-CANTIERE", "Pulizie fine cantiere", "ALTRO", 5000, "IDENTIFICATO"),
    _sp("IVA-ATTIVA", "IVA attiva (cost residuo)", "ALTRO", 45000, "IDENTIFICATO", "Da affinare con Esolver"),
    _sp("CONTINGENCY", "Contingency buffer 5%", "ALTRO", 60000, "IDENTIFICATO"),
    _sp("NO-VENDOR-IMPIANTI-EXTRA", "Impianti extra non preventivati (orfano)", "IMPIANTI", 15000, "IDENTIFICATO", "Nessun vendor identificato"),
    _sp("NO-VENDOR-FINITURE-EXTRA", "Finiture extra non preventivate (orfano)", "FINITURE", 12000, "IDENTIFICATO"),
    _sp("NO-VENDOR-ARREDI-EXTRA", "Arredi extra non preventivati (orfano)", "ARREDI", 18000, "IDENTIFICATO"),
    _sp("NO-VENDOR-IMPREVISTI", "Imprevisti generici (orfano)", "ALTRO", 25000, "IDENTIFICATO"),
]

SCOPES = SCOPES_BUCKET_A + SCOPES_BUCKET_B + SCOPES_BUCKET_C + SCOPES_BUCKET_D
```

- [ ] **Step 4: Run test — verify pass**

Run: `pytest tests/test_progetti_seed.py -v`
Expected: 3/3 PASS.

- [ ] **Step 5: Commit**

```bash
git add progetti/seeds/ tests/test_progetti_seed.py
git commit -m "feat(progetti): seed HPAN25PIANO1 — Project + 28 ScopePackages"
```

---

## Task 12: Seed Commitments (bucket a) + ScopeCommitmentLink

**Files:**
- Modify: `progetti/seeds/hpan25piano1.py`
- Modify: `tests/test_progetti_seed.py`

- [ ] **Step 1: Append test**

```python
# tests/test_progetti_seed.py (append)
from progetti.seeds.hpan25piano1 import COMMITMENTS, SCOPE_COMMITMENT_LINKS


def test_commitments_bucket_a():
    assert len(COMMITMENTS) == 5
    by_fornitore = {c.fornitore_denorm for c in COMMITMENTS}
    for expected in ["STE", "Santelia", "Dierre", "Hospitality Project", "Pisacane"]:
        assert any(expected.lower() in f.lower() for f in by_fornitore)


def test_capex_goes_to_intur():
    for c in COMMITMENTS:
        if c.tipo_spesa == "CAPEX":
            assert c.societa_pagante_id == "INTUR", f"{c.descrizione} capex but not INTUR"


def test_hospitality_is_opex_orti():
    hp = next(c for c in COMMITMENTS if "Hospitality" in c.descrizione)
    assert hp.tipo_spesa == "OPEX"
    assert hp.societa_pagante_id == "ORTI"


def test_scope_commitment_links_quota_sums_to_impegnato():
    by_commitment: dict = {}
    for lk in SCOPE_COMMITMENT_LINKS:
        by_commitment.setdefault(lk.commitment_id, Decimal(0))
        by_commitment[lk.commitment_id] += lk.quota_importo_eur
    for c in COMMITMENTS:
        total = by_commitment.get(c.commitment_id, Decimal(0))
        assert total == c.importo_impegnato_eur, (
            f"{c.commitment_id}: quotas sum {total} != impegnato {c.importo_impegnato_eur}"
        )
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Append to seed**

```python
# progetti/seeds/hpan25piano1.py (append)
from decimal import Decimal

from progetti.models import Commitment, ScopeCommitmentLink

_FIRMA_27_02 = datetime(2026, 2, 27, 15, 0)


def _c(cid: str, descr: str, forn: str, soc: str, tipo: str, imp: int | Decimal, voce: str, stato: str = "FIRMATO", data=_FIRMA_27_02) -> Commitment:
    return Commitment(
        commitment_id=cid,
        progetto_id="HPAN25PIANO1",
        descrizione=descr,
        fornitore_id=None,
        fornitore_denorm=forn,
        societa_pagante_id=soc,
        tipo_spesa=tipo,
        importo_impegnato_eur=Decimal(str(imp)),
        stato=stato,
        data_stato=data,
        from_document_id=None,
        voce_pf_target=voce,
        note=None,
    )


COMMITMENTS = [
    _c("C-STE", "Contratto STE impianti", "STE Srl", "INTUR", "CAPEX", 85000, "INVESTIMENTI_CAPEX"),
    _c("C-SANTELIA", "Contratto Santelia opere murarie", "Santelia Costruzioni", "INTUR", "CAPEX", 180000, "INVESTIMENTI_CAPEX"),
    _c("C-DIERRE", "Ordine Dierre n.864 porte std", "Dierre Spa", "INTUR", "CAPEX", 42000, "INVESTIMENTI_CAPEX"),
    _c("C-HOSPITALITY", "Contratto Hospitality Project PM fee", "Hospitality Project (Pignocchi+Faggioli)", "ORTI", "OPEX", 48000, "CONSULENZE"),
    _c("C-PISACANE", "Contratto Pisacane DL", "Amalia Pisacane", "INTUR", "OPEX", 25000, "CONSULENZE"),
]


def _lk(scope_id: str, commitment_id: str, quota: int | Decimal) -> ScopeCommitmentLink:
    return ScopeCommitmentLink(
        link_id=f"LK-{commitment_id}-{scope_id}",
        scope_package_id=scope_id,
        commitment_id=commitment_id,
        quota_importo_eur=Decimal(str(quota)),
    )


SCOPE_COMMITMENT_LINKS = [
    _lk("SP-HPAN25-STE-IMPIANTI", "C-STE", 85000),
    _lk("SP-HPAN25-SANTELIA-MURARIE", "C-SANTELIA", 180000),
    _lk("SP-HPAN25-DIERRE-PORTE-STD", "C-DIERRE", 42000),
    _lk("SP-HPAN25-HOSPITALITY-PM-FEE", "C-HOSPITALITY", 48000),
    _lk("SP-HPAN25-PISACANE-DL", "C-PISACANE", 25000),
]
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/test_progetti_seed.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add progetti/seeds/hpan25piano1.py tests/test_progetti_seed.py
git commit -m "feat(progetti): seed commitments (bucket a) + scope-commitment links"
```

---

## Task 13: Seed PaymentSchedules (30/40/30 per commitment)

**Files:**
- Modify: `progetti/seeds/hpan25piano1.py`
- Modify: `tests/test_progetti_seed.py`

- [ ] **Step 1: Append test**

```python
# tests/test_progetti_seed.py (append)
from progetti.seeds.hpan25piano1 import PAYMENT_SCHEDULES


def test_each_commitment_has_3_rates():
    from collections import Counter
    c = Counter(r.commitment_id for r in PAYMENT_SCHEDULES)
    for com in COMMITMENTS:
        assert c[com.commitment_id] == 3, f"{com.commitment_id} has {c[com.commitment_id]} rates"


def test_rates_sum_to_impegnato():
    by_c: dict = {}
    for r in PAYMENT_SCHEDULES:
        by_c.setdefault(r.commitment_id, Decimal(0))
        by_c[r.commitment_id] += r.importo_eur
    for c in COMMITMENTS:
        assert by_c[c.commitment_id] == c.importo_impegnato_eur


def test_rate_seq_monotonic():
    from collections import defaultdict
    by_c: dict = defaultdict(list)
    for r in PAYMENT_SCHEDULES:
        by_c[r.commitment_id].append(r.seq)
    for cid, seqs in by_c.items():
        assert sorted(seqs) == [1, 2, 3]
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Append seed**

```python
# progetti/seeds/hpan25piano1.py (append)
from progetti.models import PaymentSchedule

_QUOTE = [(1, Decimal("0.30"), "Acconto 30% alla firma"),
          (2, Decimal("0.40"), "SAL 40%"),
          (3, Decimal("0.30"), "Saldo 30% a fine lavori")]

_FASE_DATES = {
    "C-STE":         [date(2026, 3, 15), date(2026, 4, 15), date(2026, 5, 20)],
    "C-SANTELIA":    [date(2026, 3, 10), date(2026, 4, 20), date(2026, 5, 25)],
    "C-DIERRE":      [date(2026, 3, 20), date(2026, 4, 25), date(2026, 5, 20)],
    "C-HOSPITALITY": [date(2026, 2, 28), date(2026, 4, 1),  date(2026, 5, 31)],
    "C-PISACANE":    [date(2026, 3, 1),  date(2026, 4, 15), date(2026, 5, 31)],
}


def _rates_for(c: Commitment) -> list[PaymentSchedule]:
    out = []
    dates = _FASE_DATES[c.commitment_id]
    for (seq, quota, descr), d in zip(_QUOTE, dates):
        out.append(
            PaymentSchedule(
                rate_id=f"R-{c.commitment_id}-{seq}",
                commitment_id=c.commitment_id,
                seq=seq,
                data_prevista=d,
                importo_eur=(c.importo_impegnato_eur * quota).quantize(Decimal("0.01")),
                descrizione=descr,
                stato="PIANIFICATA",
                data_stato=_NOW,
            )
        )
    # Fix rounding residual on seq=3
    total = sum(r.importo_eur for r in out)
    if total != c.importo_impegnato_eur:
        diff = c.importo_impegnato_eur - total
        out[-1] = out[-1].model_copy(update={"importo_eur": out[-1].importo_eur + diff})
    return out


PAYMENT_SCHEDULES = [r for c in COMMITMENTS for r in _rates_for(c)]
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/test_progetti_seed.py -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add progetti/seeds/hpan25piano1.py tests/test_progetti_seed.py
git commit -m "feat(progetti): seed payment schedules (30/40/30) for 5 commitments"
```

---

## Task 14: Seed Documents (6 preventivi) + loader to BQ

**Files:**
- Modify: `progetti/seeds/hpan25piano1.py`
- Create: `progetti/seeds/loader.py`
- Modify: `tests/test_progetti_seed.py`

- [ ] **Step 1: Append test**

```python
# tests/test_progetti_seed.py (append)
from progetti.seeds.hpan25piano1 import DOCUMENTS


def test_six_preventivi_seed():
    assert len(DOCUMENTS) == 6
    assert all(d.tipo == "PREVENTIVO" for d in DOCUMENTS)


def test_documents_unique_md5():
    hashes = [d.file_hash_md5 for d in DOCUMENTS]
    assert len(hashes) == len(set(hashes))
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Append seed**

```python
# progetti/seeds/hpan25piano1.py (append)
import hashlib

from progetti.models import Document


def _doc(scope_id: str, forn: str, num: str, imp: int, drive_subpath: str, stato_prev: str = "ACCETTATO") -> Document:
    hid = hashlib.md5(f"{scope_id}|{num}|{forn}".encode()).hexdigest()
    return Document(
        document_id=f"DOC-{hid[:12]}",
        scope_package_id=scope_id,
        tipo="PREVENTIVO",
        fornitore_id=None,
        fornitore_denorm=forn,
        numero_documento=num,
        data_documento=date(2026, 2, 15),
        importo_eur=Decimal(str(imp)),
        stato_preventivo=stato_prev,
        drive_path=f"investimenti2026/HPAN25PIANO1/preventivi/{drive_subpath}",
        file_hash_md5=hid,
        estratto_confidence=1.0,
        estratto_reviewed=True,
        note="Seed manuale, non estratto da LLM",
    )


DOCUMENTS = [
    _doc("SP-HPAN25-STE-IMPIANTI", "STE Srl", "P-STE-2026-01", 85000, "STE_impianti.pdf"),
    _doc("SP-HPAN25-SANTELIA-MURARIE", "Santelia Costruzioni", "P-SAN-2026-01", 180000, "Santelia_murarie.pdf"),
    _doc("SP-HPAN25-DIERRE-PORTE-STD", "Dierre Spa", "864", 42000, "Dierre_n864.pdf"),
    _doc("SP-HPAN25-HOSPITALITY-PM-FEE", "Hospitality Project (Pignocchi+Faggioli)", "P-HP-2026-01", 48000, "HospitalityProject_PM.pdf"),
    _doc("SP-HPAN25-PISACANE-DL", "Amalia Pisacane", "P-PIS-2026-01", 25000, "Pisacane_DL.pdf"),
    _doc("SP-HPAN25-ATELIER-ARREDI", "Atelier Hospitality", "P-ATL-2026-01", 120000, "Atelier_arredi.pdf", stato_prev="RICEVUTO"),
]
```

- [ ] **Step 4: Write loader module**

```python
# progetti/seeds/loader.py
"""Load HPAN25PIANO1 seed fixtures to BigQuery."""
from __future__ import annotations

from google.cloud import bigquery

from core.bq.client import get_client
from progetti.seeds.hpan25piano1 import (
    COMMITMENTS,
    DOCUMENTS,
    PAYMENT_SCHEDULES,
    PROJECT,
    SCOPE_COMMITMENT_LINKS,
    SCOPES,
)

PROJECT_REF = "hotelops-suite.hotelops"


def _insert(client: bigquery.Client, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    errors = client.insert_rows_json(f"{PROJECT_REF}.{table}", rows)
    if errors:
        raise RuntimeError(f"{table}: {errors}")


def load_all() -> None:
    client = get_client()
    _insert(client, "d_progetti", [_pd_to_dict(PROJECT)])
    _insert(client, "f_progetto_scopes", [_pd_to_dict(s) for s in SCOPES])
    _insert(client, "f_progetto_commitments", [_pd_to_dict(c) for c in COMMITMENTS])
    _insert(client, "f_progetto_scope_commitment_link", [_pd_to_dict(l) for l in SCOPE_COMMITMENT_LINKS])
    _insert(client, "f_progetto_payment_schedules", [_pd_to_dict(r) for r in PAYMENT_SCHEDULES])
    _insert(client, "f_progetto_documenti", [_pd_to_dict(d) for d in DOCUMENTS])


def _pd_to_dict(m) -> dict:
    d = m.model_dump(mode="json")
    # Decimal → str (BQ NUMERIC accepts string)
    from decimal import Decimal as _D
    for k, v in list(d.items()):
        if isinstance(v, _D):
            d[k] = str(v)
    return d


if __name__ == "__main__":
    load_all()
    print("Seed loaded.")
```

- [ ] **Step 5: Test + load**

```bash
pytest tests/test_progetti_seed.py -v
python -m progetti.seeds.loader
```

Verify: `bq query --use_legacy_sql=false "SELECT COUNT(*) FROM hotelops-suite.hotelops.v_progetto_commitments_current WHERE progetto_id='HPAN25PIANO1'"` → 5.

- [ ] **Step 6: Commit**

```bash
git add progetti/seeds/ tests/test_progetti_seed.py
git commit -m "feat(progetti): seed documents + loader to BQ (HPAN25PIANO1 live)"
```

---

## Task 15: Fuzzy supplier matcher (rapidfuzz)

**Files:**
- Modify: `progetti/fuzzy.py`
- Create: `tests/test_projects_fuzzy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_projects_fuzzy.py
from progetti.fuzzy import MatchAction, match_fornitore


def test_auto_link_on_exact():
    known = ["STE Srl", "Santelia Costruzioni", "Dierre Spa"]
    r = match_fornitore("STE Srl", known)
    assert r.action == MatchAction.AUTO_LINK
    assert r.score >= 0.9


def test_suggest_on_partial():
    known = ["Amalia Pisacane", "STE Srl"]
    r = match_fornitore("Amalisa Pisacane", known)  # typo
    assert r.action == MatchAction.SUGGEST
    assert 0.7 <= r.score < 0.9
    assert r.best_match == "Amalia Pisacane"


def test_candidate_on_miss():
    known = ["STE Srl"]
    r = match_fornitore("Totally New Vendor Srl", known)
    assert r.action == MatchAction.CANDIDATE
    assert r.score < 0.7
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement**

```python
# progetti/fuzzy.py
from dataclasses import dataclass
from enum import Enum

from rapidfuzz import fuzz, process


class MatchAction(str, Enum):
    AUTO_LINK = "AUTO_LINK"
    SUGGEST = "SUGGEST"
    CANDIDATE = "CANDIDATE"


@dataclass
class MatchResult:
    action: MatchAction
    score: float
    best_match: str | None
    candidates: list[tuple[str, float]]


_AUTO = 0.9
_SUGGEST = 0.7


def match_fornitore(query: str, known: list[str], top_k: int = 5) -> MatchResult:
    if not known:
        return MatchResult(MatchAction.CANDIDATE, 0.0, None, [])
    results = process.extract(query, known, scorer=fuzz.token_set_ratio, limit=top_k)
    # rapidfuzz returns (match, score_0_100, idx)
    top_name, top_score, _ = results[0]
    norm = top_score / 100.0
    if norm >= _AUTO:
        action = MatchAction.AUTO_LINK
    elif norm >= _SUGGEST:
        action = MatchAction.SUGGEST
    else:
        action = MatchAction.CANDIDATE
    return MatchResult(
        action=action,
        score=norm,
        best_match=top_name if action != MatchAction.CANDIDATE else None,
        candidates=[(n, s / 100.0) for n, s, _ in results],
    )
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/test_projects_fuzzy.py -v`
Expected: 3/3 PASS.

- [ ] **Step 5: Commit**

```bash
git add progetti/fuzzy.py tests/test_projects_fuzzy.py
git commit -m "feat(progetti): fuzzy supplier matcher with AUTO/SUGGEST/CANDIDATE thresholds"
```

---

## Task 16: LLM extraction (Claude Haiku)

**Files:**
- Modify: `progetti/extract.py`
- Create: `tests/test_projects_extract.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_projects_extract.py
from unittest.mock import MagicMock, patch

from progetti.extract import ExtractedFields, extract_document_fields


def test_extract_returns_parsed_json():
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text='{"tipo":"PREVENTIVO","fornitore":"STE Srl","numero_doc":"P-42","data_doc":"2026-03-15","importo":85000,"descrizione":"Impianti","scope_hint":"IMPIANTI"}')]
    with patch("progetti.extract._client") as cli:
        cli.messages.create.return_value = fake_resp
        out = extract_document_fields(b"pdf-bytes", filename="STE.pdf")
    assert isinstance(out, ExtractedFields)
    assert out.fornitore == "STE Srl"
    assert out.importo == 85000


def test_extract_low_confidence_on_bad_json():
    fake_resp = MagicMock()
    fake_resp.content = [MagicMock(text="not json")]
    with patch("progetti.extract._client") as cli:
        cli.messages.create.return_value = fake_resp
        out = extract_document_fields(b"pdf", filename="x.pdf")
    assert out.confidence["_overall"] < 0.3
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement**

```python
# progetti/extract.py
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field

from anthropic import Anthropic

_MODEL = "claude-haiku-4-5-20251001"
_client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

_SYSTEM_PROMPT = """Sei un estrattore di metadati da documenti finanziari/cantiere (PDF preventivi, contratti, fatture).

Restituisci SOLO un oggetto JSON con questi campi (usa null se non presenti):
{
  "tipo": "PREVENTIVO" | "CONTRATTO" | "ORDINE" | "FATTURA" | "SAL" | "ALTRO",
  "fornitore": string (ragione sociale),
  "numero_doc": string,
  "data_doc": "YYYY-MM-DD",
  "importo": number (euro, IVA inclusa se indicata),
  "descrizione": string (breve, <200 char),
  "scope_hint": "OPERE_MURARIE" | "IMPIANTI" | "ARREDI" | "FINITURE" | "PORTE" | "CONSULENZE" | "PROGETTAZIONE" | "PM" | "ALTRO"
}

No markdown, no commenti, solo JSON puro."""


@dataclass
class ExtractedFields:
    tipo: str | None = None
    fornitore: str | None = None
    numero_doc: str | None = None
    data_doc: str | None = None
    importo: float | None = None
    descrizione: str | None = None
    scope_hint: str | None = None
    confidence: dict = field(default_factory=dict)
    raw_response: str = ""


def extract_document_fields(file_bytes: bytes, filename: str) -> ExtractedFields:
    b64 = base64.standard_b64encode(file_bytes).decode()
    msg = _client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
                {"type": "text", "text": f"Estrai metadati da {filename}."},
            ],
        }],
    )
    raw = msg.content[0].text if msg.content else ""
    try:
        parsed = json.loads(raw)
        conf = {k: 0.85 if parsed.get(k) else 0.0 for k in
                ("tipo", "fornitore", "numero_doc", "data_doc", "importo", "descrizione", "scope_hint")}
        conf["_overall"] = sum(conf.values()) / len(conf)
        return ExtractedFields(
            tipo=parsed.get("tipo"),
            fornitore=parsed.get("fornitore"),
            numero_doc=parsed.get("numero_doc"),
            data_doc=parsed.get("data_doc"),
            importo=parsed.get("importo"),
            descrizione=parsed.get("descrizione"),
            scope_hint=parsed.get("scope_hint"),
            confidence=conf,
            raw_response=raw,
        )
    except json.JSONDecodeError:
        return ExtractedFields(confidence={"_overall": 0.1}, raw_response=raw)
```

- [ ] **Step 4: Run — verify pass**

Run: `pytest tests/test_projects_extract.py -v`
Expected: 2/2 PASS.

- [ ] **Step 5: Commit**

```bash
git add progetti/extract.py tests/test_projects_extract.py
git commit -m "feat(progetti): LLM document extraction via Claude Haiku"
```

---

## Task 17: Forward-flow solver → `f_piano_finanziario_input`

**Files:**
- Modify: `progetti/forward_flow.py`
- Modify: `progetti/config.py`
- Create: `tests/test_projects_forward_flow.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_projects_forward_flow.py
from datetime import date
from decimal import Decimal

from progetti.forward_flow import (
    compute_forward_flow_rows,
    lookup_opex_voce,
)
from progetti.models import Commitment, PaymentSchedule


def _mkc(tipo: str, soc: str, voce: str = "INVESTIMENTI_CAPEX") -> Commitment:
    from datetime import datetime
    return Commitment(
        commitment_id="c1", progetto_id="HPAN25PIANO1",
        descrizione="x", fornitore_id=None, fornitore_denorm="X",
        societa_pagante_id=soc, tipo_spesa=tipo,
        importo_impegnato_eur=Decimal("100"), stato="FIRMATO",
        data_stato=datetime.now(), from_document_id=None,
        voce_pf_target=voce, note=None,
    )


def _mkr(seq: int, d: date, imp: int, stato: str = "PIANIFICATA") -> PaymentSchedule:
    from datetime import datetime
    return PaymentSchedule(
        rate_id=f"r{seq}", commitment_id="c1", seq=seq,
        data_prevista=d, importo_eur=Decimal(str(imp)),
        descrizione=f"r{seq}", stato=stato, data_stato=datetime.now(),
    )


def test_capex_intur_emits_investimenti_capex():
    c = _mkc("CAPEX", "INTUR")
    rates = [_mkr(1, date(2026, 3, 15), 30), _mkr(2, date(2026, 4, 15), 40)]
    rows = compute_forward_flow_rows(c, rates)
    assert len(rows) == 2
    assert all(r["voce_id"] == "INVESTIMENTI_CAPEX" for r in rows)
    assert all(r["societa_id"] == "INTUR" for r in rows)
    assert all(r["fonte"] == "PROGETTI" for r in rows)
    assert all(r["progetto_id"] == "HPAN25PIANO1" for r in rows)


def test_opex_orti_emits_consulenze():
    c = _mkc("OPEX", "ORTI", voce="CONSULENZE")
    rates = [_mkr(1, date(2026, 4, 1), 50)]
    rows = compute_forward_flow_rows(c, rates)
    assert rows[0]["voce_id"] == "CONSULENZE"
    assert rows[0]["societa_id"] == "ORTI"


def test_skip_non_pianificata_rates():
    c = _mkc("CAPEX", "INTUR")
    rates = [_mkr(1, date(2026, 3, 15), 30, stato="PAGATA")]
    rows = compute_forward_flow_rows(c, rates)
    assert rows == []


def test_lookup_opex_pm_maps_consulenze():
    assert lookup_opex_voce("PM") == "CONSULENZE"
    assert lookup_opex_voce("CONSULENZE") == "CONSULENZE"
    assert lookup_opex_voce("UNKNOWN") == "CONSULENZE"  # fallback
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement**

```python
# progetti/config.py
OPEX_CATEGORY_MAP: dict[str, str] = {
    "PM": "CONSULENZE",
    "CONSULENZE": "CONSULENZE",
    "PROGETTAZIONE": "CONSULENZE",
}
OPEX_FALLBACK_VOCE = "CONSULENZE"

CAPEX_DEFAULT_VOCE = "INVESTIMENTI_CAPEX"
FORWARD_FLOW_FONTE = "PROGETTI"
```

```python
# progetti/forward_flow.py
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable

from google.cloud import bigquery

from core.bq.client import get_client
from progetti.config import (
    CAPEX_DEFAULT_VOCE,
    FORWARD_FLOW_FONTE,
    OPEX_CATEGORY_MAP,
    OPEX_FALLBACK_VOCE,
)
from progetti.models import Commitment, PaymentSchedule

_PROJECT_REF = "hotelops-suite.hotelops"


def lookup_opex_voce(categoria: str) -> str:
    return OPEX_CATEGORY_MAP.get(categoria, OPEX_FALLBACK_VOCE)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def compute_forward_flow_rows(
    commitment: Commitment,
    rates: Iterable[PaymentSchedule],
) -> list[dict]:
    if commitment.stato not in ("FIRMATO", "IN_CORSO"):
        return []
    voce = commitment.voce_pf_target or (
        CAPEX_DEFAULT_VOCE if commitment.tipo_spesa == "CAPEX" else OPEX_FALLBACK_VOCE
    )
    out: list[dict] = []
    for r in rates:
        if r.stato != "PIANIFICATA":
            continue
        out.append({
            "societa_id": commitment.societa_pagante_id,
            "voce_id": voce,
            "mese": _month_start(r.data_prevista).isoformat(),
            "importo_eur": str(r.importo_eur),
            "fonte": FORWARD_FLOW_FONTE,
            "progetto_id": commitment.progetto_id,
            "descrizione": f"{commitment.descrizione} — rata {r.seq}",
        })
    return out


def apply_forward_flow(progetto_id: str, dry_run: bool = False) -> dict:
    """Compute forward-flow for a progetto and apply DELETE+INSERT to f_piano_finanziario_input.

    Returns summary dict {deleted, inserted, rows}.
    """
    client = get_client()
    # Fetch commitments + rates
    q = f"""
    SELECT c.commitment_id, c.progetto_id, c.descrizione,
           c.societa_pagante_id, c.tipo_spesa,
           c.importo_impegnato_eur, c.stato, c.voce_pf_target,
           c.fornitore_denorm, c.fornitore_id, c.from_document_id,
           c.data_stato, c.note,
           r.rate_id, r.seq, r.data_prevista, r.importo_eur, r.stato AS rata_stato,
           r.data_stato AS rata_data_stato, r.descrizione AS rata_descr
    FROM `{_PROJECT_REF}.v_progetto_commitments_current` c
    JOIN `{_PROJECT_REF}.v_progetto_payment_schedules_current` r USING (commitment_id)
    WHERE c.progetto_id = @pid AND c.stato IN ('FIRMATO', 'IN_CORSO')
      AND r.stato = 'PIANIFICATA'
    """
    job = client.query(
        q,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("pid", "STRING", progetto_id),
        ]),
    )
    rows_by_c: dict[str, tuple[Commitment, list[PaymentSchedule]]] = {}
    for r in job.result():
        if r["commitment_id"] not in rows_by_c:
            c = Commitment(
                commitment_id=r["commitment_id"], progetto_id=r["progetto_id"],
                descrizione=r["descrizione"],
                fornitore_id=r["fornitore_id"], fornitore_denorm=r["fornitore_denorm"],
                societa_pagante_id=r["societa_pagante_id"], tipo_spesa=r["tipo_spesa"],
                importo_impegnato_eur=Decimal(str(r["importo_impegnato_eur"])),
                stato=r["stato"], data_stato=r["data_stato"],
                from_document_id=r["from_document_id"],
                voce_pf_target=r["voce_pf_target"], note=r["note"],
            )
            rows_by_c[r["commitment_id"]] = (c, [])
        ps = PaymentSchedule(
            rate_id=r["rate_id"], commitment_id=r["commitment_id"],
            seq=r["seq"], data_prevista=r["data_prevista"],
            importo_eur=Decimal(str(r["importo_eur"])),
            descrizione=r["rata_descr"], stato=r["rata_stato"],
            data_stato=r["rata_data_stato"],
        )
        rows_by_c[r["commitment_id"]][1].append(ps)

    pf_rows: list[dict] = []
    for c, rates in rows_by_c.values():
        pf_rows.extend(compute_forward_flow_rows(c, rates))

    if dry_run:
        return {"deleted": 0, "inserted": 0, "rows": pf_rows, "dry_run": True}

    client.query(
        f"""DELETE FROM `{_PROJECT_REF}.f_piano_finanziario_input`
            WHERE fonte = @fonte AND progetto_id = @pid""",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("fonte", "STRING", FORWARD_FLOW_FONTE),
            bigquery.ScalarQueryParameter("pid", "STRING", progetto_id),
        ]),
    ).result()

    if pf_rows:
        errors = client.insert_rows_json(f"{_PROJECT_REF}.f_piano_finanziario_input", pf_rows)
        if errors:
            raise RuntimeError(f"insert errors: {errors}")

    return {"deleted": "ok", "inserted": len(pf_rows), "rows": pf_rows}
```

- [ ] **Step 4: Run unit tests — verify pass**

Run: `pytest tests/test_projects_forward_flow.py -v`
Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add progetti/forward_flow.py progetti/config.py tests/test_projects_forward_flow.py
git commit -m "feat(progetti): forward-flow solver (CAPEX/OPEX branch + idempotent DELETE+INSERT)"
```

---

## Task 18: CLI commands — `hotelops progetti`

**Files:**
- Modify: `progetti/cli_commands.py`
- Modify: `cli.py`

- [ ] **Step 1: Implement handlers**

```python
# progetti/cli_commands.py
from __future__ import annotations

import argparse

from google.cloud import bigquery

from core.bq.client import get_client
from progetti.forward_flow import apply_forward_flow


def cmd_progetti_forward_flow(args: argparse.Namespace) -> None:
    summary = apply_forward_flow(args.progetto, dry_run=args.dry_run)
    print(f"Forward-flow progetto={args.progetto} dry_run={args.dry_run}")
    print(f"Rows to emit: {len(summary['rows'])}")
    for r in summary["rows"]:
        print(f"  {r['societa_id']:5} {r['voce_id']:22} {r['mese']} {r['importo_eur']:>12} {r['descrizione']}")
    if not args.dry_run:
        print(f"Inserted: {summary['inserted']} rows.")


def cmd_progetti_fornitori_candidate(args: argparse.Namespace) -> None:
    client = get_client()
    q = """
    SELECT ragione_sociale, partita_iva
    FROM `hotelops-suite.hotelops.d_anagrafica_fornitori`
    WHERE stato_censimento = 'DA_CENSIRE'
    ORDER BY ragione_sociale
    """
    for r in client.query(q).result():
        print(f"  {r['ragione_sociale']}  (P.IVA: {r['partita_iva']})")


def cmd_progetti_fornitori_promote(args: argparse.Namespace) -> None:
    client = get_client()
    job = client.query(
        """UPDATE `hotelops-suite.hotelops.d_anagrafica_fornitori`
           SET stato_censimento = 'CENSITO'
           WHERE ragione_sociale = @rs""",
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("rs", "STRING", args.denorm),
        ]),
    )
    job.result()
    print(f"Promoted: {args.denorm} → CENSITO ({job.num_dml_affected_rows} rows)")


def register(subparsers) -> None:
    p = subparsers.add_parser("progetti", help="Projects vertical commands")
    sub = p.add_subparsers(dest="progetti_cmd", required=True)

    ff = sub.add_parser("forward-flow", help="Apply forward-flow to f_piano_finanziario_input")
    ff.add_argument("--progetto", required=True)
    ff.add_argument("--dry-run", action="store_true")
    ff.set_defaults(func=cmd_progetti_forward_flow)

    fo = sub.add_parser("fornitori", help="Fornitori candidate management")
    fo_sub = fo.add_subparsers(dest="fornitori_cmd", required=True)

    fo_c = fo_sub.add_parser("candidate", help="List candidate fornitori (stato_censimento=DA_CENSIRE)")
    fo_c.set_defaults(func=cmd_progetti_fornitori_candidate)

    fo_p = fo_sub.add_parser("promote", help="Promote fornitore candidate → CENSITO")
    fo_p.add_argument("denorm", help="ragione_sociale to promote")
    fo_p.set_defaults(func=cmd_progetti_fornitori_promote)
```

- [ ] **Step 2: Register in `cli.py`**

Open `cli.py`. Find where other verticals register their subparsers (e.g., `reviews.cli_commands.register(...)`). Add:

```python
from progetti import cli_commands as progetti_cli
# ... inside subparser setup:
progetti_cli.register(subparsers)
```

- [ ] **Step 3: Smoke**

```bash
hotelops progetti forward-flow --progetto HPAN25PIANO1 --dry-run
```

Expected: prints 15 rows (5 commitments × 3 rates, all PIANIFICATA).

```bash
hotelops progetti fornitori candidate
```

Expected: lists any DA_CENSIRE entries (likely empty initially, ok).

- [ ] **Step 4: Commit**

```bash
git add progetti/cli_commands.py cli.py
git commit -m "feat(progetti): CLI commands forward-flow + fornitori candidate/promote"
```

---

## Task 19: Streamlit View 1 — Register

**Files:**
- Modify: `progetti/app_projects.py`

- [ ] **Step 1: Implement skeleton + View 1**

```python
# progetti/app_projects.py
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.bq.client import get_client

st.set_page_config(page_title="HotelOps Progetti", layout="wide")
st.title("Progetti — Project Subledger")


@st.cache_data(ttl=60)
def load_progetti() -> pd.DataFrame:
    return get_client().query(
        "SELECT * FROM `hotelops-suite.hotelops.v_progetto_overview` ORDER BY progetto_id"
    ).to_dataframe()


@st.cache_data(ttl=60)
def load_register(progetto_id: str) -> pd.DataFrame:
    q = """
    WITH latest_scope AS (
      SELECT * FROM `hotelops-suite.hotelops.v_progetto_scopes_current`
      WHERE progetto_id = @pid
    ),
    commit_on_scope AS (
      SELECT l.scope_package_id, c.commitment_id, c.fornitore_denorm,
             c.importo_impegnato_eur, c.stato AS commit_stato,
             cs.delta_overrun_eur, cs.stato_overrun
      FROM `hotelops-suite.hotelops.f_progetto_scope_commitment_link` l
      JOIN `hotelops-suite.hotelops.v_progetto_commitments_current` c USING (commitment_id)
      LEFT JOIN `hotelops-suite.hotelops.v_commitment_status` cs USING (commitment_id)
    ),
    prev_on_scope AS (
      SELECT scope_package_id, MAX(importo_eur) AS max_prev_eur
      FROM `hotelops-suite.hotelops.f_progetto_documenti`
      WHERE tipo = 'PREVENTIVO' AND stato_preventivo IN ('RICEVUTO','ACCETTATO')
      GROUP BY scope_package_id
    )
    SELECT
      s.scope_id, s.codice, s.descrizione, s.categoria, s.stato,
      s.importo_stimato_eur,
      c.fornitore_denorm,
      c.importo_impegnato_eur,
      p.max_prev_eur,
      COALESCE(c.importo_impegnato_eur, p.max_prev_eur, s.importo_stimato_eur) AS importo_vigente_eur,
      CASE
        WHEN c.importo_impegnato_eur IS NOT NULL THEN 'COMMITTED'
        WHEN p.max_prev_eur IS NOT NULL THEN 'PREVENTIVO'
        ELSE 'STIMA'
      END AS fonte_importo,
      c.delta_overrun_eur, c.stato_overrun
    FROM latest_scope s
    LEFT JOIN commit_on_scope c ON c.scope_package_id = s.scope_id
    LEFT JOIN prev_on_scope p ON p.scope_package_id = s.scope_id
    ORDER BY s.categoria, s.codice
    """
    from google.cloud import bigquery
    return get_client().query(
        q,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("pid", "STRING", progetto_id)
        ]),
    ).to_dataframe()


progetti = load_progetti()
if progetti.empty:
    st.info("Nessun progetto.")
    st.stop()

selected = st.sidebar.selectbox("Progetto", progetti["progetto_id"].tolist())
p = progetti[progetti["progetto_id"] == selected].iloc[0]

tab1, tab2, tab3, tab4 = st.tabs(["Register", "Documents", "Budget evolution", "Payment planning"])

with tab1:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Cap", f"€ {p['budget_cap_eur']:,.0f}")
    c2.metric("Impegnato", f"€ {p['sum_impegnato_eur']:,.0f}")
    c3.metric("Stimato residuo", f"€ {p['sum_stimato_eur']:,.0f}")
    c4.metric("Fatturato", f"€ {p['sum_fatturato_eur']:,.0f}")
    buf = p["buffer_residuo_eur"]
    c5.metric("Buffer residuo", f"€ {buf:,.0f}", delta=p["stato_budget"])

    reg = load_register(selected)
    st.dataframe(reg, use_container_width=True, hide_index=True)
```

- [ ] **Step 2: Smoke**

Run: `streamlit run progetti/app_projects.py`
Expected: KPIs show HPAN25PIANO1 numbers; Register table shows 28 scopes with 5 COMMITTED.

Kill (Ctrl+C).

- [ ] **Step 3: Commit**

```bash
git add progetti/app_projects.py
git commit -m "feat(progetti): Streamlit View 1 — Register (KPIs + scope cascade)"
```

---

## Task 20: Streamlit View 2 — Documents (Drop + orfane)

**Files:**
- Modify: `progetti/app_projects.py`

- [ ] **Step 1: Implement Documents tab**

Append inside `with tab2:`:

```python
# progetti/app_projects.py (inside with tab2:)
with tab2:
    sub_drop, sub_orfane, sub_list = st.tabs(["Drop documento", "Fatture orfane", "Lista documenti"])

    with sub_drop:
        uploaded = st.file_uploader("Drop PDF preventivo/fattura", type=["pdf"])
        if uploaded is not None:
            import hashlib
            data = uploaded.getvalue()
            md5 = hashlib.md5(data).hexdigest()
            st.write(f"MD5: `{md5}`")
            if st.button("Estrai con Claude Haiku"):
                from progetti.extract import extract_document_fields
                fields = extract_document_fields(data, uploaded.name)
                st.json(fields.__dict__)
                st.warning("Review + submit in version integrata (MVP stub).")

    with sub_orfane:
        q = """
        SELECT mc.row_hash, mc.data_registrazione, mc.descrizione,
               (mc.imp_dare - mc.imp_avere) AS importo, mc.fornitore
        FROM `hotelops-suite.hotelops.f_movimenti_contabili` mc
        WHERE NOT EXISTS (
          SELECT 1 FROM `hotelops-suite.hotelops.f_progetto_invoice_link` il
          WHERE il.movimento_row_hash = mc.row_hash
        )
        AND mc.data_registrazione >= DATE '2026-01-01'
        ORDER BY mc.data_registrazione DESC
        LIMIT 200
        """
        orfane = get_client().query(q).to_dataframe()
        st.caption(f"{len(orfane)} fatture senza InvoiceLink (ultimi 12 mesi, LIMIT 200)")
        st.dataframe(orfane, use_container_width=True, hide_index=True)

    with sub_list:
        q = """
        SELECT scope_package_id, tipo, fornitore_denorm, numero_documento,
               data_documento, importo_eur, stato_preventivo, drive_path
        FROM `hotelops-suite.hotelops.f_progetto_documenti`
        WHERE scope_package_id IN (
          SELECT scope_id FROM `hotelops-suite.hotelops.v_progetto_scopes_current`
          WHERE progetto_id = @pid
        )
        ORDER BY data_documento DESC
        """
        from google.cloud import bigquery
        docs = get_client().query(
            q,
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("pid", "STRING", selected)
            ]),
        ).to_dataframe()
        st.dataframe(docs, use_container_width=True, hide_index=True)
```

Adjust column name `fornitore` / `row_hash` if different in `f_movimenti_contabili`.

- [ ] **Step 2: Smoke**

Launch streamlit, click Documents tab, verify 3 sub-tabs render.

- [ ] **Step 3: Commit**

```bash
git add progetti/app_projects.py
git commit -m "feat(progetti): Streamlit View 2 — Documents (drop + orfane + lista)"
```

---

## Task 21: Streamlit View 3 — Budget evolution

**Files:**
- Modify: `progetti/app_projects.py`

- [ ] **Step 1: Implement**

```python
# progetti/app_projects.py (inside with tab3:)
with tab3:
    from google.cloud import bigquery

    q = """
    SELECT * FROM `hotelops-suite.hotelops.v_progetto_timeline`
    WHERE progetto_id = @pid
    ORDER BY ts_evento DESC
    """
    tl = get_client().query(
        q,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("pid", "STRING", selected)
        ]),
    ).to_dataframe()
    st.subheader("Timeline eventi")
    st.dataframe(tl, use_container_width=True, hide_index=True)

    # Cumulative projected budget chart
    if not tl.empty and "ts_evento" in tl.columns:
        import pandas as pd
        tl_sorted = tl.sort_values("ts_evento")
        tl_sorted["cum_impegnato"] = tl_sorted.apply(
            lambda r: r["importo_eur"] if r["tipo_evento"] == "COMMITMENT_STATO" else 0, axis=1
        ).cumsum()
        st.line_chart(tl_sorted.set_index("ts_evento")["cum_impegnato"])
```

- [ ] **Step 2: Smoke**

Streamlit → Budget evolution tab. Verify timeline table + chart render.

- [ ] **Step 3: Commit**

```bash
git add progetti/app_projects.py
git commit -m "feat(progetti): Streamlit View 3 — Budget evolution (timeline)"
```

---

## Task 22: Streamlit View 4 — Payment planning

**Files:**
- Modify: `progetti/app_projects.py`

- [ ] **Step 1: Implement**

```python
# progetti/app_projects.py (inside with tab4:)
with tab4:
    from google.cloud import bigquery

    q = """
    SELECT
      DATE_TRUNC(ps.data_prevista, MONTH) AS mese,
      c.societa_pagante_id AS societa,
      c.tipo_spesa,
      SUM(ps.importo_eur) AS importo_eur
    FROM `hotelops-suite.hotelops.v_progetto_payment_schedules_current` ps
    JOIN `hotelops-suite.hotelops.v_progetto_commitments_current` c USING (commitment_id)
    WHERE c.progetto_id = @pid AND ps.stato = 'PIANIFICATA'
    GROUP BY mese, societa, tipo_spesa
    ORDER BY mese, societa
    """
    pay = get_client().query(
        q,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("pid", "STRING", selected)
        ]),
    ).to_dataframe()

    st.subheader("Cashflow mensile — rate pianificate")
    if pay.empty:
        st.info("Nessuna rata pianificata.")
    else:
        piv = pay.pivot_table(
            index="mese",
            columns=["societa", "tipo_spesa"],
            values="importo_eur",
            aggfunc="sum",
            fill_value=0,
        )
        st.dataframe(piv, use_container_width=True)
        st.bar_chart(piv.sum(axis=1))

    st.subheader("Forward-flow")
    col1, col2 = st.columns(2)
    if col1.button("Dry run"):
        from progetti.forward_flow import apply_forward_flow
        out = apply_forward_flow(selected, dry_run=True)
        st.json({"rows": len(out["rows"]), "preview": out["rows"][:5]})
    if col2.button("Applica (DELETE+INSERT)"):
        from progetti.forward_flow import apply_forward_flow
        out = apply_forward_flow(selected, dry_run=False)
        st.success(f"Inserted {out['inserted']} rows in f_piano_finanziario_input.")
```

- [ ] **Step 2: Smoke**

Streamlit → Payment planning. Dry-run button → shows 15 rows preview. Apply → triggers real insert.

- [ ] **Step 3: Commit**

```bash
git add progetti/app_projects.py
git commit -m "feat(progetti): Streamlit View 4 — Payment planning + forward-flow trigger"
```

---

## Task 23: E2E smoke test

**Files:**
- Create: `tests/test_projects_e2e.py`

- [ ] **Step 1: Write test**

```python
# tests/test_projects_e2e.py
import pytest

pytestmark = pytest.mark.bq


def test_seed_loaded_overview_consistent(bq_client):
    q = """
    SELECT * FROM `hotelops-suite.hotelops.v_progetto_overview`
    WHERE progetto_id = 'HPAN25PIANO1'
    """
    rows = list(bq_client.query(q).result())
    assert len(rows) == 1
    r = rows[0]
    assert float(r["budget_cap_eur"]) == 1_200_000
    assert float(r["sum_impegnato_eur"]) >= 380_000  # 85+180+42+48+25
    assert r["stato_budget"] in {"OK", "NEAR_CAP", "SFORATO"}


def test_forward_flow_emits_15_rows(bq_client):
    from progetti.forward_flow import apply_forward_flow
    out = apply_forward_flow("HPAN25PIANO1", dry_run=False)
    assert out["inserted"] == 15  # 5 commitments × 3 rates

    q = """
    SELECT COUNT(*) AS n
    FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
    WHERE fonte = 'PROGETTI' AND progetto_id = 'HPAN25PIANO1'
    """
    n = list(bq_client.query(q).result())[0]["n"]
    assert n == 15


def test_forward_flow_idempotent(bq_client):
    from progetti.forward_flow import apply_forward_flow
    apply_forward_flow("HPAN25PIANO1", dry_run=False)
    apply_forward_flow("HPAN25PIANO1", dry_run=False)  # idempotent
    q = """
    SELECT COUNT(*) AS n
    FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
    WHERE fonte = 'PROGETTI' AND progetto_id = 'HPAN25PIANO1'
    """
    n = list(bq_client.query(q).result())[0]["n"]
    assert n == 15  # Still 15, not 30


def test_capex_rows_go_to_intur_investimenti_capex(bq_client):
    q = """
    SELECT societa_id, voce_id, COUNT(*) AS n
    FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
    WHERE fonte = 'PROGETTI' AND progetto_id = 'HPAN25PIANO1'
    GROUP BY societa_id, voce_id
    ORDER BY n DESC
    """
    rows = list(bq_client.query(q).result())
    by_key = {(r["societa_id"], r["voce_id"]): r["n"] for r in rows}
    assert by_key[("INTUR", "INVESTIMENTI_CAPEX")] == 9  # 3 capex commitments × 3 rates
    assert by_key[("ORTI", "CONSULENZE")] == 3  # Hospitality
    assert by_key[("INTUR", "CONSULENZE")] == 3  # Pisacane
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_projects_e2e.py -v`
Expected: 4/4 PASS. If `HOTELOPS_SKIP_BQ=1`, skip.

- [ ] **Step 3: Commit**

```bash
git add tests/test_projects_e2e.py
git commit -m "test(progetti): E2E smoke — forward-flow idempotence + row allocation"
```

---

## Task 24: Vault captures

**Files:**
- Create: `/Users/stefanodellapietra/dev/projects/obsidian/Obsidian Vault/hotelops/decisions/2026-04-21_Projects_Vertical.md`
- Create: `/Users/stefanodellapietra/dev/projects/obsidian/Obsidian Vault/hotelops/ontology/business-rules/capex-opex-allocation.md`
- Modify: `/Users/stefanodellapietra/dev/projects/obsidian/Obsidian Vault/hotelops/ontology/projects/CamerePrimoPiano.md`
- Modify: `/Users/stefanodellapietra/dev/projects/obsidian/Obsidian Vault/hotelops/PLATFORM.md`

- [ ] **Step 1: Write decision stub**

```markdown
# Projects — 4th vertical (project subledger + forward-flow)

**Date:** 2026-04-21
**Status:** implementato (MVP HPAN25PIANO1)
**Related I:** candidato I9 riformulato (subledger + forward-flow, non retroattivo)
**Related commits:** (fill after merge)

## Context

Gruppo Panorama esegue investimenti capex di grande scala (HPAN25PIANO1, 1.2M) che CONDGES non
modella: manca il ciclo impegno → documento → fattura → pagamento per progetto. Tagging retroattivo
di `progetto_id` sulle fact canoniche viola I3 (Canonical Truth Registry) e introduce accoppiamenti
indesiderati.

## Decision

`progetti/` diventa il 4° vertical peer di CONDGES / REVIEWS / ECONOMATO, con:

- 7 entità Pydantic: Project, ScopePackage, Document, Commitment, PaymentSchedule, InvoiceLink, ScopeCommitmentLink (+DocumentExtraction audit).
- 8 tabelle BQ prefix `f_progetto_*` + `d_progetti`. 6 view (3 latest-state, `v_commitment_status`, `v_progetto_overview`, `v_progetto_timeline`).
- **Forward-flow** (non retroactive tagging): Commitments + PaymentSchedules emettono righe in `f_piano_finanziario_input` con `fonte='PROGETTI'` e nuova colonna `progetto_id`.
- Nuova voce PF `INVESTIMENTI_CAPEX` per capex (INTUR). OPEX progetti (es. Hospitality Project PM fee) usa lookup (`CONSULENZE`).
- Streamlit `progetti/app_projects.py` con 4 view (Register / Documents / Budget evolution / Payment planning).
- LLM extraction via Claude Haiku, human review obbligatoria prima di submit.

## Consequences

- **+** Canonicità rispettata: fatture restano in `f_movimenti_contabili`, linkate via thin `f_progetto_invoice_link`.
- **+** Rosa/Gasparotto vedono le rate progetti in `v_budget_canonical`-downstream senza saperlo (idiomatico PF).
- **+** Stefano vede budget cap, overrun, pct_committed in <10s.
- **−** Richiede merge coordinato con Session 1 (Gasparotto Cash-Flow) su struttura `d_voci_piano_finanziario`.
- **−** I10 ritirato come invariant → diventa business rule vertical (vedi `ontology/business-rules/capex-opex-allocation.md`).

## Implementation

- branch: `projects-mvp-hpan25piano1`
- plan: `docs/superpowers/plans/2026-04-20-projects-mvp.md`
- spec: `docs/superpowers/specs/2026-04-20-projects-mvp-design.md`
- commits: (fill after merge)
```

- [ ] **Step 2: Write business rule stub**

```markdown
# capex-opex-allocation (Gruppo Panorama)

**Tipo:** business rule vertical (`progetti/`)
**Status:** attivo
**Related:** `decisions/2026-04-21_Projects_Vertical.md`

## Regola

- **CAPEX su immobili** → società **proprietaria dell'asset** (INTUR: Hotel, Spiaggia, Immobili; ORTI: solo se immobile registrato a ORTI).
- **OPEX operativi** → società **operativa** (ORTI: gestione Hotel/Residence/CVM; INTUR: Lido).

## Esempi HPAN25PIANO1

| Commitment | Tipo | Società pagante | Voce PF |
|---|---|---|---|
| STE impianti camere | CAPEX | INTUR | INVESTIMENTI_CAPEX |
| Santelia opere murarie | CAPEX | INTUR | INVESTIMENTI_CAPEX |
| Dierre porte std | CAPEX | INTUR | INVESTIMENTI_CAPEX |
| Pisacane DL | OPEX | INTUR | CONSULENZE |
| Hospitality Project PM fee | OPEX | **ORTI** | CONSULENZE |

## Enforcement

- UI `progetti/app_projects.py`: default societa_pagante in base a tipo_spesa (CAPEX→INTUR).
- Warn su override manuale (non blocca).
- Non enforced in BQ: `f_progetto_commitments.societa_pagante_id` è STRING libero.

## Perché vertical e non I10

Regola gruppo-specifica di Panorama: altri gruppi potrebbero allocare differentemente
(es. capex su società operativa se leaseback, o holding immobiliare per tutti i capex
multi-struttura). Non platform-wide → non invariant.
```

- [ ] **Step 3: Update `CamerePrimoPiano.md`**

Read current content, update budget from 350K to 1.2M, add section:

```markdown
## Subledger (MVP 2026-04-21)

Gestito in `progetti/` vertical. Vedi `docs/progetti/HPAN25PIANO1-walkthrough.md`.

- 28 ScopePackages (4 bucket: a firmati, b accettati, c in valutazione, d orfani/TBD)
- 5 Commitments (bucket a): STE, Santelia, Dierre, Hospitality Project, Pisacane
- 15 PaymentSchedules (30/40/30 per commitment)
- Forward-flow attivo → `f_piano_finanziario_input` fonte=PROGETTI
```

- [ ] **Step 4: Update `PLATFORM.md`**

Add row to verticals table:

```markdown
| [[verticals/PROGETTI]] | ✅ Attivo (MVP) | Stefano Jr (+ PM) | Streamlit app_projects.py |
```

Add under BigQuery Schema / Fact Tables:
```
**+8 Projects tables (vertical `progetti/`):**
- d_progetti, f_progetto_scopes, f_progetto_commitments, f_progetto_scope_commitment_link,
  f_progetto_documenti, f_progetto_payment_schedules, f_progetto_invoice_link, f_progetto_extractions
```

Update Views from 15 → 21 with:
```
- v_progetto_scopes_current / v_progetto_commitments_current / v_progetto_payment_schedules_current (latest-state)
- v_commitment_status (overrun)
- v_progetto_overview (budget cascade)
- v_progetto_timeline (UNION ALL event log)
```

- [ ] **Step 5: Commit vault changes**

```bash
cd "/Users/stefanodellapietra/dev/projects/obsidian/Obsidian Vault/hotelops"
git add decisions/2026-04-21_Projects_Vertical.md ontology/business-rules/capex-opex-allocation.md ontology/projects/CamerePrimoPiano.md PLATFORM.md
git commit -m "capture: Projects vertical MVP (HPAN25PIANO1) + capex-opex business rule"
cd -
```

---

## Task 25: Merge + STATUS update

**Files:**
- Modify: `STATUS.md`

- [ ] **Step 1: Verify full test suite green**

```bash
pytest
ruff check .
```

Expected: all green. Fix any regression before proceeding.

- [ ] **Step 2: Push branch + open PR**

```bash
git push -u origin projects-mvp-hpan25piano1
gh pr create --title "feat: Projects MVP — 4th vertical (subledger + forward-flow)" --body "$(cat <<'EOF'
## Summary
- Introduces `progetti/` as 4th HotelOps vertical (peer of CONDGES / REVIEWS / ECONOMATO)
- 7 entity Pydantic models + 8 BQ tables + 6 views
- Forward-flow solver: Commitments+PaymentSchedules → `f_piano_finanziario_input` fonte=`PROGETTI`
- Canonical migrations: new voce `INVESTIMENTI_CAPEX`, `progetto_id` column on PF input, `stato_censimento` on fornitori
- Seed: HPAN25PIANO1 (28 scopes, 5 commitments, 15 rates, 6 docs)
- Streamlit `app_projects.py` with 4 views (Register / Documents / Budget evolution / Payment planning)
- LLM extraction via Claude Haiku (`claude-haiku-4-5-20251001`)
- Vault captures: decision stub, capex-opex business rule, CamerePrimoPiano update

## Spec
`docs/superpowers/specs/2026-04-20-projects-mvp-design.md`

## Test plan
- [ ] Unit tests green (`pytest tests/test_projects_*`)
- [ ] E2E BQ green (`pytest tests/test_projects_e2e.py -m bq`)
- [ ] Streamlit smoke (4 tabs render)
- [ ] `hotelops progetti forward-flow --progetto HPAN25PIANO1 --dry-run` → 15 rows
- [ ] `f_piano_finanziario_input` shows 15 rows fonte=PROGETTI
EOF
)"
```

- [ ] **Step 3: Update STATUS.md**

Add to "Completato di recente":

```markdown
- 2026-04-21: **Projects MVP vertical** — nuovo `progetti/` (4° vertical), 8 BQ tables + 6 views, forward-flow solver, seed HPAN25PIANO1 (28 scopes, 5 commitments, 15 rates). Nuova voce PF `INVESTIMENTI_CAPEX`, colonna `progetto_id` su `f_piano_finanziario_input`, fonte `PROGETTI`. Streamlit `app_projects.py` 4 view. Vault captures: decision + capex-opex business rule. Branch `projects-mvp-hpan25piano1`.
```

Move from "In corso" (remove) / add to "Completato".

- [ ] **Step 4: Commit STATUS**

```bash
git add STATUS.md
git commit -m "chore: STATUS.md — Projects MVP shipped"
```

- [ ] **Step 5: Merge PR** (after user review)

```bash
gh pr merge --squash --delete-branch
```

---

## Self-review notes

**Spec coverage (§2.4 success criteria):**
- Register view → Task 19 ✓
- Documents view → Task 20 ✓
- Budget evolution → Task 21 ✓
- Payment planning → Task 22 ✓
- Forward-flow verifiable → Task 23 ✓

**Canonicals migration:** INVESTIMENTI_CAPEX (Task 10), `progetto_id` column (Task 10), `stato_censimento` (Task 10), `fonte=PROGETTI` as a new permitted value (implicit — string column, no enum check in BQ).

**Seed data blocks user is filling in parallel** (from walkthrough §Decisioni bloccanti):
- Importi bucket (c)+(d) Excel canonical — seed uses rough estimates; will be revised in a follow-up commit.
- Capone TV canonical name — placeholder "Capone (TV)" in seed.
- Dierre bucket b/d split — seed treats as bucket a (ordine 864 firmato).
- Metal 2000 scope — scope TBD note in seed.
- Atelier/Ninni reclassification — Atelier ARREDI, Ninni PROGETTAZIONE as walkthrough suggests.

These refine the Register numbers but don't block the model shipping.

**Session 1 coord** (§9 of spec): this plan assumes `d_voci_piano_finanziario.csv` has standard columns (voce_id, nome, direzione, fonte, ...). If Session 1 ships a structural change, Task 10 Step 3 must be adjusted to the new schema before applying.
