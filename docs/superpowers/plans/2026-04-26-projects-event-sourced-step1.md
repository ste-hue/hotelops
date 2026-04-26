# Projects Event-Sourced Step 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Materializzare 3 tabelle BigQuery (`d_progetti`, `f_progetto_voci`, `f_progetto_eventi`) + Pydantic discriminated union sui 5 tipi di evento + seed inline (10 voci, 19 eventi) su 2 progetti reali + view `v_progetto_voci_stato` che deriva lo stato per voce. Validare che lo stesso schema regge HPAN25PIANO1 (maturo, commitment+fatture+overrun) e SPIAGGIA_LOTTO7 (early-stage, solo preventivi).

**Architecture:** Event sourcing su 3 tabelle. `f_progetto_eventi` (APPEND) è log immutabile; `f_progetto_voci` (SNAPSHOT) è identità della riga di scope; `d_progetti` (SNAPSHOT) è anagrafica progetto. Pydantic v2 discriminated union su `tipo_evento ∈ {PREVENTIVO, IMPEGNO, FATTURA, PAGAMENTO, DOCUMENTO}` per validation gate (I1). Le 3 lenti I4 (IMPEGNO/COMPETENZA/CASSA) si derivano dagli eventi via view. Step 1 implementa solo la view per la domanda **COSA** (Register); le altre 3 (CHI/QUANTO/QUANDO) sono Fase 2.

**Tech Stack:** Python 3.11, Pydantic v2 (`BaseModel`, `Field(discriminator=...)`, `model_validator`), `google-cloud-bigquery`, pytest, ruff. BigQuery: project=`hotelops-suite`, dataset=`hotelops`.

---

## Reference

- Spec: `docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md`
- Concept: vault `concepts/PROGETTO.md`
- Patterns to follow:
  - `core/schemas.py` — Pydantic v2, `from __future__ import annotations`, type aliases (`SocietaId`, `BusinessUnitId`), `field_validator`
  - `core/config.py` — `_t()` helper, `F_*` / `D_*` / `V_*` constants
  - `core/bq/load/load_voci_piano_finanziario.py` — loader pattern: `BQ_SCHEMA` tuple, `setup_logger()`, idempotent `WRITE_TRUNCATE`, CLI with argparse
  - `core/bq/views/v_ledger_movimenti.sql` — view SQL with `CREATE OR REPLACE VIEW \`hotelops-suite.hotelops.v_*\` AS`
  - `core/bq/client.py::get_client()` — BQ client singleton
  - `tests/conftest.py` — `mock_bq_client` fixture for unit tests
  - `tests/test_budget_canonical.py` — example of `@pytest.mark.bq` marker for integration tests

## File Structure

**Create:**
- `tests/test_progetti_schema.py` — Pydantic unit tests (~12 tests)
- `tests/test_progetti_seed.py` — BQ integration tests (`@pytest.mark.bq`, ~5 tests)
- `core/bq/load/create_progetti_tables.py` — DDL idempotent for 3 tables
- `core/bq/load/seed_progetti_step1.py` — Inline seed loader
- `core/bq/views/v_progetto_voci_stato.sql` — View SQL
- `core/bq/load/deploy_view_voci_stato.py` — View deploy script (executes the SQL)

**Modify:**
- `core/schemas.py` — Add `Rata`, 5 metadata sub-models, `Progetto`, `ProgettoVoce`, `ProgettoEvento`
- `core/config.py` — Add `D_PROGETTI`, `F_PROGETTO_VOCI`, `F_PROGETTO_EVENTI`, `V_PROGETTO_VOCI_STATO`

---

## Task 1: Pydantic helper `Rata` + first metadata `PreventivoMeta`

**Files:**
- Modify: `core/schemas.py`
- Create: `tests/test_progetti_schema.py`

- [ ] **Step 1.1: Write the failing test for `Rata` and `PreventivoMeta`**

Create `tests/test_progetti_schema.py` with:

```python
"""Pydantic validation tests for projects event-sourced models (Step 1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.schemas import PreventivoMeta, Rata


class TestRata:
    def test_happy_path(self):
        r = Rata(
            seq=1,
            data_prevista=date(2026, 5, 1),
            importo_eur=Decimal("100.00"),
            descrizione="Acconto 30%",
            stato="PIANIFICATA",
        )
        assert r.seq == 1
        assert r.importo_eur == Decimal("100.00")
        assert r.stato == "PIANIFICATA"

    def test_invalid_stato_rejected(self):
        with pytest.raises(ValidationError):
            Rata(
                seq=1,
                data_prevista=date(2026, 5, 1),
                importo_eur=Decimal("100"),
                descrizione="x",
                stato="UNKNOWN_STATO",
            )


class TestPreventivoMeta:
    def test_minimal_required(self):
        m = PreventivoMeta(
            articolo="Pagoda 220",
            stato_preventivo="RICEVUTO",
        )
        assert m.tipo == "PREVENTIVO"
        assert m.articolo == "Pagoda 220"
        assert m.numero_preventivo is None

    def test_full_fields(self):
        m = PreventivoMeta(
            numero_preventivo="SQ221807-2",
            data_preventivo=date(2025, 3, 10),
            validita_fino_a=date(2025, 6, 10),
            articolo="Sand Desk Brown Inground Wood",
            codice_articolo="NRO510-0611",
            stato_preventivo="ACCETTATO",
            note="Sconto 20% applicato",
        )
        assert m.numero_preventivo == "SQ221807-2"
        assert m.codice_articolo == "NRO510-0611"

    def test_invalid_stato_preventivo_rejected(self):
        with pytest.raises(ValidationError):
            PreventivoMeta(articolo="x", stato_preventivo="MAYBE")
```

- [ ] **Step 1.2: Run the test to verify it fails**

```bash
cd /Users/stefanodellapietra/dev/Projects/hotelops
pytest tests/test_progetti_schema.py -v
```

Expected: `ImportError` or `AttributeError` on `from core.schemas import PreventivoMeta, Rata` (these don't exist yet).

- [ ] **Step 1.3: Implement `Rata` and `PreventivoMeta` in `core/schemas.py`**

First, update the imports section at the top of `core/schemas.py` to include `Decimal`:

```python
from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal  # ← add this line
from typing import Literal, Optional

from pydantic import BaseModel, field_validator
```

Then append after existing models:

```python
# ── projects (event-sourced Step 1) ──────────────────────────────────────────


class Rata(BaseModel):
    """Una rata di pagamento dentro un piano (ImpegnoMeta.rate[])."""

    seq: int
    data_prevista: date
    importo_eur: Decimal
    descrizione: str
    stato: Literal["PIANIFICATA", "EMESSA", "PAGATA", "ANNULLATA"]


class PreventivoMeta(BaseModel):
    """metadata per evento tipo_evento='PREVENTIVO'."""

    tipo: Literal["PREVENTIVO"] = "PREVENTIVO"
    numero_preventivo: Optional[str] = None
    data_preventivo: Optional[date] = None
    validita_fino_a: Optional[date] = None
    articolo: str
    codice_articolo: Optional[str] = None
    stato_preventivo: Literal["RICEVUTO", "ACCETTATO", "RIFIUTATO", "SCADUTO"]
    note: Optional[str] = None
```

- [ ] **Step 1.4: Run the test to verify it passes**

```bash
pytest tests/test_progetti_schema.py -v
```

Expected: 4 tests PASS (1 Rata happy + 1 Rata reject + 2 PreventivoMeta happy + 1 PreventivoMeta reject = 5 tests, all green).

- [ ] **Step 1.5: Commit**

```bash
git add core/schemas.py tests/test_progetti_schema.py
git commit -m "feat(progetti): add Rata + PreventivoMeta Pydantic models

Step 1 of event-sourced design: helper Rata for payment schedules and
first event metadata sub-model (PreventivoMeta).

Refs: docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md §3.1

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Pydantic metadata `ImpegnoMeta` + `FatturaMeta`

**Files:**
- Modify: `core/schemas.py`
- Modify: `tests/test_progetti_schema.py`

- [ ] **Step 2.1: Add tests for `ImpegnoMeta` and `FatturaMeta`**

Append to `tests/test_progetti_schema.py`:

```python
class TestImpegnoMeta:
    def test_minimal_with_rate(self):
        from core.schemas import ImpegnoMeta

        m = ImpegnoMeta(
            data_firma=date(2026, 2, 27),
            rate=[
                Rata(
                    seq=1,
                    data_prevista=date(2026, 3, 1),
                    importo_eur=Decimal("7200.00"),
                    descrizione="Acconto 30%",
                    stato="PIANIFICATA",
                )
            ],
            stato_commitment="FIRMATO",
        )
        assert m.tipo == "IMPEGNO"
        assert len(m.rate) == 1
        assert m.from_preventivo_evento_id is None
        assert m.motivo_variazione is None

    def test_with_variazione(self):
        from core.schemas import ImpegnoMeta

        m = ImpegnoMeta(
            data_firma=date(2026, 3, 1),
            rate=[],
            stato_commitment="IN_CORSO",
            motivo_variazione="Overrun amianto Ft 02-26",
            from_preventivo_evento_id="evt-uuid-001",
        )
        assert m.motivo_variazione.startswith("Overrun")


class TestFatturaMeta:
    def test_minimal(self):
        from core.schemas import FatturaMeta

        m = FatturaMeta(
            numero_fattura="IT00126V0001851",
            data_emissione=date(2026, 4, 15),
            tipo_doc="FT",
            condizioni_pagamento="Bonifico 30gg",
        )
        assert m.tipo == "FATTURA"
        assert m.movimento_row_hash is None
        assert m.copre_rate == []

    def test_full(self):
        from core.schemas import FatturaMeta

        m = FatturaMeta(
            numero_fattura="FPR 31/26",
            data_emissione=date(2026, 3, 26),
            data_ricezione=date(2026, 3, 28),
            tipo_doc="FT-RC",
            condizioni_pagamento="Bonifico 90gg DF FM",
            data_scadenza=date(2026, 6, 30),
            movimento_row_hash="abc123def456",
            copre_rate=[1, 2],
        )
        assert m.tipo_doc == "FT-RC"
        assert m.copre_rate == [1, 2]
```

- [ ] **Step 2.2: Run tests to verify FAIL**

```bash
pytest tests/test_progetti_schema.py::TestImpegnoMeta tests/test_progetti_schema.py::TestFatturaMeta -v
```

Expected: `ImportError` on `ImpegnoMeta` and `FatturaMeta`.

- [ ] **Step 2.3: Implement `ImpegnoMeta` and `FatturaMeta` in `core/schemas.py`**

Append after `PreventivoMeta`:

```python
class ImpegnoMeta(BaseModel):
    """metadata per evento tipo_evento='IMPEGNO' (commitment firmato)."""

    tipo: Literal["IMPEGNO"] = "IMPEGNO"
    from_preventivo_evento_id: Optional[str] = None
    numero_contratto: Optional[str] = None
    data_firma: date
    rate: list[Rata]
    stato_commitment: Literal["FIRMATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    motivo_variazione: Optional[str] = None  # popolato solo per impegni successivi


class FatturaMeta(BaseModel):
    """metadata per evento tipo_evento='FATTURA'."""

    tipo: Literal["FATTURA"] = "FATTURA"
    numero_fattura: str
    data_emissione: date
    data_ricezione: Optional[date] = None
    tipo_doc: Literal["FT", "FT-RC", "NC"]
    condizioni_pagamento: str
    data_scadenza: Optional[date] = None
    movimento_row_hash: Optional[str] = None  # FK a f_movimenti_contabili
    copre_rate: list[int] = []  # seq rate IMPEGNO che questa fattura sta fatturando
```

- [ ] **Step 2.4: Run tests to verify PASS**

```bash
pytest tests/test_progetti_schema.py -v
```

Expected: all tests PASS (4 from Task 1 + 4 new = 8 total).

- [ ] **Step 2.5: Commit**

```bash
git add core/schemas.py tests/test_progetti_schema.py
git commit -m "feat(progetti): add ImpegnoMeta + FatturaMeta Pydantic models

ImpegnoMeta carries payment schedule (rate[]) and motivo_variazione for
successive commitments (overrun/riprogrammazione). FatturaMeta links to
f_movimenti_contabili via movimento_row_hash.

Refs: docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md §3.2-3.3

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Pydantic metadata `PagamentoMeta` + `DocumentoMeta`

**Files:**
- Modify: `core/schemas.py`
- Modify: `tests/test_progetti_schema.py`

- [ ] **Step 3.1: Add tests**

Append to `tests/test_progetti_schema.py`:

```python
class TestPagamentoMeta:
    def test_happy_path(self):
        from core.schemas import PagamentoMeta

        m = PagamentoMeta(
            data_valuta=date(2026, 5, 14),
            metodo="BONIFICO",
            importo_pagato_eur=Decimal("2169.16"),
            copre_fatture=["evt-fattura-001"],
        )
        assert m.tipo == "PAGAMENTO"
        assert m.banca_movimento_hash is None

    def test_multi_fattura_coverage(self):
        from core.schemas import PagamentoMeta

        m = PagamentoMeta(
            data_valuta=date(2026, 5, 14),
            metodo="BONIFICO",
            importo_pagato_eur=Decimal("10000.00"),
            copre_fatture=["evt-f-001", "evt-f-002", "evt-f-003"],
            banca_movimento_hash="md5xyz",
        )
        assert len(m.copre_fatture) == 3


class TestDocumentoMeta:
    def test_minimal(self):
        from core.schemas import DocumentoMeta

        m = DocumentoMeta(
            tipo_doc="PREVENTIVO",
            drive_url="https://drive.google.com/file/d/abc",
            file_name="Preventivo_Kompan.pdf",
            file_hash_md5="abc123",
        )
        assert m.tipo == "DOCUMENTO"
        assert m.correlato_evento_id is None

    def test_correlato_to_event(self):
        from core.schemas import DocumentoMeta

        m = DocumentoMeta(
            tipo_doc="FATTURA",
            drive_url="https://drive.google.com/...",
            file_name="ft_03.pdf",
            file_hash_md5="def456",
            correlato_evento_id="evt-fattura-uuid",
        )
        assert m.correlato_evento_id == "evt-fattura-uuid"
```

- [ ] **Step 3.2: Run tests to verify FAIL**

```bash
pytest tests/test_progetti_schema.py::TestPagamentoMeta tests/test_progetti_schema.py::TestDocumentoMeta -v
```

Expected: `ImportError`.

- [ ] **Step 3.3: Implement `PagamentoMeta` and `DocumentoMeta`**

Append to `core/schemas.py`:

```python
class PagamentoMeta(BaseModel):
    """metadata per evento tipo_evento='PAGAMENTO'."""

    tipo: Literal["PAGAMENTO"] = "PAGAMENTO"
    data_valuta: date
    metodo: Literal["BONIFICO", "SDD", "RID", "ASSEGNO", "CASSA"]
    importo_pagato_eur: Decimal
    copre_fatture: list[str]  # evento_id FATTURA coperti
    banca_movimento_hash: Optional[str] = None  # FK a f_banche_movimenti


class DocumentoMeta(BaseModel):
    """metadata per evento tipo_evento='DOCUMENTO' (allegato Drive)."""

    tipo: Literal["DOCUMENTO"] = "DOCUMENTO"
    tipo_doc: Literal[
        "PREVENTIVO",
        "CONTRATTO",
        "ORDINE",
        "FATTURA",
        "SAL",
        "PLANIMETRIA",
        "EMAIL",
        "ALTRO",
    ]
    drive_url: str
    file_name: str
    file_hash_md5: str  # dedup
    correlato_evento_id: Optional[str] = None
```

- [ ] **Step 3.4: Run tests to verify PASS**

```bash
pytest tests/test_progetti_schema.py -v
```

Expected: all 12 tests PASS.

- [ ] **Step 3.5: Commit**

```bash
git add core/schemas.py tests/test_progetti_schema.py
git commit -m "feat(progetti): add PagamentoMeta + DocumentoMeta Pydantic models

Completes the 5 metadata sub-models for event-sourced step 1.
PagamentoMeta covers fatture via copre_fatture[] (multi-coverage).
DocumentoMeta is the Drive-attachment evento, optionally correlato to
another evento_id (es. PDF preventivo -> evento PREVENTIVO).

Refs: docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md §3.4-3.5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Pydantic top-level `Progetto` + `ProgettoVoce`

**Files:**
- Modify: `core/schemas.py`
- Modify: `tests/test_progetti_schema.py`

- [ ] **Step 4.1: Add tests**

Append to `tests/test_progetti_schema.py`:

```python
class TestProgetto:
    def test_happy_path(self):
        from core.schemas import Progetto

        p = Progetto(
            progetto_id="HPAN25PIANO1",
            nome="Camere Primo Piano - Hotel Panorama",
            societa_owner_id="INTUR",
            business_unit_id="HOTEL",
            struttura="Hotel Panorama",
            budget_cap_eur=Decimal("1200000.00"),
            data_inizio=date(2026, 2, 1),
            stato="IN_CORSO",
            owner="Stefano Della Pietra Jr",
        )
        assert p.progetto_id == "HPAN25PIANO1"
        assert p.data_fine_prevista is None
        assert p.drive_root_url is None

    def test_invalid_societa_rejected(self):
        from core.schemas import Progetto

        with pytest.raises(ValidationError):
            Progetto(
                progetto_id="X",
                nome="X",
                societa_owner_id="UNKNOWN",  # invalid
                business_unit_id="HOTEL",
                budget_cap_eur=Decimal("1"),
                data_inizio=date(2026, 1, 1),
                stato="IN_CORSO",
                owner="x",
            )


class TestProgettoVoce:
    def test_minimal(self):
        from core.schemas import ProgettoVoce

        v = ProgettoVoce(
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            codice_interno="001",
            descrizione="Opere murarie strutturali piano 1",
            categoria="EDILE",
            societa_pagante_id="INTUR",
        )
        assert v.fornitore_id is None
        assert v.qta is None

    def test_with_fornitore_chosen(self):
        from core.schemas import ProgettoVoce

        v = ProgettoVoce(
            voce_id="HPAN25PIANO1.010",
            progetto_id="HPAN25PIANO1",
            codice_interno="010",
            descrizione="Project Management",
            categoria="CONSULENZA",
            societa_pagante_id="ORTI",  # opex via ORTI
            fornitore_id="anag-hospitality-project-001",
        )
        assert v.societa_pagante_id == "ORTI"
        assert v.fornitore_id is not None
```

- [ ] **Step 4.2: Run tests to verify FAIL**

```bash
pytest tests/test_progetti_schema.py::TestProgetto tests/test_progetti_schema.py::TestProgettoVoce -v
```

Expected: `ImportError`.

- [ ] **Step 4.3: Implement `Progetto` + `ProgettoVoce`**

Append to `core/schemas.py`:

```python
class Progetto(BaseModel):
    """Anagrafica progetto. Lifecycle: SNAPSHOT per progetto_id."""

    progetto_id: str  # HPAN25PIANO1, SPIAGGIA_LOTTO7
    nome: str
    societa_owner_id: SocietaId  # ORTI o INTUR (riusato da type alias esistente)
    business_unit_id: BusinessUnitId  # HOTEL/RESIDENCE/CVM/LIDO/HQ (riusato)
    struttura: Optional[str] = None
    budget_cap_eur: Decimal
    data_inizio: date
    data_fine_prevista: Optional[date] = None
    stato: Literal["PIANIFICATO", "IN_CORSO", "CHIUSO", "ANNULLATO"]
    owner: str
    drive_root_url: Optional[str] = None


class ProgettoVoce(BaseModel):
    """Identità di una riga di scope. Lifecycle: SNAPSHOT per voce_id."""

    voce_id: str  # composito {progetto_id}.{seq}
    progetto_id: str
    codice_interno: str  # "001", "002"
    descrizione: str
    categoria: str  # stringa libera: EDILE, IMPIANTI_EL, OMBRELLONI, ...
    qta: Optional[Decimal] = None
    unita: Optional[str] = None  # pz, mq, cad, set
    fornitore_id: Optional[str] = None  # FK d_anagrafica_fornitori, popolato alla SCELTA
    societa_pagante_id: SocietaId  # default INTUR, ORTI per opex
    note: Optional[str] = None
```

- [ ] **Step 4.4: Run tests to verify PASS**

```bash
pytest tests/test_progetti_schema.py -v
```

Expected: all 16 tests PASS.

- [ ] **Step 4.5: Commit**

```bash
git add core/schemas.py tests/test_progetti_schema.py
git commit -m "feat(progetti): add Progetto + ProgettoVoce top-level models

Progetto (SNAPSHOT) is project anagraphics; ProgettoVoce (SNAPSHOT) is
the identity of a scope row (= Excel row 'cosa da comprare').
fornitore_id nullable, popolato alla SCELTA.
societa_pagante_id riusa SocietaId Literal.

Refs: docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md §2.1-2.2

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Pydantic `ProgettoEvento` con discriminated union

**Files:**
- Modify: `core/schemas.py`
- Modify: `tests/test_progetti_schema.py`

- [ ] **Step 5.1: Add tests for discriminated union dispatch**

Append to `tests/test_progetti_schema.py`:

```python
class TestProgettoEvento:
    def test_preventivo_event_validates(self):
        from core.schemas import ProgettoEvento

        e = ProgettoEvento(
            evento_id="evt-001",
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            tipo_evento="PREVENTIVO",
            data_evento=date(2026, 1, 15),
            data_registrazione="2026-04-26T10:00:00",
            importo_eur=Decimal("375389.25"),
            fornitore_id="anag-amcn-001",
            metadata={
                "tipo": "PREVENTIVO",
                "articolo": "Opere murarie strutturali piano 1",
                "stato_preventivo": "ACCETTATO",
            },
        )
        assert e.metadata.tipo == "PREVENTIVO"
        assert e.metadata.articolo.startswith("Opere")

    def test_impegno_event_validates_with_rate(self):
        from core.schemas import ProgettoEvento

        e = ProgettoEvento(
            evento_id="evt-002",
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            tipo_evento="IMPEGNO",
            data_evento=date(2026, 2, 27),
            data_registrazione="2026-04-26T10:00:00",
            importo_eur=Decimal("375389.25"),
            fornitore_id="anag-amcn-001",
            metadata={
                "tipo": "IMPEGNO",
                "data_firma": "2026-02-27",
                "rate": [
                    {
                        "seq": 1,
                        "data_prevista": "2026-03-15",
                        "importo_eur": "100000.00",
                        "descrizione": "Acconto",
                        "stato": "PIANIFICATA",
                    }
                ],
                "stato_commitment": "FIRMATO",
            },
        )
        assert e.metadata.tipo == "IMPEGNO"
        assert len(e.metadata.rate) == 1
        assert e.metadata.rate[0].seq == 1

    def test_tipo_mismatch_rejected(self):
        from core.schemas import ProgettoEvento

        # tipo_evento=FATTURA ma metadata.tipo=PREVENTIVO -> deve fallire
        with pytest.raises(ValidationError):
            ProgettoEvento(
                evento_id="evt-bad",
                voce_id="x",
                progetto_id="x",
                tipo_evento="FATTURA",
                data_evento=date(2026, 1, 1),
                data_registrazione="2026-04-26T10:00:00",
                metadata={
                    "tipo": "PREVENTIVO",  # mismatch!
                    "articolo": "x",
                    "stato_preventivo": "RICEVUTO",
                },
            )

    def test_documento_event_with_correlato(self):
        from core.schemas import ProgettoEvento

        e = ProgettoEvento(
            evento_id="evt-doc",
            voce_id="SPIAGGIA_LOTTO7.002",
            progetto_id="SPIAGGIA_LOTTO7",
            tipo_evento="DOCUMENTO",
            data_evento=date(2025, 3, 10),
            data_registrazione="2026-04-26T10:00:00",
            metadata={
                "tipo": "DOCUMENTO",
                "tipo_doc": "PREVENTIVO",
                "drive_url": "https://drive.google.com/file/d/xyz",
                "file_name": "Preventivo_Ethimo.pdf",
                "file_hash_md5": "deadbeef",
                "correlato_evento_id": "evt-prev-ethimo",
            },
        )
        assert e.metadata.correlato_evento_id == "evt-prev-ethimo"

    def test_serialization_roundtrip(self):
        """Ensure model_dump → model_validate roundtrip preserves data."""
        from core.schemas import ProgettoEvento

        original = ProgettoEvento(
            evento_id="evt-rt",
            voce_id="x",
            progetto_id="x",
            tipo_evento="PAGAMENTO",
            data_evento=date(2026, 5, 14),
            data_registrazione="2026-04-26T10:00:00",
            importo_eur=Decimal("100.00"),
            metadata={
                "tipo": "PAGAMENTO",
                "data_valuta": "2026-05-14",
                "metodo": "BONIFICO",
                "importo_pagato_eur": "100.00",
                "copre_fatture": ["evt-f-1"],
            },
        )
        dumped = original.model_dump(mode="json")
        restored = ProgettoEvento.model_validate(dumped)
        assert restored.metadata.tipo == "PAGAMENTO"
        assert restored.metadata.metodo == "BONIFICO"
```

- [ ] **Step 5.2: Run tests to verify FAIL**

```bash
pytest tests/test_progetti_schema.py::TestProgettoEvento -v
```

Expected: `ImportError` on `ProgettoEvento`.

- [ ] **Step 5.3: Implement `ProgettoEvento` with discriminated union**

First, update the imports section at the top of `core/schemas.py` to include `Annotated`, `Union`, `Field`, `model_validator`:

```python
from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Optional, Union  # ← add Annotated, Union

from pydantic import BaseModel, Field, field_validator, model_validator  # ← add Field, model_validator
```

Then append after `DocumentoMeta`:

```python
# Type alias for discriminated metadata (Pydantic v2 union with discriminator on `tipo` field)
ProgettoEventoMetadata = Annotated[
    Union[
        PreventivoMeta,
        ImpegnoMeta,
        FatturaMeta,
        PagamentoMeta,
        DocumentoMeta,
    ],
    Field(discriminator="tipo"),
]


class ProgettoEvento(BaseModel):
    """Evento immutabile sul thread di una voce. Lifecycle: APPEND."""

    evento_id: str  # UUID
    voce_id: str  # FK ProgettoVoce
    progetto_id: str  # denormalized for query speed
    tipo_evento: Literal["PREVENTIVO", "IMPEGNO", "FATTURA", "PAGAMENTO", "DOCUMENTO"]
    data_evento: date
    data_registrazione: str  # ISO datetime
    importo_eur: Optional[Decimal] = None
    fornitore_id: Optional[str] = None
    metadata: ProgettoEventoMetadata
    file_sorgente: Optional[str] = None  # drive_url del file che ha generato l'evento

    @model_validator(mode="after")
    def tipo_consistency(self) -> ProgettoEvento:
        """metadata.tipo deve combaciare con tipo_evento (I1)."""
        if self.metadata.tipo != self.tipo_evento:
            raise ValueError(
                f"tipo_evento={self.tipo_evento!r} but metadata.tipo={self.metadata.tipo!r}"
            )
        return self
```

- [ ] **Step 5.4: Run tests to verify PASS**

```bash
pytest tests/test_progetti_schema.py -v
```

Expected: all 21 tests PASS (16 from previous + 5 new).

- [ ] **Step 5.5: Commit**

```bash
git add core/schemas.py tests/test_progetti_schema.py
git commit -m "feat(progetti): add ProgettoEvento with Pydantic discriminated union

ProgettoEventoMetadata = Annotated[Union[5 sub-models], Field(discriminator='tipo')]
dispatches metadata validation based on tipo_evento. model_validator
enforces consistency between tipo_evento and metadata.tipo (I1 strict
validation gate).

Refs: docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md §2.3

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Add table IDs to `core/config.py`

**Files:**
- Modify: `core/config.py`

- [ ] **Step 6.1: Add new constants**

Edit `core/config.py`. Find the `# Fact tables` section and add at the end (before `# Dimension tables`):

```python
F_PROGETTO_VOCI             = _t("f_progetto_voci")
F_PROGETTO_EVENTI           = _t("f_progetto_eventi")
```

Find the `# Dimension tables` section, add at the end:

```python
D_PROGETTI                  = _t("d_progetti")
```

Find the `# Views` section, add at the end:

```python
V_PROGETTO_VOCI_STATO       = _t("v_progetto_voci_stato")
```

- [ ] **Step 6.2: Verify imports work**

```bash
python -c "from core.config import D_PROGETTI, F_PROGETTO_VOCI, F_PROGETTO_EVENTI, V_PROGETTO_VOCI_STATO; print(D_PROGETTI, F_PROGETTO_VOCI, F_PROGETTO_EVENTI, V_PROGETTO_VOCI_STATO)"
```

Expected:
```
hotelops-suite.hotelops.d_progetti hotelops-suite.hotelops.f_progetto_voci hotelops-suite.hotelops.f_progetto_eventi hotelops-suite.hotelops.v_progetto_voci_stato
```

- [ ] **Step 6.3: Commit**

```bash
git add core/config.py
git commit -m "feat(progetti): add D_PROGETTI / F_PROGETTO_VOCI / F_PROGETTO_EVENTI / V_PROGETTO_VOCI_STATO table IDs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: DDL script `create_progetti_tables.py`

**Files:**
- Create: `core/bq/load/create_progetti_tables.py`

- [ ] **Step 7.1: Write the DDL script**

Create `core/bq/load/create_progetti_tables.py`:

```python
#!/usr/bin/env python3
"""
DDL idempotente per le 3 tabelle Projects (event-sourced Step 1).

Crea (CREATE TABLE IF NOT EXISTS):
- d_progetti                (SNAPSHOT)
- f_progetto_voci           (SNAPSHOT)
- f_progetto_eventi         (APPEND, PARTITION BY DATE(data_evento))

Usage:
    python -m core.bq.load.create_progetti_tables
    python -m core.bq.load.create_progetti_tables --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.bq.client import get_client
from core.config import D_PROGETTI, F_PROGETTO_EVENTI, F_PROGETTO_VOCI

DDL_D_PROGETTI = f"""
CREATE TABLE IF NOT EXISTS `{D_PROGETTI}` (
    progetto_id          STRING NOT NULL,
    nome                 STRING NOT NULL,
    societa_owner_id     STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    struttura            STRING,
    budget_cap_eur       NUMERIC NOT NULL,
    data_inizio          DATE NOT NULL,
    data_fine_prevista   DATE,
    stato                STRING NOT NULL,
    owner                STRING NOT NULL,
    drive_root_url       STRING,
    data_caricamento     TIMESTAMP NOT NULL
)
"""

DDL_F_PROGETTO_VOCI = f"""
CREATE TABLE IF NOT EXISTS `{F_PROGETTO_VOCI}` (
    voce_id              STRING NOT NULL,
    progetto_id          STRING NOT NULL,
    codice_interno       STRING NOT NULL,
    descrizione          STRING NOT NULL,
    categoria            STRING NOT NULL,
    qta                  NUMERIC,
    unita                STRING,
    fornitore_id         STRING,
    societa_pagante_id   STRING NOT NULL,
    note                 STRING,
    data_caricamento     TIMESTAMP NOT NULL
)
"""

DDL_F_PROGETTO_EVENTI = f"""
CREATE TABLE IF NOT EXISTS `{F_PROGETTO_EVENTI}` (
    evento_id            STRING NOT NULL,
    voce_id              STRING NOT NULL,
    progetto_id          STRING NOT NULL,
    tipo_evento          STRING NOT NULL,
    data_evento          DATE NOT NULL,
    data_registrazione   TIMESTAMP NOT NULL,
    importo_eur          NUMERIC,
    fornitore_id         STRING,
    metadata             JSON NOT NULL,
    file_sorgente        STRING
)
PARTITION BY DATE(data_evento)
CLUSTER BY progetto_id, voce_id, tipo_evento
"""

DDL_STATEMENTS = [
    ("d_progetti", DDL_D_PROGETTI),
    ("f_progetto_voci", DDL_F_PROGETTO_VOCI),
    ("f_progetto_eventi", DDL_F_PROGETTO_EVENTI),
]


def setup_logger() -> logging.Logger:
    log = logging.getLogger("create_progetti_tables")
    log.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Print DDL without executing")
    args = p.parse_args()

    log = setup_logger()
    log.info("DDL projects tables — idempotent (CREATE TABLE IF NOT EXISTS)")

    if args.dry_run:
        for name, ddl in DDL_STATEMENTS:
            log.info(f"--- {name} ---")
            print(ddl)
        return 0

    client = get_client()
    for name, ddl in DDL_STATEMENTS:
        log.info(f"Creating {name}...")
        job = client.query(ddl)
        job.result()  # blocks until complete
        log.info(f"  ✓ {name}")

    log.info("All 3 tables ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7.2: Dry-run to verify DDL is well-formed**

```bash
cd /Users/stefanodellapietra/dev/Projects/hotelops
python -m core.bq.load.create_progetti_tables --dry-run
```

Expected: prints 3 DDL statements with table IDs `hotelops-suite.hotelops.d_progetti`, etc.

- [ ] **Step 7.3: Execute DDL on real BigQuery**

```bash
python -m core.bq.load.create_progetti_tables
```

Expected output:
```
INFO DDL projects tables — idempotent (CREATE TABLE IF NOT EXISTS)
INFO Creating d_progetti...
INFO   ✓ d_progetti
INFO Creating f_progetto_voci...
INFO   ✓ f_progetto_voci
INFO Creating f_progetto_eventi...
INFO   ✓ f_progetto_eventi
INFO All 3 tables ready.
```

Verify in BQ:
```bash
bq ls hotelops-suite:hotelops | grep -E "(d_progetti|f_progetto)"
```

Expected: 3 lines listing the 3 tables.

- [ ] **Step 7.4: Re-run to verify idempotency**

```bash
python -m core.bq.load.create_progetti_tables
```

Expected: same output, no errors (CREATE TABLE IF NOT EXISTS is no-op).

- [ ] **Step 7.5: Commit**

```bash
git add core/bq/load/create_progetti_tables.py
git commit -m "feat(progetti): DDL idempotent for 3 event-sourced tables

CREATE TABLE IF NOT EXISTS for d_progetti, f_progetto_voci, f_progetto_eventi.
f_progetto_eventi partitioned by DATE(data_evento), clustered by
progetto_id+voce_id+tipo_evento for query efficiency.

Refs: docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md §2

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Seed loader `seed_progetti_step1.py`

**Files:**
- Create: `core/bq/load/seed_progetti_step1.py`

- [ ] **Step 8.1: Write the seed loader with inline data**

Create `core/bq/load/seed_progetti_step1.py`:

```python
#!/usr/bin/env python3
"""
Seed loader Step 1 — popola HPAN25PIANO1 + SPIAGGIA_LOTTO7 con dati inline.

Idempotente: prima DELETE, poi INSERT (per i due progetti del seed).

Carica:
- 2 righe in d_progetti
- 10 righe in f_progetto_voci (5 HPAN + 5 SPIAGGIA)
- 19 righe in f_progetto_eventi (11 HPAN + 8 SPIAGGIA)

Usage:
    python -m core.bq.load.seed_progetti_step1
    python -m core.bq.load.seed_progetti_step1 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from decimal import Decimal

from core.bq.client import get_client
from core.config import D_PROGETTI, F_PROGETTO_EVENTI, F_PROGETTO_VOCI
from core.schemas import (
    Progetto,
    ProgettoEvento,
    ProgettoVoce,
    Rata,
)

NOW_ISO = datetime.utcnow().isoformat()
SEED_PROGETTI_IDS = ("HPAN25PIANO1", "SPIAGGIA_LOTTO7")


def build_progetti() -> list[Progetto]:
    return [
        Progetto(
            progetto_id="HPAN25PIANO1",
            nome="Camere Primo Piano - Hotel Panorama",
            societa_owner_id="INTUR",
            business_unit_id="HOTEL",
            struttura="Hotel Panorama",
            budget_cap_eur=Decimal("1200000.00"),
            data_inizio=date(2026, 2, 1),
            stato="IN_CORSO",
            owner="Stefano Della Pietra Jr",
            drive_root_url="investimenti2026/HPAN25PIANO1/",
        ),
        Progetto(
            progetto_id="SPIAGGIA_LOTTO7",
            nome="Spiaggia Lotto 7 Maiori",
            societa_owner_id="INTUR",
            business_unit_id="LIDO",
            struttura="Stabilimento Lido 7",
            budget_cap_eur=Decimal("490000.00"),
            data_inizio=date(2025, 3, 1),
            stato="PIANIFICATO",
            owner="Stefano Della Pietra Jr",
            drive_root_url=None,
        ),
    ]


def build_voci() -> list[ProgettoVoce]:
    return [
        # ── HPAN25PIANO1 (5 voci) ──
        ProgettoVoce(
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            codice_interno="001",
            descrizione="Opere murarie strutturali piano 1 (AMCN)",
            categoria="EDILE",
            societa_pagante_id="INTUR",
            fornitore_id="anag-amcn-001",
        ),
        ProgettoVoce(
            voce_id="HPAN25PIANO1.002",
            progetto_id="HPAN25PIANO1",
            codice_interno="002",
            descrizione="Impianti elettrici (STE)",
            categoria="IMPIANTI_EL",
            societa_pagante_id="INTUR",
            fornitore_id="anag-ste-002",
        ),
        ProgettoVoce(
            voce_id="HPAN25PIANO1.008",
            progetto_id="HPAN25PIANO1",
            codice_interno="008",
            descrizione="Direzione lavori (Amalia Pisacane)",
            categoria="CONSULENZA",
            societa_pagante_id="INTUR",
            fornitore_id=None,  # ancora candidato
        ),
        ProgettoVoce(
            voce_id="HPAN25PIANO1.010",
            progetto_id="HPAN25PIANO1",
            codice_interno="010",
            descrizione="Project Management (Hospitality Project)",
            categoria="CONSULENZA",
            societa_pagante_id="ORTI",  # opex via ORTI
            fornitore_id=None,
        ),
        ProgettoVoce(
            voce_id="HPAN25PIANO1.013",
            progetto_id="HPAN25PIANO1",
            codice_interno="013",
            descrizione="Falegnameria armadi (Rino Cuomo)",
            categoria="ARREDI_CUSTOM",
            societa_pagante_id="INTUR",
            fornitore_id=None,
            note="Stima da Excel; nessun preventivo ricevuto",
        ),
        # ── SPIAGGIA_LOTTO7 (5 voci) ──
        ProgettoVoce(
            voce_id="SPIAGGIA_LOTTO7.001",
            progetto_id="SPIAGGIA_LOTTO7",
            codice_interno="001",
            descrizione="Ombrelloni Pagoda 164pz",
            categoria="OMBRELLONI",
            qta=Decimal("164"),
            unita="pz",
            societa_pagante_id="INTUR",
            fornitore_id=None,  # 4 preventivi in valutazione
        ),
        ProgettoVoce(
            voce_id="SPIAGGIA_LOTTO7.002",
            progetto_id="SPIAGGIA_LOTTO7",
            codice_interno="002",
            descrizione="Arredo Ethimo (cabane+sedie+tavolini+lampade)",
            categoria="ARREDI",
            societa_pagante_id="INTUR",
            fornitore_id=None,
        ),
        ProgettoVoce(
            voce_id="SPIAGGIA_LOTTO7.005",
            progetto_id="SPIAGGIA_LOTTO7",
            codice_interno="005",
            descrizione="Giochi da spiaggia (Kompan)",
            categoria="GIOCHI",
            societa_pagante_id="INTUR",
            fornitore_id=None,
        ),
        ProgettoVoce(
            voce_id="SPIAGGIA_LOTTO7.011",
            progetto_id="SPIAGGIA_LOTTO7",
            codice_interno="011",
            descrizione="Vela motorizzata (Similis)",
            categoria="STRUTTURA",
            societa_pagante_id="INTUR",
            fornitore_id=None,
        ),
        ProgettoVoce(
            voce_id="SPIAGGIA_LOTTO7.012",
            progetto_id="SPIAGGIA_LOTTO7",
            codice_interno="012",
            descrizione="Buvette",
            categoria="STRUTTURA",
            societa_pagante_id="INTUR",
            fornitore_id=None,
            note="Da definire fornitore",
        ),
    ]


def build_eventi() -> list[ProgettoEvento]:
    return [
        # ── HPAN25PIANO1.001 AMCN: PREV → IMPEGNO 375K → IMPEGNO 413K (overrun) → 3 FATT ──
        ProgettoEvento(
            evento_id="evt-h001-prev",
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            tipo_evento="PREVENTIVO",
            data_evento=date(2026, 1, 15),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("375389.25"),
            fornitore_id="anag-amcn-001",
            metadata={
                "tipo": "PREVENTIVO",
                "articolo": "Opere murarie strutturali piano 1",
                "stato_preventivo": "ACCETTATO",
                "note": "OFFERTA FIRMATA HOTEL PANORAMA.pdf",
            },
        ),
        ProgettoEvento(
            evento_id="evt-h001-imp1",
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            tipo_evento="IMPEGNO",
            data_evento=date(2026, 2, 27),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("375389.25"),
            fornitore_id="anag-amcn-001",
            metadata={
                "tipo": "IMPEGNO",
                "from_preventivo_evento_id": "evt-h001-prev",
                "data_firma": "2026-02-27",
                "rate": [],
                "stato_commitment": "FIRMATO",
            },
        ),
        ProgettoEvento(
            evento_id="evt-h001-imp2",
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            tipo_evento="IMPEGNO",
            data_evento=date(2026, 3, 26),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("412928.18"),
            fornitore_id="anag-amcn-001",
            metadata={
                "tipo": "IMPEGNO",
                "data_firma": "2026-02-27",
                "rate": [],
                "stato_commitment": "IN_CORSO",
                "motivo_variazione": "Overrun amianto - Ft 02-26 INTUR Saldo_AMIANTO",
            },
        ),
        ProgettoEvento(
            evento_id="evt-h001-fatt1",
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            tipo_evento="FATTURA",
            data_evento=date(2026, 3, 14),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("44000.00"),
            fornitore_id="anag-amcn-001",
            metadata={
                "tipo": "FATTURA",
                "numero_fattura": "FPR 23/26",
                "data_emissione": "2026-03-14",
                "tipo_doc": "FT-RC",
                "condizioni_pagamento": "Bonifico 90gg DF FM",
                "data_scadenza": "2026-06-30",
                "copre_rate": [],
            },
        ),
        ProgettoEvento(
            evento_id="evt-h001-fatt2",
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            tipo_evento="FATTURA",
            data_evento=date(2026, 3, 14),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("56732.02"),
            fornitore_id="anag-amcn-001",
            metadata={
                "tipo": "FATTURA",
                "numero_fattura": "FPR 24/26",
                "data_emissione": "2026-03-14",
                "tipo_doc": "FT-RC",
                "condizioni_pagamento": "Bonifico 90gg DF FM",
                "data_scadenza": "2026-06-30",
                "copre_rate": [],
            },
        ),
        ProgettoEvento(
            evento_id="evt-h001-fatt3",
            voce_id="HPAN25PIANO1.001",
            progetto_id="HPAN25PIANO1",
            tipo_evento="FATTURA",
            data_evento=date(2026, 3, 26),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("60157.92"),
            fornitore_id="anag-amcn-001",
            metadata={
                "tipo": "FATTURA",
                "numero_fattura": "FPR 31/26",
                "data_emissione": "2026-03-26",
                "tipo_doc": "FT-RC",
                "condizioni_pagamento": "Bonifico 90gg DF FM",
                "data_scadenza": "2026-06-30",
                "copre_rate": [],
            },
        ),
        # ── HPAN25PIANO1.002 STE: PREV → IMPEGNO 107K → 1 FATT ──
        ProgettoEvento(
            evento_id="evt-h002-prev",
            voce_id="HPAN25PIANO1.002",
            progetto_id="HPAN25PIANO1",
            tipo_evento="PREVENTIVO",
            data_evento=date(2026, 1, 20),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("101705.84"),
            fornitore_id="anag-ste-002",
            metadata={
                "tipo": "PREVENTIVO",
                "articolo": "Impianti elettrici e speciali",
                "stato_preventivo": "ACCETTATO",
                "note": "imp_elettrico_e_speciali_COMPUTO METRICO",
            },
        ),
        ProgettoEvento(
            evento_id="evt-h002-imp",
            voce_id="HPAN25PIANO1.002",
            progetto_id="HPAN25PIANO1",
            tipo_evento="IMPEGNO",
            data_evento=date(2026, 2, 27),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("106791.13"),
            fornitore_id="anag-ste-002",
            metadata={
                "tipo": "IMPEGNO",
                "from_preventivo_evento_id": "evt-h002-prev",
                "data_firma": "2026-02-27",
                "rate": [],
                "stato_commitment": "IN_CORSO",
            },
        ),
        ProgettoEvento(
            evento_id="evt-h002-fatt",
            voce_id="HPAN25PIANO1.002",
            progetto_id="HPAN25PIANO1",
            tipo_evento="FATTURA",
            data_evento=date(2026, 3, 31),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("30000.00"),
            fornitore_id="anag-ste-002",
            metadata={
                "tipo": "FATTURA",
                "numero_fattura": "STE-FT-001",
                "data_emissione": "2026-03-31",
                "tipo_doc": "FT",
                "condizioni_pagamento": "Bonifico 60gg DF",
                "copre_rate": [],
            },
        ),
        # ── HPAN25PIANO1.008 Pisacane: 1 PREV ──
        ProgettoEvento(
            evento_id="evt-h008-prev",
            voce_id="HPAN25PIANO1.008",
            progetto_id="HPAN25PIANO1",
            tipo_evento="PREVENTIVO",
            data_evento=date(2026, 1, 25),
            data_registrazione=NOW_ISO,
            importo_eur=None,
            fornitore_id=None,
            metadata={
                "tipo": "PREVENTIVO",
                "articolo": "Direzione lavori ingegneria",
                "stato_preventivo": "RICEVUTO",
                "note": "Importo da chiarire - PREVENTIVO_PENDING",
            },
        ),
        # ── HPAN25PIANO1.010 Hospitality Project: 1 PREV (società ORTI) ──
        ProgettoEvento(
            evento_id="evt-h010-prev",
            voce_id="HPAN25PIANO1.010",
            progetto_id="HPAN25PIANO1",
            tipo_evento="PREVENTIVO",
            data_evento=date(2026, 1, 30),
            data_registrazione=NOW_ISO,
            importo_eur=None,
            fornitore_id=None,
            metadata={
                "tipo": "PREVENTIVO",
                "articolo": "Project Management",
                "stato_preventivo": "RICEVUTO",
                "note": "PM fee - società pagante ORTI (unico opex del progetto)",
            },
        ),
        # ── HPAN25PIANO1.013 Rino Cuomo: 0 eventi (voce orfana, solo identità) ──
        # ── SPIAGGIA_LOTTO7.001 Pagoda: 4 PREVENTIVO ──
        ProgettoEvento(
            evento_id="evt-s001-prev-armagi",
            voce_id="SPIAGGIA_LOTTO7.001",
            progetto_id="SPIAGGIA_LOTTO7",
            tipo_evento="PREVENTIVO",
            data_evento=date(2026, 4, 17),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("31324.00"),
            fornitore_id="anag-armagi-001",
            metadata={
                "tipo": "PREVENTIVO",
                "articolo": "Pagoda 164pz (82 Ø220 + 82 Ø240)",
                "stato_preventivo": "RICEVUTO",
            },
        ),
        ProgettoEvento(
            evento_id="evt-s001-prev-magnani",
            voce_id="SPIAGGIA_LOTTO7.001",
            progetto_id="SPIAGGIA_LOTTO7",
            tipo_evento="PREVENTIVO",
            data_evento=date(2026, 4, 17),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("35620.80"),
            fornitore_id="anag-magnani-001",
            metadata={
                "tipo": "PREVENTIVO",
                "articolo": "Pagoda 164pz",
                "stato_preventivo": "RICEVUTO",
                "note": "Sconto 20% applicato",
            },
        ),
        ProgettoEvento(
            evento_id="evt-s001-prev-maffei",
            voce_id="SPIAGGIA_LOTTO7.001",
            progetto_id="SPIAGGIA_LOTTO7",
            tipo_evento="PREVENTIVO",
            data_evento=date(2026, 4, 20),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("37556.00"),
            fornitore_id="anag-maffei-001",
            metadata={
                "tipo": "PREVENTIVO",
                "articolo": "Pagoda 220+240",
                "stato_preventivo": "RICEVUTO",
                "note": "Porto franco",
            },
        ),
        ProgettoEvento(
            evento_id="evt-s001-prev-azzolini",
            voce_id="SPIAGGIA_LOTTO7.001",
            progetto_id="SPIAGGIA_LOTTO7",
            tipo_evento="PREVENTIVO",
            data_evento=date(2025, 3, 3),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("122098.00"),
            fornitore_id="anag-azzolini-001",
            metadata={
                "tipo": "PREVENTIVO",
                "numero_preventivo": "25/00392",
                "data_preventivo": "2025-03-03",
                "articolo": "Ombrellone Pagoda 220 + 240 + Lettini Rail (bundle)",
                "stato_preventivo": "RICEVUTO",
                "note": "Non competitivo (bundle, vs alternatives)",
            },
        ),
        # ── SPIAGGIA_LOTTO7.002 Ethimo: 1 PREVENTIVO + 1 DOCUMENTO ──
        ProgettoEvento(
            evento_id="evt-s002-prev-ethimo",
            voce_id="SPIAGGIA_LOTTO7.002",
            progetto_id="SPIAGGIA_LOTTO7",
            tipo_evento="PREVENTIVO",
            data_evento=date(2025, 3, 10),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("84851.40"),
            fornitore_id="anag-ethimo-001",
            metadata={
                "tipo": "PREVENTIVO",
                "data_preventivo": "2025-03-10",
                "articolo": "Arredo esterno (KILT, KNIT, GAIA, ALLAPERTO)",
                "stato_preventivo": "RICEVUTO",
            },
        ),
        ProgettoEvento(
            evento_id="evt-s002-doc-ethimo",
            voce_id="SPIAGGIA_LOTTO7.002",
            progetto_id="SPIAGGIA_LOTTO7",
            tipo_evento="DOCUMENTO",
            data_evento=date(2025, 3, 10),
            data_registrazione=NOW_ISO,
            metadata={
                "tipo": "DOCUMENTO",
                "tipo_doc": "PREVENTIVO",
                "drive_url": "https://drive.google.com/open?id=1gutGg76LwglxG5dCbHQ3CLwRMzVwO-Pi",
                "file_name": "Preventivo_Ethimo.pdf",
                "file_hash_md5": "ethimo-pdf-hash-placeholder",
                "correlato_evento_id": "evt-s002-prev-ethimo",
            },
            file_sorgente="https://drive.google.com/open?id=1gutGg76LwglxG5dCbHQ3CLwRMzVwO-Pi",
        ),
        # ── SPIAGGIA_LOTTO7.005 Kompan: 1 PREVENTIVO ──
        ProgettoEvento(
            evento_id="evt-s005-prev-kompan",
            voce_id="SPIAGGIA_LOTTO7.005",
            progetto_id="SPIAGGIA_LOTTO7",
            tipo_evento="PREVENTIVO",
            data_evento=date(2025, 3, 10),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("13550.00"),
            fornitore_id="anag-kompan-001",
            metadata={
                "tipo": "PREVENTIVO",
                "numero_preventivo": "SQ221807-2",
                "data_preventivo": "2025-03-10",
                "validita_fino_a": "2025-06-10",
                "articolo": "Sand Desk + Delfino + Capanna + Ape (giochi spiaggia)",
                "stato_preventivo": "RICEVUTO",
                "note": "Pagamento 50% conferma + 50% a 30gg",
            },
        ),
        # ── SPIAGGIA_LOTTO7.011 Vela Similis: 1 PREVENTIVO ──
        ProgettoEvento(
            evento_id="evt-s011-prev-similis",
            voce_id="SPIAGGIA_LOTTO7.011",
            progetto_id="SPIAGGIA_LOTTO7",
            tipo_evento="PREVENTIVO",
            data_evento=date(2025, 3, 5),
            data_registrazione=NOW_ISO,
            importo_eur=Decimal("26101.39"),
            fornitore_id="anag-similis-001",
            metadata={
                "tipo": "PREVENTIVO",
                "numero_preventivo": "P25-00125",
                "data_preventivo": "2025-03-05",
                "articolo": "Vela motorizzata SunSquare SQK-I",
                "stato_preventivo": "RICEVUTO",
            },
        ),
        # ── SPIAGGIA_LOTTO7.012 Buvette: 0 eventi (voce orfana) ──
    ]


def progetto_to_row(p: Progetto) -> dict:
    d = p.model_dump(mode="json")
    d["data_caricamento"] = NOW_ISO
    return d


def voce_to_row(v: ProgettoVoce) -> dict:
    d = v.model_dump(mode="json")
    d["data_caricamento"] = NOW_ISO
    return d


def evento_to_row(e: ProgettoEvento) -> dict:
    d = e.model_dump(mode="json")
    # BQ JSON column: serialize metadata dict → JSON string
    d["metadata"] = json.dumps(d["metadata"])
    return d


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Skip BQ writes, print counts")
    args = p.parse_args()

    log = logging.getLogger("seed_progetti_step1")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    progetti = build_progetti()
    voci = build_voci()
    eventi = build_eventi()

    log.info(f"Built: {len(progetti)} progetti, {len(voci)} voci, {len(eventi)} eventi")
    assert len(progetti) == 2, "Expected 2 progetti"
    assert len(voci) == 10, "Expected 10 voci"
    assert len(eventi) == 19, "Expected 19 eventi"

    if args.dry_run:
        log.info("--dry-run: skipping BQ writes")
        return 0

    client = get_client()

    # 1. DELETE existing rows for the seed progetti (idempotency)
    seed_ids_sql = ",".join(f"'{pid}'" for pid in SEED_PROGETTI_IDS)
    for table, key in [
        (D_PROGETTI, "progetto_id"),
        (F_PROGETTO_VOCI, "progetto_id"),
        (F_PROGETTO_EVENTI, "progetto_id"),
    ]:
        log.info(f"DELETE FROM {table} WHERE {key} IN ({SEED_PROGETTI_IDS})")
        client.query(f"DELETE FROM `{table}` WHERE {key} IN ({seed_ids_sql})").result()

    # 2. INSERT
    log.info(f"INSERT {len(progetti)} rows into {D_PROGETTI}")
    errors = client.insert_rows_json(D_PROGETTI, [progetto_to_row(p) for p in progetti])
    if errors:
        log.error(f"d_progetti errors: {errors}")
        return 1

    log.info(f"INSERT {len(voci)} rows into {F_PROGETTO_VOCI}")
    errors = client.insert_rows_json(F_PROGETTO_VOCI, [voce_to_row(v) for v in voci])
    if errors:
        log.error(f"f_progetto_voci errors: {errors}")
        return 1

    log.info(f"INSERT {len(eventi)} rows into {F_PROGETTO_EVENTI}")
    errors = client.insert_rows_json(F_PROGETTO_EVENTI, [evento_to_row(e) for e in eventi])
    if errors:
        log.error(f"f_progetto_eventi errors: {errors}")
        return 1

    log.info("Seed Step 1 completato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8.2: Dry-run for sanity**

```bash
cd /Users/stefanodellapietra/dev/Projects/hotelops
python -m core.bq.load.seed_progetti_step1 --dry-run
```

Expected:
```
INFO Built: 2 progetti, 10 voci, 19 eventi
INFO --dry-run: skipping BQ writes
```

If counts mismatch → fix `build_*` functions.

- [ ] **Step 8.3: Execute on real BigQuery**

```bash
python -m core.bq.load.seed_progetti_step1
```

Expected:
```
INFO Built: 2 progetti, 10 voci, 19 eventi
INFO DELETE FROM ... WHERE progetto_id IN ('HPAN25PIANO1', 'SPIAGGIA_LOTTO7')
... (3 DELETE log lines)
INFO INSERT 2 rows into hotelops-suite.hotelops.d_progetti
INFO INSERT 10 rows into hotelops-suite.hotelops.f_progetto_voci
INFO INSERT 19 rows into hotelops-suite.hotelops.f_progetto_eventi
INFO Seed Step 1 completato.
```

Verify counts:
```bash
bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) AS n_progetti FROM \`hotelops-suite.hotelops.d_progetti\` WHERE progetto_id IN ('HPAN25PIANO1', 'SPIAGGIA_LOTTO7')"
bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) AS n_voci FROM \`hotelops-suite.hotelops.f_progetto_voci\` WHERE progetto_id IN ('HPAN25PIANO1', 'SPIAGGIA_LOTTO7')"
bq query --use_legacy_sql=false --format=csv "SELECT COUNT(*) AS n_eventi FROM \`hotelops-suite.hotelops.f_progetto_eventi\` WHERE progetto_id IN ('HPAN25PIANO1', 'SPIAGGIA_LOTTO7')"
```

Expected: 2, 10, 19.

- [ ] **Step 8.4: Re-run to verify idempotency**

```bash
python -m core.bq.load.seed_progetti_step1
```

Expected: same output, counts still 2/10/19 (DELETE+INSERT). Run the bq counts again to confirm.

- [ ] **Step 8.5: Commit**

```bash
git add core/bq/load/seed_progetti_step1.py
git commit -m "feat(progetti): seed loader Step 1 with 2 projects + 10 voci + 19 eventi

Inline data (no Excel parsing). Idempotent: DELETE + INSERT for the seed
progetto_ids ('HPAN25PIANO1', 'SPIAGGIA_LOTTO7'). Validates that the same
schema covers a mature project (HPAN25PIANO1: PREV→IMPEGNO→FATT, with
overrun via 2nd IMPEGNO) and an early-stage project (SPIAGGIA_LOTTO7:
multi-preventivo confronto + DOCUMENTO Drive).

Refs: docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md §5

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: View `v_progetto_voci_stato` + deploy

**Files:**
- Create: `core/bq/views/v_progetto_voci_stato.sql`
- Create: `core/bq/load/deploy_view_voci_stato.py`

- [ ] **Step 9.1: Write the view SQL**

Create `core/bq/views/v_progetto_voci_stato.sql`:

```sql
-- v_progetto_voci_stato — Step 1 — risponde alla domanda COSA (Register)
-- Per ogni voce: stato derivato + fornitore scelto + totali impegnato/fatturato/pagato.
-- Latest IMPEGNO vince (I8); fatture/pagamenti aggregati con SUM.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_progetto_voci_stato` AS
WITH latest_impegno AS (
  SELECT voce_id, importo_eur, data_evento, evento_id, metadata
  FROM (
    SELECT
      voce_id,
      importo_eur,
      data_evento,
      evento_id,
      metadata,
      ROW_NUMBER() OVER (
        PARTITION BY voce_id
        ORDER BY data_evento DESC, data_registrazione DESC
      ) AS rn
    FROM `hotelops-suite.hotelops.f_progetto_eventi`
    WHERE tipo_evento = 'IMPEGNO'
  )
  WHERE rn = 1
),
totali_fattura AS (
  SELECT
    voce_id,
    SUM(importo_eur) AS importo_fatturato_eur,
    COUNT(*) AS n_fatture
  FROM `hotelops-suite.hotelops.f_progetto_eventi`
  WHERE tipo_evento = 'FATTURA'
  GROUP BY voce_id
),
totali_pagamento AS (
  SELECT
    voce_id,
    SUM(importo_eur) AS importo_pagato_eur
  FROM `hotelops-suite.hotelops.f_progetto_eventi`
  WHERE tipo_evento = 'PAGAMENTO'
  GROUP BY voce_id
),
n_preventivi AS (
  SELECT
    voce_id,
    COUNT(*) AS n_preventivi
  FROM `hotelops-suite.hotelops.f_progetto_eventi`
  WHERE tipo_evento = 'PREVENTIVO'
  GROUP BY voce_id
)
SELECT
  v.voce_id,
  v.progetto_id,
  v.codice_interno,
  v.descrizione,
  v.categoria,
  v.fornitore_id AS fornitore_scelto_id,
  v.societa_pagante_id,
  li.importo_eur AS importo_impegnato_eur,
  li.data_evento AS data_impegno,
  COALESCE(tf.importo_fatturato_eur, 0) AS importo_fatturato_eur,
  COALESCE(tp.importo_pagato_eur, 0) AS importo_pagato_eur,
  COALESCE(li.importo_eur, 0) - COALESCE(tf.importo_fatturato_eur, 0) AS residuo_impegno_eur,
  COALESCE(tf.importo_fatturato_eur, 0) - COALESCE(li.importo_eur, 0) AS delta_overrun_eur,
  COALESCE(np.n_preventivi, 0) AS n_preventivi,
  COALESCE(tf.n_fatture, 0) AS n_fatture,
  CASE
    WHEN li.importo_eur IS NOT NULL
         AND COALESCE(tp.importo_pagato_eur, 0) >= li.importo_eur THEN 'CHIUSO'
    WHEN COALESCE(tf.importo_fatturato_eur, 0) > 0 THEN 'IN_CORSO_FATTURATO'
    WHEN li.importo_eur IS NOT NULL THEN 'IMPEGNATO'
    WHEN COALESCE(np.n_preventivi, 0) > 0 THEN 'IN_VALUTAZIONE'
    ELSE 'IDENTIFICATO'
  END AS stato
FROM `hotelops-suite.hotelops.f_progetto_voci` v
LEFT JOIN latest_impegno li USING (voce_id)
LEFT JOIN totali_fattura tf USING (voce_id)
LEFT JOIN totali_pagamento tp USING (voce_id)
LEFT JOIN n_preventivi np USING (voce_id)
```

- [ ] **Step 9.2: Write deploy script**

Create `core/bq/load/deploy_view_voci_stato.py`:

```python
#!/usr/bin/env python3
"""Deploy v_progetto_voci_stato view to BigQuery.

Idempotente (CREATE OR REPLACE VIEW).

Usage:
    python -m core.bq.load.deploy_view_voci_stato
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from core.bq.client import get_client

VIEW_SQL_PATH = (
    Path(__file__).resolve().parents[2] / "bq" / "views" / "v_progetto_voci_stato.sql"
)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("deploy_view_voci_stato")

    if not VIEW_SQL_PATH.exists():
        log.error(f"View SQL not found: {VIEW_SQL_PATH}")
        return 1

    sql = VIEW_SQL_PATH.read_text(encoding="utf-8")
    log.info(f"Deploying {VIEW_SQL_PATH.name} ({len(sql)} chars)")

    client = get_client()
    client.query(sql).result()

    log.info("View deployed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 9.3: Deploy the view**

```bash
cd /Users/stefanodellapietra/dev/Projects/hotelops
python -m core.bq.load.deploy_view_voci_stato
```

Expected:
```
INFO Deploying v_progetto_voci_stato.sql (~2500 chars)
INFO View deployed.
```

- [ ] **Step 9.4: Verify the view returns 10 rows with correct stati**

```bash
bq query --use_legacy_sql=false --format=prettyjson \
  "SELECT voce_id, stato, importo_impegnato_eur, importo_fatturato_eur, n_preventivi, n_fatture
   FROM \`hotelops-suite.hotelops.v_progetto_voci_stato\`
   ORDER BY progetto_id, codice_interno"
```

Expected: 10 rows. Sanity assertions:
- `HPAN25PIANO1.001`: stato=`IN_CORSO_FATTURATO`, importo_impegnato=412928.18, importo_fatturato=160889.94 (44+56732+60157.92), n_fatture=3
- `HPAN25PIANO1.002`: stato=`IN_CORSO_FATTURATO`, importo_impegnato=106791.13, importo_fatturato=30000, n_fatture=1
- `HPAN25PIANO1.008`: stato=`IN_VALUTAZIONE`, importo_impegnato=null, n_preventivi=1
- `HPAN25PIANO1.010`: stato=`IN_VALUTAZIONE`, n_preventivi=1
- `HPAN25PIANO1.013`: stato=`IDENTIFICATO`, n_preventivi=0
- `SPIAGGIA_LOTTO7.001`: stato=`IN_VALUTAZIONE`, n_preventivi=4
- `SPIAGGIA_LOTTO7.002`: stato=`IN_VALUTAZIONE`, n_preventivi=1
- `SPIAGGIA_LOTTO7.005`: stato=`IN_VALUTAZIONE`, n_preventivi=1
- `SPIAGGIA_LOTTO7.011`: stato=`IN_VALUTAZIONE`, n_preventivi=1
- `SPIAGGIA_LOTTO7.012`: stato=`IDENTIFICATO`, n_preventivi=0

Aggregate sanity:
```bash
bq query --use_legacy_sql=false --format=csv \
  "SELECT stato, COUNT(*) AS n FROM \`hotelops-suite.hotelops.v_progetto_voci_stato\` GROUP BY stato ORDER BY stato"
```

Expected:
```
stato,n
IDENTIFICATO,2
IN_CORSO_FATTURATO,2
IN_VALUTAZIONE,6
```

- [ ] **Step 9.5: Commit**

```bash
git add core/bq/views/v_progetto_voci_stato.sql core/bq/load/deploy_view_voci_stato.py
git commit -m "feat(progetti): v_progetto_voci_stato view (COSA — Register)

Derives stato per voce from f_progetto_eventi:
- CHIUSO: pagato >= impegnato
- IN_CORSO_FATTURATO: ha fatture
- IMPEGNATO: ha latest IMPEGNO ma 0 fatture
- IN_VALUTAZIONE: ha preventivi ma 0 IMPEGNO
- IDENTIFICATO: 0 eventi

Latest IMPEGNO via ROW_NUMBER() (I8: row selection in canonical view).
Smoke test: 10 voci, distribuzione stati 2 IDENTIFICATO + 2 IN_CORSO_FATTURATO + 6 IN_VALUTAZIONE.

Refs: docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md §4 (COSA)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: BQ integration smoke test

**Files:**
- Create: `tests/test_progetti_seed.py`

- [ ] **Step 10.1: Write integration tests**

Create `tests/test_progetti_seed.py`:

```python
"""BigQuery integration tests for projects seed (Step 1).

Run with: pytest -m bq tests/test_progetti_seed.py -v

Skipped by default (require BQ credentials). These tests verify that:
1. The 3 tables exist with correct schema.
2. Seed data is queryable.
3. v_progetto_voci_stato derives correct stati.

Idempotent: tests do not modify data, only read.
"""

from __future__ import annotations

import pytest

from core.bq.client import get_client
from core.config import D_PROGETTI, F_PROGETTO_EVENTI, F_PROGETTO_VOCI, V_PROGETTO_VOCI_STATO

pytestmark = pytest.mark.bq


def test_seed_progetti_count():
    """d_progetti has 2 seed rows."""
    client = get_client()
    q = f"""
    SELECT COUNT(*) AS n
    FROM `{D_PROGETTI}`
    WHERE progetto_id IN ('HPAN25PIANO1', 'SPIAGGIA_LOTTO7')
    """
    rows = list(client.query(q).result())
    assert rows[0].n == 2


def test_seed_voci_count():
    """f_progetto_voci has 10 seed rows (5+5)."""
    client = get_client()
    q = f"""
    SELECT progetto_id, COUNT(*) AS n
    FROM `{F_PROGETTO_VOCI}`
    WHERE progetto_id IN ('HPAN25PIANO1', 'SPIAGGIA_LOTTO7')
    GROUP BY progetto_id
    ORDER BY progetto_id
    """
    rows = {r.progetto_id: r.n for r in client.query(q).result()}
    assert rows == {"HPAN25PIANO1": 5, "SPIAGGIA_LOTTO7": 5}


def test_seed_eventi_count():
    """f_progetto_eventi has 19 seed rows (11 HPAN + 8 SPIAGGIA)."""
    client = get_client()
    q = f"""
    SELECT progetto_id, COUNT(*) AS n
    FROM `{F_PROGETTO_EVENTI}`
    WHERE progetto_id IN ('HPAN25PIANO1', 'SPIAGGIA_LOTTO7')
    GROUP BY progetto_id
    ORDER BY progetto_id
    """
    rows = {r.progetto_id: r.n for r in client.query(q).result()}
    assert rows == {"HPAN25PIANO1": 11, "SPIAGGIA_LOTTO7": 8}


def test_view_stato_distribution():
    """v_progetto_voci_stato distribution matches expected: 2/2/6."""
    client = get_client()
    q = f"""
    SELECT stato, COUNT(*) AS n
    FROM `{V_PROGETTO_VOCI_STATO}`
    WHERE progetto_id IN ('HPAN25PIANO1', 'SPIAGGIA_LOTTO7')
    GROUP BY stato
    ORDER BY stato
    """
    rows = {r.stato: r.n for r in client.query(q).result()}
    assert rows == {
        "IDENTIFICATO": 2,
        "IN_CORSO_FATTURATO": 2,
        "IN_VALUTAZIONE": 6,
    }


def test_view_amcn_overrun_visible():
    """HPAN25PIANO1.001 (AMCN) shows overrun: importo_impegnato=412928.18 (latest IMPEGNO wins)."""
    client = get_client()
    q = f"""
    SELECT
      voce_id,
      importo_impegnato_eur,
      importo_fatturato_eur,
      delta_overrun_eur,
      stato
    FROM `{V_PROGETTO_VOCI_STATO}`
    WHERE voce_id = 'HPAN25PIANO1.001'
    """
    rows = list(client.query(q).result())
    assert len(rows) == 1
    r = rows[0]
    assert float(r.importo_impegnato_eur) == 412928.18  # latest IMPEGNO (overrun)
    assert float(r.importo_fatturato_eur) == 160889.94  # 44 + 56732.02 + 60157.92
    assert r.stato == "IN_CORSO_FATTURATO"
```

- [ ] **Step 10.2: Run integration tests**

```bash
cd /Users/stefanodellapietra/dev/Projects/hotelops
pytest tests/test_progetti_seed.py -v -m bq
```

Expected: 5 tests PASS.

If a test fails:
- Counts mismatch → re-run `python -m core.bq.load.seed_progetti_step1`
- Stato distribution mismatch → review view SQL CASE WHEN
- AMCN overrun missing → verify both IMPEGNO eventi are inserted (data_evento ordering)

- [ ] **Step 10.3: Commit**

```bash
git add tests/test_progetti_seed.py
git commit -m "test(progetti): BQ integration smoke tests for seed Step 1

5 tests verifying:
- 2 progetti / 10 voci / 19 eventi present
- v_progetto_voci_stato distribution: 2 IDENTIFICATO + 2 IN_CORSO_FATTURATO + 6 IN_VALUTAZIONE
- AMCN overrun (latest IMPEGNO=412K, latest wins, fatturato=160K, stato=IN_CORSO_FATTURATO)

Marked @pytest.mark.bq (require credentials, skipped by default).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-review checklist (post-execution)

After all 10 tasks executed, verify:

1. **All Pydantic tests green** (no `@pytest.mark.bq`):
   ```bash
   pytest tests/test_progetti_schema.py -v
   ```
   Expected: 21 tests PASS.

2. **All BQ integration tests green** (with `@pytest.mark.bq`):
   ```bash
   pytest tests/test_progetti_seed.py -v -m bq
   ```
   Expected: 5 tests PASS.

3. **Existing test suite still green** (no regressions):
   ```bash
   pytest -v
   ```
   Expected: all green (Step 1 only added; nothing modified existing flows).

4. **Idempotency verified**:
   - `python -m core.bq.load.create_progetti_tables` (re-run): no errors
   - `python -m core.bq.load.seed_progetti_step1` (re-run): counts unchanged 2/10/19
   - `python -m core.bq.load.deploy_view_voci_stato` (re-run): no errors

5. **Lint clean**:
   ```bash
   ruff check core/schemas.py core/config.py core/bq/load/create_progetti_tables.py core/bq/load/seed_progetti_step1.py core/bq/load/deploy_view_voci_stato.py tests/test_progetti_schema.py tests/test_progetti_seed.py
   ruff format --check core/schemas.py core/config.py core/bq/load/create_progetti_tables.py core/bq/load/seed_progetti_step1.py core/bq/load/deploy_view_voci_stato.py tests/test_progetti_schema.py tests/test_progetti_seed.py
   ```
   Expected: clean.

If any of the above fails, do NOT proceed to Fase 2. Step 1 must validate the flow before unlocking Fase 2 (forward-flow + reversed Drive write).

---

## Out of Step 1 (Fase 2+ backlog)

- View `v_progetto_timeline` (QUANTO — Budget Evolution)
- View `v_progetto_payment_schedule` (QUANDO — Payment Planning)
- View `v_progetto_preventivi` (CHI — Documents extended)
- Forward-flow `f_piano_finanziario_input` fonte=PROGETTI
- CLI `hotelops progetti {overview,voci,eventi,...}`
- Streamlit app
- LLM extraction PDF → eventi
- Reversed Drive: hotelops crea Excel template + cartelle
- Agent loop drop→map
- Parsing automatico Excel attuali (HPAN25PIANO1_CapEx_Controllo.xlsx, SPIAGGIA_budget_lotto7_v2.xlsx)
