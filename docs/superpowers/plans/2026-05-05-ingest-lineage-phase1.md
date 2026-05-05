# Ingest Lineage Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introdurre un lineage layer per-raw-object additive-only nel repo `hotelops`, con detection ↔ policy separate, hard gate "no loop, no canonical", e zero modifica al comportamento esistente.

**Architecture:** Append-only su tutta la linea. `f_raw_objects` è identity-only (write-once at intake), `f_lineage_events` è il log immutabile delle transizioni di stato. Una view `v_raw_objects_current` espone lo stato corrente via window function. Tutte le scritture passano da `bq_write_validated(append)` — I1 pieno, zero MERGE. Nuovi entrypoint `hotelops intake/promote/lineage`; `cmd_drop`/`cmd_classifica`/`ingest.orchestrate` invariati.

**Tech Stack:** Python 3.11+, Pydantic v2, google-cloud-bigquery, PyYAML, pytest. Test: pytest + tmp_path + monkeypatch (no real BQ).

**Spec autoritativa:** `docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md`

**Branch:** `refactor/ingest-lineage-gcs`

**Constraints (non negoziabili):**
- Nessun file in `ingest/banca/`, `ingest/flussi/`, `ingest/classify.py`, `ingest/orchestrate.py`, `core/bq/manifest.py`, `core/bq/write.py` viene modificato
- Tutti i test esistenti restano verdi (nessun edit in `tests/test_*.py` esistenti)
- Tutte le scritture BQ in nuovi moduli passano da `bq_write_validated`

---

## File structure (locked)

| Path | Type | Responsibility |
|---|---|---|
| `core/lineage/__init__.py` | new | package marker |
| `core/lineage/schemas.py` | new | Pydantic: `SourceDefinition`, `RawObject`, `LineageEvent`; naming grammar validator |
| `core/source_registry.yaml` | new | SSOT policy per source_name (10 categories seeded) |
| `core/lineage/source_resolver.py` | new | load yaml, validate naming + invariants, lookup by detector_category + dims |
| `core/lineage/state_machine.py` | new | pure transition rules (`can_transition`, `next_status`) |
| `core/lineage/policy_gate.py` | new | `enforce_loop_target_gate`, `PolicyViolation` |
| `core/lineage/raw_manifest.py` | new | high-level API: `register_raw_object`, `emit_event`, `latest_status` (via view) |
| `core/bq/load/load_lineage_tables.py` | new | DDL loader for `f_raw_objects`, `f_lineage_events`, `v_raw_objects_current` |
| `core/bq/views/v_raw_objects_current.sql` | new | view derives current status from latest event |
| `ingest/intake.py` | new | entrypoint: file + source_metadata → raw blob + RAW_INGESTED event |
| `ingest/promotion.py` | new | entrypoint: PROMOTABLE → parser → bq_write_validated → PROMOTED |
| `cli.py` | edit (additive) | 3 new subparsers + handlers (`intake`, `promote`, `lineage`) |
| `CLAUDE.md` | edit (additive) | §Lineage stub (~10 lines) |
| `docs/architecture/DATA_ENGINEERING_RULES.md` | edit (additive) | §10 link this spec |
| `docs/superpowers/specs/2026-04-02-manifest-shadow-os-design.md` | edit | banner SUPERSEDED in cima |
| `STATUS.md` | edit (additive) | "in corso" entry |
| `tests/test_lineage_schemas.py` | new | grammar + Pydantic round-trip |
| `tests/test_source_resolver.py` | new | yaml load, validation, lookup |
| `tests/test_state_machine.py` | new | every transition + every rejection |
| `tests/test_policy_gate.py` | new | hard gate firing |
| `tests/test_raw_manifest.py` | new | register, emit_event, dedup (mock BQ) |
| `tests/test_intake.py` | new | end-to-end (mock BQ) |
| `tests/test_promotion.py` | new | happy path + 4 rejection paths (mock BQ) |

---

## Conventions

- Commits use Conventional Commits: `feat(lineage): ...`, `test(lineage): ...`, `docs(lineage): ...`
- Each commit is one logical unit (one task, OR one test+impl pair within a task if substantial)
- All new BQ tables are namespaced under `hotelops.f_*` and `hotelops.v_*`
- All BQ writes from new modules use `bq_write_validated(mode="append")` — never raw client
- Mock BQ in tests via `monkeypatch.setattr("core.bq.write.get_client", ...)` (consistent with existing `tests/test_bq_write.py`)

---

## Task 1: Pydantic schemas + naming grammar

**Files:**
- Create: `core/lineage/__init__.py`
- Create: `core/lineage/schemas.py`
- Test: `tests/test_lineage_schemas.py`

- [ ] **Step 1.1: Create empty package marker**

```bash
mkdir -p core/lineage
```

Create `core/lineage/__init__.py`:

```python
"""Lineage layer — per-raw-object tracking, source policy, state machine.

See spec: docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md
"""
```

- [ ] **Step 1.2: Write failing tests for naming grammar**

Create `tests/test_lineage_schemas.py`:

```python
"""Pydantic schemas + naming grammar for the lineage layer."""

from datetime import datetime, timezone

import pytest

from core.lineage.schemas import (
    InvalidSourceName,
    LineageEvent,
    RawObject,
    SourceDefinition,
    validate_source_name,
)


# ── Naming grammar ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "ESOLVER_BILANCINO_ORTI_SNAPSHOT",
        "MPS_BANCA_INTUR_APPEND",
        "POWERBI_CRUSCOTTO_ORTI_APPEND",
        "ESOLVER_BUDGET_GROUP_SNAPSHOT",
    ],
)
def test_valid_source_names(name: str) -> None:
    system, dataset, societa, lifecycle = validate_source_name(name)
    assert "_" not in system
    assert societa in {"ORTI", "INTUR", "GROUP"}
    assert lifecycle in {"APPEND", "SNAPSHOT"}


@pytest.mark.parametrize(
    "name, fragment",
    [
        ("ESOLVER_BILANCINO_ORTI", "expected 4"),
        ("ESOLVER_MOVIMENTI_CONTABILI_ORTI_APPEND", "expected 4"),
        ("esolver_BILANCINO_ORTI_SNAPSHOT", "[A-Z]"),
        ("ESOLVER_BILANCINO_HOTEL_SNAPSHOT", "societa"),
        ("ESOLVER_BILANCINO_ORTI_DELTA", "lifecycle"),
        ("1ESOLVER_BILANCINO_ORTI_SNAPSHOT", "[A-Z]"),
    ],
)
def test_invalid_source_names_raise(name: str, fragment: str) -> None:
    with pytest.raises(InvalidSourceName) as exc:
        validate_source_name(name)
    assert fragment in str(exc.value)
```

- [ ] **Step 1.3: Run test, verify failure**

```bash
pytest tests/test_lineage_schemas.py -v
```

Expected: ImportError / collection error (`core.lineage.schemas` doesn't exist yet).

- [ ] **Step 1.4: Implement schemas.py with naming grammar + Pydantic models**

Create `core/lineage/schemas.py`:

```python
"""Pydantic schemas + naming grammar for the lineage layer.

Spec: docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md §4
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# ── Closed enums ──────────────────────────────────────────────────────────────

SOCIETA_VALUES = ("ORTI", "INTUR", "GROUP")
LIFECYCLE_VALUES = ("APPEND", "SNAPSHOT")
TOKEN_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*$")

RawObjectStatus = Literal["RAW_ONLY", "CLASSIFIED", "PROMOTABLE", "PROMOTED", "REJECTED"]

LineageEventType = Literal[
    "RAW_INGESTED",
    "DETECTED",
    "SOURCE_RESOLVED",
    "VALIDATED_OK",
    "VALIDATED_FAIL",
    "PROMOTION_REQUESTED",
    "PROMOTED",
    "REJECTED",
    "RECLASSIFIED",
]

RejectionReason = Literal["NO_LOOP_TARGET", "DETECT_FAIL", "VALIDATE_FAIL", "WRITE_FAIL"]
PromotionPolicy = Literal["AUTO", "MANUAL", "RAW_ONLY"]
RawBackend = Literal["drive", "gcs", "local"]


# ── Naming grammar ────────────────────────────────────────────────────────────


class InvalidSourceName(ValueError):
    """source_name does not match <SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>."""


def validate_source_name(name: str) -> tuple[str, str, str, str]:
    """Parse + validate a source_name. Returns (system, dataset, societa, lifecycle).

    Strict 4-token grammar — see spec §4.1.1.
    """
    parts = name.split("_")
    if len(parts) != 4:
        raise InvalidSourceName(
            f"{name!r}: expected 4 underscore-separated tokens, got {len(parts)}"
        )
    system, dataset, societa, lifecycle = parts
    for token, label in ((system, "system"), (dataset, "dataset")):
        if not TOKEN_PATTERN.match(token):
            raise InvalidSourceName(
                f"{name!r}: {label} token {token!r} must match [A-Z][A-Z0-9]*"
            )
    if societa not in SOCIETA_VALUES:
        raise InvalidSourceName(
            f"{name!r}: societa {societa!r} must be one of {list(SOCIETA_VALUES)}"
        )
    if lifecycle not in LIFECYCLE_VALUES:
        raise InvalidSourceName(
            f"{name!r}: lifecycle {lifecycle!r} must be one of {list(LIFECYCLE_VALUES)}"
        )
    return (system, dataset, societa, lifecycle)


# ── Source definition (yaml row) ──────────────────────────────────────────────


class SourceDefinition(BaseModel):
    source_name: str
    system: str
    dataset: str
    dataset_label: Optional[str] = None
    societa: Literal["ORTI", "INTUR", "GROUP"]
    business_unit: Optional[str] = None
    lifecycle: Literal["APPEND", "SNAPSHOT"]
    canonical_table: str
    parser_module: str
    parser_entrypoint: str = "main"
    natural_key: Optional[list[str]] = None
    hash_basis: Optional[str] = None
    loop_targets: list[str] = Field(default_factory=list)
    promotion_policy: PromotionPolicy
    detector_category: str
    raw_storage: dict
    notes: Optional[str] = None

    @field_validator("source_name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        validate_source_name(v)
        return v


# ── Raw object (identity row) ─────────────────────────────────────────────────


class RawObject(BaseModel):
    raw_object_id: str
    content_hash: str
    raw_uri: str
    raw_backend: RawBackend
    file_name_original: str
    file_name_canonical: Optional[str] = None
    bytes_size: int
    source_name: Optional[str] = None
    detector_category: Optional[str] = None
    societa_id: Optional[str] = None
    business_unit_id: Optional[str] = None
    banca_id: Optional[str] = None
    intake_at: datetime
    intake_actor: str
    pipeline_run_id: str
    pipeline_name: str
    file_sorgente: Optional[str] = None
    ingestion_ts: datetime


# ── Lineage event (state transition log row) ──────────────────────────────────


class LineageEvent(BaseModel):
    event_id: str
    raw_object_id: str
    event_type: LineageEventType
    event_at: datetime
    actor: str
    pipeline_run_id: Optional[str] = None
    pipeline_name: Optional[str] = None
    from_status: Optional[RawObjectStatus] = None
    to_status: Optional[RawObjectStatus] = None
    payload_json: Optional[str] = None
    reason: Optional[RejectionReason] = None
```

- [ ] **Step 1.5: Run grammar tests, verify pass**

```bash
pytest tests/test_lineage_schemas.py -v -k "source_name"
```

Expected: 10 passed (4 valid + 6 invalid).

- [ ] **Step 1.6: Add Pydantic round-trip tests**

Append to `tests/test_lineage_schemas.py`:

```python
# ── Pydantic round-trip ──────────────────────────────────────────────────────


def test_RawObject_round_trip() -> None:
    now = datetime(2026, 5, 5, 10, 0, tzinfo=timezone.utc)
    obj = RawObject(
        raw_object_id="abc-123",
        content_hash="d41d8cd98f00b204e9800998ecf8427e",
        raw_uri="file:///tmp/test.xlsx",
        raw_backend="local",
        file_name_original="Master_Completo_ORTI_20260430.xlsx",
        bytes_size=12345,
        source_name="ESOLVER_BUDGET_ORTI_SNAPSHOT",
        detector_category="gasparotto",
        societa_id="ORTI",
        intake_at=now,
        intake_actor="cli",
        pipeline_run_id="run-1",
        pipeline_name="ingest_intake",
        ingestion_ts=now,
    )
    dumped = obj.model_dump(mode="json")
    revived = RawObject(**dumped)
    assert revived.raw_object_id == "abc-123"
    assert revived.intake_at == now


def test_LineageEvent_minimal() -> None:
    ev = LineageEvent(
        event_id="ev-1",
        raw_object_id="abc-123",
        event_type="RAW_INGESTED",
        event_at=datetime.now(timezone.utc),
        actor="cli",
        from_status=None,
        to_status="RAW_ONLY",
    )
    assert ev.to_status == "RAW_ONLY"


def test_LineageEvent_with_reason() -> None:
    ev = LineageEvent(
        event_id="ev-2",
        raw_object_id="abc-123",
        event_type="REJECTED",
        event_at=datetime.now(timezone.utc),
        actor="gate",
        from_status="CLASSIFIED",
        to_status="REJECTED",
        reason="NO_LOOP_TARGET",
        payload_json='{"source_name": "POWERBI_CRUSCOTTO_ORTI_APPEND"}',
    )
    assert ev.reason == "NO_LOOP_TARGET"


def test_SourceDefinition_invalid_name_rejected() -> None:
    import pytest as _pytest
    with _pytest.raises(Exception):  # Pydantic ValidationError wraps InvalidSourceName
        SourceDefinition(
            source_name="bad_name",
            system="ESOLVER",
            dataset="X",
            societa="ORTI",
            lifecycle="APPEND",
            canonical_table="f_x",
            parser_module="ingest.flussi.x",
            promotion_policy="AUTO",
            detector_category="x",
            raw_storage={},
        )
```

- [ ] **Step 1.7: Run all schema tests, verify pass**

```bash
pytest tests/test_lineage_schemas.py -v
```

Expected: 14 passed.

- [ ] **Step 1.8: Commit**

```bash
git add core/lineage/__init__.py core/lineage/schemas.py tests/test_lineage_schemas.py
git commit -m "feat(lineage): pydantic schemas + naming grammar (task 1)"
```

---

## Task 2: Source registry yaml + loader

**Files:**
- Create: `core/source_registry.yaml`
- Create: `core/lineage/source_resolver.py`
- Test: `tests/test_source_resolver.py`

**Decision required before this task starts:** Q7 from spec §12 — for `Master_Completo_*.xlsx` (Romita's Gasparotto file), use `system=ESOLVER` (default) or `system=ROMITA`? **This plan assumes `ESOLVER` per spec default. Flip seed entry if Stefano decides otherwise.**

- [ ] **Step 2.1: Seed `core/source_registry.yaml` with the 10 current detector categories**

Create `core/source_registry.yaml`:

```yaml
# Single source of truth for source policy (NOT detector signatures).
# Detector signatures live in core/registry.yaml.
# Spec: docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md §4.1
version: 1

sources:

  # ── Banca homebanking — APPEND, MD5 dedup ────────────────────────────────
  MPS_BANCA_ORTI_APPEND:
    system: MPS
    dataset: BANCA
    dataset_label: "Movimenti homebanking MPS"
    societa: ORTI
    business_unit: null
    lifecycle: APPEND
    canonical_table: f_banche_movimenti
    parser_module: ingest.banca.ingest
    hash_basis: hash_riga
    loop_targets: [daily_reconciliation, cash_control, monthly_close]
    promotion_policy: AUTO
    detector_category: banca
    raw_storage:
      backend: drive
      path_template: "homebanking/ORTI/MPS"

  MPS_BANCA_INTUR_APPEND:
    system: MPS
    dataset: BANCA
    societa: INTUR
    business_unit: null
    lifecycle: APPEND
    canonical_table: f_banche_movimenti
    parser_module: ingest.banca.ingest
    hash_basis: hash_riga
    loop_targets: [daily_reconciliation, cash_control, monthly_close]
    promotion_policy: AUTO
    detector_category: banca
    raw_storage:
      backend: drive
      path_template: "homebanking/INTUR/MPS"

  # (additional banca sources MPSKROSS/SELLA/INTESA/BCP follow the same pattern;
  #  add them per societa as the migration proceeds — see spec Appendice B)

  # ── Esolver flussi — APPEND ───────────────────────────────────────────────
  ESOLVER_MOVIMENTI_ORTI_APPEND:
    system: ESOLVER
    dataset: MOVIMENTI
    dataset_label: "Prima nota Esolver (LISTAMOVCONT)"
    societa: ORTI
    business_unit: null
    lifecycle: APPEND
    canonical_table: f_movimenti_contabili
    parser_module: ingest.flussi.ingest_movimenti_contabili
    hash_basis: hash_riga
    loop_targets: [monthly_close, budget_canonical]
    promotion_policy: AUTO
    detector_category: movimenti_contabili
    raw_storage:
      backend: drive
      path_template: "movimenti_contabili/ORTI"

  # ── Esolver scheda contabile — APPEND ─────────────────────────────────────
  ESOLVER_SCHEDA_ORTI_APPEND:
    system: ESOLVER
    dataset: SCHEDA
    dataset_label: "Scheda contabile / saldi banca da Esolver"
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_saldi_banca_snapshot
    parser_module: ingest.flussi.ingest_scheda_contabile
    hash_basis: hash_riga
    loop_targets: [bank_ledger_reconciliation, cash_control]
    promotion_policy: AUTO
    detector_category: scheda_contabile
    raw_storage:
      backend: drive
      path_template: "registro_banca_esolver/ORTI"

  # ── Partite aperte — SNAPSHOT ─────────────────────────────────────────────
  ESOLVER_PARTITE_ORTI_SNAPSHOT:
    system: ESOLVER
    dataset: PARTITE
    dataset_label: "Partite aperte fornitori"
    societa: ORTI
    lifecycle: SNAPSHOT
    canonical_table: f_partite_aperte_fornitori
    parser_module: ingest.flussi.ingest_partite_aperte
    natural_key: [data_snapshot, societa_id]
    loop_targets: [cash_control, monthly_close]
    promotion_policy: AUTO
    detector_category: partite_fornitori
    raw_storage:
      backend: drive
      path_template: "partite_fornitori/ORTI"

  ESOLVER_PARTITE_INTUR_SNAPSHOT:
    system: ESOLVER
    dataset: PARTITE
    societa: INTUR
    lifecycle: SNAPSHOT
    canonical_table: f_partite_aperte_fornitori
    parser_module: ingest.flussi.ingest_partite_aperte
    natural_key: [data_snapshot, societa_id]
    loop_targets: [cash_control, monthly_close]
    promotion_policy: AUTO
    detector_category: partite_fornitori
    raw_storage:
      backend: drive
      path_template: "partite_fornitori/INTUR"

  # ── Bilancino — SNAPSHOT ──────────────────────────────────────────────────
  ESOLVER_BILANCINO_ORTI_SNAPSHOT:
    system: ESOLVER
    dataset: BILANCINO
    societa: ORTI
    lifecycle: SNAPSHOT
    canonical_table: f_bilancino
    parser_module: ingest.flussi.ingest_bilancino
    natural_key: [data_snapshot, societa_id, codice_conto]
    loop_targets: [monthly_close, budget_canonical]
    promotion_policy: AUTO
    detector_category: bilancino
    raw_storage:
      backend: drive
      path_template: "bilancino/ORTI"

  # ── Gasparotto budget — SNAPSHOT ──────────────────────────────────────────
  ESOLVER_BUDGET_ORTI_SNAPSHOT:
    system: ESOLVER
    dataset: BUDGET
    dataset_label: "Master Completo (Romita) — sezione Budget"
    societa: ORTI
    lifecycle: SNAPSHOT
    canonical_table: f_budget_mensile
    parser_module: ingest.flussi.ingest_gasparotto
    natural_key: [societa_id, anno, mese, codice_conto, fonte]
    loop_targets: [budget_canonical, monthly_close]
    promotion_policy: AUTO
    detector_category: gasparotto
    raw_storage:
      backend: drive
      path_template: "gasparotto"
    notes: |
      Q7 ancora aperta: system=ESOLVER (default, fonte primaria) o
      system=ROMITA (autore del foglio)? Flip qui se Stefano decide ROMITA.

  # ── Piano finanziario — SNAPSHOT ──────────────────────────────────────────
  ESOLVER_PF_ORTI_SNAPSHOT:
    system: ESOLVER
    dataset: PF
    dataset_label: "Piano Finanziario (cash flow voci)"
    societa: ORTI
    lifecycle: SNAPSHOT
    canonical_table: f_piano_finanziario_input
    parser_module: ingest.flussi.ingest_piano_finanziario_xlsx
    natural_key: [societa_id, voce_id, anno, mese, fonte]
    loop_targets: [cash_control, budget_canonical]
    promotion_policy: AUTO
    detector_category: piano_finanziario
    raw_storage:
      backend: drive
      path_template: "piani_finanziari/ORTI"

  # ── HotelCube accodamenti — APPEND, BU per-file ───────────────────────────
  HOTELCUBE_ACCODAMENTI_ORTI_APPEND:
    system: HOTELCUBE
    dataset: ACCODAMENTI
    dataset_label: "Accodamenti PMS (corrispettivi/fatture/movimenti)"
    societa: ORTI
    business_unit: null   # H_/R_/C_ prefix → HOTEL/RESIDENCE/CVM, popolato per-file
    lifecycle: APPEND
    canonical_table: f_accodamenti
    parser_module: ingest.banca.ingest_accodamenti
    hash_basis: hash_riga
    loop_targets: [daily_reconciliation, cash_control]
    promotion_policy: AUTO
    detector_category: accodamenti
    raw_storage:
      backend: drive
      path_template: "accodamenti/ORTI"

  # ── Coperti — APPEND ──────────────────────────────────────────────────────
  ORTI_COPERTI_ORTI_APPEND:
    system: ORTI
    dataset: COPERTI
    dataset_label: "Coperti giornalieri (Google Sheet o XLSX)"
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_coperti_giornalieri
    parser_module: ingest.flussi.ingest_coperti
    hash_basis: hash_riga
    loop_targets: [food_cost, monthly_close]
    promotion_policy: AUTO
    detector_category: coperti
    raw_storage:
      backend: drive
      path_template: "coperti"

  # ── Economato consumi — APPEND ────────────────────────────────────────────
  ORTI_ECONOMATO_ORTI_APPEND:
    system: ORTI
    dataset: ECONOMATO
    dataset_label: "Consumi economato per reparto"
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_consumi_economato
    parser_module: ingest.flussi.ingest_consumi_economato
    hash_basis: hash_riga
    loop_targets: [food_cost, monthly_close]
    promotion_policy: AUTO
    detector_category: economato
    raw_storage:
      backend: drive
      path_template: "economato"

  # ── PMS statistiche — RAW_ONLY (esempio hard gate) ────────────────────────
  POWERBI_CRUSCOTTO_ORTI_APPEND:
    system: POWERBI
    dataset: CRUSCOTTO
    dataset_label: "Cruscotto produzione PMS (export Power BI)"
    societa: ORTI
    business_unit: null
    lifecycle: APPEND
    canonical_table: f_pms_statistiche
    parser_module: ingest.flussi.ingest_pms_statistiche
    hash_basis: hash_riga
    loop_targets: []
    promotion_policy: RAW_ONLY
    detector_category: pms_statistiche
    raw_storage:
      backend: drive
      path_template: "ingresso/pms_statistiche/ORTI"
    notes: |
      Esempio hard gate: dati interessanti, nessun loop dichiarato. Resta
      in raw, no canonical promotion. Flip a AUTO + dichiara loop_target
      quando il consumer sarà pronto.
```

- [ ] **Step 2.2: Write failing tests for source_resolver**

Create `tests/test_source_resolver.py`:

```python
"""Source registry loader + lookup."""

from pathlib import Path

import pytest

from core.lineage.source_resolver import (
    InvalidRegistry,
    SourceRegistry,
    load_registry,
)


# ── Registry load + invariant validation ─────────────────────────────────────


def test_load_real_registry() -> None:
    """The shipped registry must load + validate cleanly."""
    reg = load_registry()
    assert len(reg.sources) >= 10
    assert "ESOLVER_BILANCINO_ORTI_SNAPSHOT" in reg.sources
    assert "POWERBI_CRUSCOTTO_ORTI_APPEND" in reg.sources


def test_registry_lookup_by_detector_category(tmp_path: Path) -> None:
    reg = load_registry()
    matches = reg.find_by_detector_category("partite_fornitori")
    assert len(matches) == 2  # ORTI + INTUR
    societas = {m.societa for m in matches}
    assert societas == {"ORTI", "INTUR"}


def test_registry_lookup_with_societa(tmp_path: Path) -> None:
    reg = load_registry()
    match = reg.find_by_detector_category("partite_fornitori", societa="ORTI")
    assert match is not None
    assert match.source_name == "ESOLVER_PARTITE_ORTI_SNAPSHOT"


# ── Invariant: loop_targets == [] ⇔ promotion_policy == RAW_ONLY ─────────────


def test_invariant_violation_raw_only_with_loops(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
version: 1
sources:
  ESOLVER_BAD_ORTI_APPEND:
    system: ESOLVER
    dataset: BAD
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.flussi.x
    promotion_policy: RAW_ONLY
    detector_category: x
    loop_targets: [some_loop]
    raw_storage: {backend: local, path_template: "x"}
"""
    )
    with pytest.raises(InvalidRegistry, match="RAW_ONLY"):
        load_registry(path=bad)


def test_invariant_violation_auto_without_loops(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
version: 1
sources:
  ESOLVER_BAD_ORTI_APPEND:
    system: ESOLVER
    dataset: BAD
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.flussi.x
    promotion_policy: AUTO
    detector_category: x
    loop_targets: []
    raw_storage: {backend: local, path_template: "x"}
"""
    )
    with pytest.raises(InvalidRegistry, match="loop_targets"):
        load_registry(path=bad)


def test_invalid_source_name_in_registry(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
version: 1
sources:
  bad_lowercase_name:
    system: ESOLVER
    dataset: X
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_x
    parser_module: ingest.flussi.x
    promotion_policy: AUTO
    detector_category: x
    loop_targets: [some_loop]
    raw_storage: {backend: local, path_template: "x"}
"""
    )
    with pytest.raises(Exception):  # InvalidSourceName wrapped or surfaced
        load_registry(path=bad)
```

- [ ] **Step 2.3: Run, verify FAIL**

```bash
pytest tests/test_source_resolver.py -v
```

Expected: ImportError (`source_resolver` not yet implemented).

- [ ] **Step 2.4: Implement `core/lineage/source_resolver.py`**

```python
"""Load + validate core/source_registry.yaml. Lookup by detector_category + dims.

Spec: §4.1, §7.1
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import ValidationError

from core.lineage.policy_gate import PolicyViolation, enforce_loop_target_gate_consistency
from core.lineage.schemas import InvalidSourceName, SourceDefinition

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "core" / "source_registry.yaml"


class InvalidRegistry(Exception):
    """Registry yaml violates an invariant or schema."""


class SourceRegistry:
    def __init__(self, sources: dict[str, SourceDefinition]):
        self.sources = sources

    def find_by_detector_category(
        self, detector_category: str, societa: Optional[str] = None
    ) -> list[SourceDefinition] | Optional[SourceDefinition]:
        """Lookup sources matching detector_category (and optionally societa).

        - With societa: returns single SourceDefinition or None.
        - Without societa: returns list of all matches.
        """
        matches = [
            s
            for s in self.sources.values()
            if s.detector_category == detector_category
        ]
        if societa is None:
            return matches
        narrow = [s for s in matches if s.societa == societa]
        if not narrow:
            return None
        if len(narrow) > 1:
            raise InvalidRegistry(
                f"Ambiguous lookup: {detector_category}+{societa} matches "
                f"{[s.source_name for s in narrow]}"
            )
        return narrow[0]

    def get(self, source_name: str) -> Optional[SourceDefinition]:
        return self.sources.get(source_name)


def load_registry(path: Optional[Path] = None) -> SourceRegistry:
    """Load + validate the registry. Raises InvalidRegistry on any failure."""
    p = path or REGISTRY_PATH
    if not p.exists():
        raise InvalidRegistry(f"Registry file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "sources" not in raw:
        raise InvalidRegistry(f"{p}: missing top-level 'sources' key")

    sources: dict[str, SourceDefinition] = {}
    for source_name, spec in (raw["sources"] or {}).items():
        try:
            sd = SourceDefinition(source_name=source_name, **spec)
        except (ValidationError, InvalidSourceName) as e:
            raise InvalidRegistry(f"{p}::{source_name}: {e}") from e

        try:
            enforce_loop_target_gate_consistency(sd)
        except PolicyViolation as e:
            raise InvalidRegistry(f"{p}::{source_name}: {e}") from e

        sources[source_name] = sd

    return SourceRegistry(sources)
```

Note: this depends on `policy_gate.enforce_loop_target_gate_consistency`, which we implement next in Task 4. To unblock this test, add a temporary stub in `policy_gate.py`:

Create `core/lineage/policy_gate.py` (stub only — full impl in Task 4):

```python
"""Policy gate — hard gate for 'no loop, no canonical'. (stub — Task 4 fills in)"""

from __future__ import annotations

from core.lineage.schemas import SourceDefinition


class PolicyViolation(Exception):
    def __init__(self, reason: str, source_name: str, message: str):
        self.reason = reason
        self.source_name = source_name
        super().__init__(message)


def enforce_loop_target_gate_consistency(source_def: SourceDefinition) -> None:
    """Boot-time check: loop_targets == [] ⇔ promotion_policy == RAW_ONLY."""
    has_loops = bool(source_def.loop_targets)
    is_raw_only = source_def.promotion_policy == "RAW_ONLY"
    if has_loops and is_raw_only:
        raise PolicyViolation(
            "NO_LOOP_TARGET",
            source_def.source_name,
            f"{source_def.source_name}: promotion_policy=RAW_ONLY "
            f"contraddice loop_targets={source_def.loop_targets}.",
        )
    if not has_loops and not is_raw_only:
        raise PolicyViolation(
            "NO_LOOP_TARGET",
            source_def.source_name,
            f"{source_def.source_name}: loop_targets=[] ma "
            f"promotion_policy={source_def.promotion_policy}.",
        )
```

- [ ] **Step 2.5: Run tests, verify pass**

```bash
pytest tests/test_source_resolver.py -v
```

Expected: 6 passed.

- [ ] **Step 2.6: Commit**

```bash
git add core/source_registry.yaml core/lineage/source_resolver.py core/lineage/policy_gate.py tests/test_source_resolver.py
git commit -m "feat(lineage): source_registry.yaml + resolver + policy_gate stub (task 2)"
```

---

## Task 3: State machine (pure functions)

**Files:**
- Create: `core/lineage/state_machine.py`
- Test: `tests/test_state_machine.py`

- [ ] **Step 3.1: Write failing tests**

Create `tests/test_state_machine.py`:

```python
"""Pure transition rules for the lineage state machine.

Spec: §5.2
"""

import pytest

from core.lineage.state_machine import (
    InvalidTransition,
    can_transition,
    next_status_after_event,
)


# ── Allowed transitions ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "from_status, event_type, expected_to",
    [
        (None, "RAW_INGESTED", "RAW_ONLY"),
        ("RAW_ONLY", "SOURCE_RESOLVED", "CLASSIFIED"),
        ("CLASSIFIED", "PROMOTION_REQUESTED", None),  # no transition, just event
        ("PROMOTABLE", "PROMOTED", "PROMOTED"),
        ("CLASSIFIED", "REJECTED", "REJECTED"),
        ("PROMOTABLE", "REJECTED", "REJECTED"),
        ("REJECTED", "RECLASSIFIED", "CLASSIFIED"),
    ],
)
def test_allowed(from_status, event_type, expected_to) -> None:
    assert can_transition(from_status, event_type)
    if expected_to is not None:
        assert next_status_after_event(from_status, event_type) == expected_to


# ── Forbidden transitions ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "from_status, event_type",
    [
        ("PROMOTED", "RAW_INGESTED"),     # already promoted, can't re-ingest
        ("PROMOTED", "PROMOTED"),         # idempotent guard
        ("RAW_ONLY", "PROMOTED"),         # skip CLASSIFIED+PROMOTABLE
        (None, "PROMOTED"),               # no genesis
    ],
)
def test_forbidden(from_status, event_type) -> None:
    assert not can_transition(from_status, event_type)
    with pytest.raises(InvalidTransition):
        next_status_after_event(from_status, event_type)
```

- [ ] **Step 3.2: Run, verify FAIL**

```bash
pytest tests/test_state_machine.py -v
```

Expected: ImportError.

- [ ] **Step 3.3: Implement state machine**

Create `core/lineage/state_machine.py`:

```python
"""Pure transition rules. No I/O. No side effects.

Spec: §5.2
"""

from __future__ import annotations

from typing import Optional

from core.lineage.schemas import LineageEventType, RawObjectStatus


class InvalidTransition(Exception):
    """The (from_status, event_type) pair is not allowed by the state machine."""


# Map: (from_status, event_type) → next_status (or None if event is non-transitional)
# from_status=None means "no prior state" (genesis).
_TRANSITIONS: dict[tuple[Optional[str], LineageEventType], Optional[RawObjectStatus]] = {
    # Genesis
    (None, "RAW_INGESTED"): "RAW_ONLY",
    # Detection (non-transitional events)
    ("RAW_ONLY", "DETECTED"): None,
    ("CLASSIFIED", "DETECTED"): None,  # re-detection on already-classified is logged
    # Source resolution
    ("RAW_ONLY", "SOURCE_RESOLVED"): "CLASSIFIED",
    # Validation events (non-transitional — they precede PROMOTED/REJECTED)
    ("PROMOTABLE", "VALIDATED_OK"): None,
    ("PROMOTABLE", "VALIDATED_FAIL"): None,
    ("CLASSIFIED", "PROMOTION_REQUESTED"): None,
    ("PROMOTABLE", "PROMOTION_REQUESTED"): None,
    # Promotion
    ("PROMOTABLE", "PROMOTED"): "PROMOTED",
    # Rejection (from any non-terminal)
    ("RAW_ONLY", "REJECTED"): "REJECTED",
    ("CLASSIFIED", "REJECTED"): "REJECTED",
    ("PROMOTABLE", "REJECTED"): "REJECTED",
    # Reclassification (revive REJECTED or re-route CLASSIFIED)
    ("REJECTED", "RECLASSIFIED"): "CLASSIFIED",
    ("CLASSIFIED", "RECLASSIFIED"): "CLASSIFIED",
    ("RAW_ONLY", "RECLASSIFIED"): "RAW_ONLY",
}


def can_transition(
    from_status: Optional[RawObjectStatus],
    event_type: LineageEventType,
) -> bool:
    """Return True if (from_status, event_type) is a known transition."""
    return (from_status, event_type) in _TRANSITIONS


def next_status_after_event(
    from_status: Optional[RawObjectStatus],
    event_type: LineageEventType,
) -> Optional[RawObjectStatus]:
    """Return the new status after applying this event.

    Returns None for non-transitional events (DETECTED, VALIDATED_*, PROMOTION_REQUESTED).
    Raises InvalidTransition if the pair is not allowed.
    """
    if not can_transition(from_status, event_type):
        raise InvalidTransition(
            f"Cannot apply {event_type!r} from status {from_status!r}"
        )
    return _TRANSITIONS[(from_status, event_type)]
```

- [ ] **Step 3.4: Run tests, verify pass**

```bash
pytest tests/test_state_machine.py -v
```

Expected: 11 passed (7 allowed + 4 forbidden).

- [ ] **Step 3.5: Commit**

```bash
git add core/lineage/state_machine.py tests/test_state_machine.py
git commit -m "feat(lineage): state machine pure transition rules (task 3)"
```

---

## Task 4: Policy gate (full implementation)

**Files:**
- Modify: `core/lineage/policy_gate.py` (replace stub from Task 2)
- Test: `tests/test_policy_gate.py`

- [ ] **Step 4.1: Write failing tests**

Create `tests/test_policy_gate.py`:

```python
"""Hard gate: 'no loop, no canonical'.

Spec: §7.1
"""

import pytest

from core.lineage.policy_gate import (
    PolicyViolation,
    enforce_loop_target_gate_consistency,
    enforce_loop_target_gate_at_promotion,
)
from core.lineage.schemas import SourceDefinition


def _src(**overrides) -> SourceDefinition:
    base = dict(
        source_name="ESOLVER_BILANCINO_ORTI_SNAPSHOT",
        system="ESOLVER",
        dataset="BILANCINO",
        societa="ORTI",
        lifecycle="SNAPSHOT",
        canonical_table="f_bilancino",
        parser_module="ingest.flussi.ingest_bilancino",
        natural_key=["data_snapshot", "societa_id"],
        loop_targets=["monthly_close"],
        promotion_policy="AUTO",
        detector_category="bilancino",
        raw_storage={"backend": "drive", "path_template": "bilancino/ORTI"},
    )
    base.update(overrides)
    return SourceDefinition(**base)


# ── Boot-time consistency ────────────────────────────────────────────────────


def test_consistent_auto_with_loops_passes() -> None:
    enforce_loop_target_gate_consistency(_src())  # no raise


def test_consistent_raw_only_no_loops_passes() -> None:
    src = _src(
        source_name="POWERBI_CRUSCOTTO_ORTI_APPEND",
        system="POWERBI", dataset="CRUSCOTTO", lifecycle="APPEND",
        canonical_table="f_pms_statistiche",
        parser_module="ingest.flussi.ingest_pms_statistiche",
        natural_key=None,
        loop_targets=[],
        promotion_policy="RAW_ONLY",
        detector_category="pms_statistiche",
    )
    enforce_loop_target_gate_consistency(src)  # no raise


def test_inconsistent_raw_only_with_loops_fails() -> None:
    src = _src(promotion_policy="RAW_ONLY")  # loops still set
    with pytest.raises(PolicyViolation) as exc:
        enforce_loop_target_gate_consistency(src)
    assert exc.value.reason == "NO_LOOP_TARGET"


def test_inconsistent_auto_without_loops_fails() -> None:
    src = _src(loop_targets=[])
    with pytest.raises(PolicyViolation):
        enforce_loop_target_gate_consistency(src)


# ── Promotion-time fail-closed ───────────────────────────────────────────────


def test_promotion_blocked_for_raw_only() -> None:
    src = _src(
        source_name="POWERBI_CRUSCOTTO_ORTI_APPEND",
        system="POWERBI", dataset="CRUSCOTTO", lifecycle="APPEND",
        canonical_table="f_pms_statistiche",
        parser_module="ingest.flussi.ingest_pms_statistiche",
        natural_key=None,
        loop_targets=[],
        promotion_policy="RAW_ONLY",
        detector_category="pms_statistiche",
    )
    with pytest.raises(PolicyViolation) as exc:
        enforce_loop_target_gate_at_promotion(src)
    assert exc.value.reason == "NO_LOOP_TARGET"


def test_promotion_allowed_for_auto() -> None:
    enforce_loop_target_gate_at_promotion(_src())  # no raise
```

- [ ] **Step 4.2: Run, verify FAIL**

Expected: `enforce_loop_target_gate_at_promotion` not yet defined.

```bash
pytest tests/test_policy_gate.py -v
```

- [ ] **Step 4.3: Replace `core/lineage/policy_gate.py` stub with full impl**

```python
"""Policy gate — hard gate for 'no loop, no canonical'.

Spec: §7.1
"""

from __future__ import annotations

from core.lineage.schemas import SourceDefinition


class PolicyViolation(Exception):
    def __init__(self, reason: str, source_name: str, message: str):
        self.reason = reason
        self.source_name = source_name
        super().__init__(message)


def enforce_loop_target_gate_consistency(source_def: SourceDefinition) -> None:
    """Boot-time check.

    Invariant: loop_targets == [] ⇔ promotion_policy == RAW_ONLY.
    A legitimate RAW_ONLY (no loops, policy=RAW_ONLY) passes here.
    """
    has_loops = bool(source_def.loop_targets)
    is_raw_only = source_def.promotion_policy == "RAW_ONLY"
    if has_loops and is_raw_only:
        raise PolicyViolation(
            "NO_LOOP_TARGET",
            source_def.source_name,
            f"{source_def.source_name}: promotion_policy=RAW_ONLY "
            f"contraddice loop_targets={source_def.loop_targets}. "
            f"Decidi: o flip policy=AUTO/MANUAL, o azzera loop_targets.",
        )
    if not has_loops and not is_raw_only:
        raise PolicyViolation(
            "NO_LOOP_TARGET",
            source_def.source_name,
            f"{source_def.source_name}: loop_targets=[] ma "
            f"promotion_policy={source_def.promotion_policy}. "
            f"Hard gate: dichiara almeno un loop o flip policy=RAW_ONLY.",
        )


def enforce_loop_target_gate_at_promotion(source_def: SourceDefinition) -> None:
    """Promotion-time check. Fail-closed: never promote a RAW_ONLY source."""
    enforce_loop_target_gate_consistency(source_def)
    if source_def.promotion_policy == "RAW_ONLY":
        raise PolicyViolation(
            "NO_LOOP_TARGET",
            source_def.source_name,
            f"{source_def.source_name} è RAW_ONLY: promotion non consentita.",
        )
```

- [ ] **Step 4.4: Run all gate tests, verify pass**

```bash
pytest tests/test_policy_gate.py tests/test_source_resolver.py -v
```

Expected: 6 + 6 = 12 passed.

- [ ] **Step 4.5: Commit**

```bash
git add core/lineage/policy_gate.py tests/test_policy_gate.py
git commit -m "feat(lineage): policy_gate full impl with promotion-time fail-closed (task 4)"
```

---

## Task 5: BQ DDL loader + view

**Files:**
- Create: `core/bq/load/load_lineage_tables.py`
- Create: `core/bq/views/v_raw_objects_current.sql`
- Test: `tests/test_load_lineage_tables.py`

- [ ] **Step 5.1: Create the view SQL**

Create `core/bq/views/v_raw_objects_current.sql`:

```sql
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_raw_objects_current` AS
WITH latest_event AS (
  SELECT
    raw_object_id,
    to_status        AS current_status,
    event_at         AS last_event_at,
    pipeline_run_id  AS last_pipeline_run_id,
    reason           AS last_rejection_reason,
    ROW_NUMBER() OVER (
      PARTITION BY raw_object_id
      ORDER BY event_at DESC, event_id DESC
    ) AS rn
  FROM `hotelops-suite.hotelops.f_lineage_events`
  WHERE to_status IS NOT NULL
)
SELECT
  ro.*,
  COALESCE(le.current_status, 'RAW_ONLY') AS current_status,
  le.last_event_at,
  le.last_pipeline_run_id,
  le.last_rejection_reason
FROM `hotelops-suite.hotelops.f_raw_objects` ro
LEFT JOIN latest_event le
  ON le.raw_object_id = ro.raw_object_id
  AND le.rn = 1;
```

- [ ] **Step 5.2: Write failing test for DDL loader**

Create `tests/test_load_lineage_tables.py`:

```python
"""DDL loader for f_raw_objects, f_lineage_events, v_raw_objects_current."""

from unittest.mock import MagicMock

from core.bq.load.load_lineage_tables import (
    DDL_FACT_LINEAGE_EVENTS,
    DDL_FACT_RAW_OBJECTS,
    SQL_VIEW_RAW_OBJECTS_CURRENT,
    create_lineage_tables,
)


def test_ddl_strings_are_valid() -> None:
    assert "CREATE TABLE" in DDL_FACT_RAW_OBJECTS or "CREATE OR REPLACE TABLE" in DDL_FACT_RAW_OBJECTS
    assert "f_raw_objects" in DDL_FACT_RAW_OBJECTS
    assert "PARTITION BY" in DDL_FACT_RAW_OBJECTS

    assert "f_lineage_events" in DDL_FACT_LINEAGE_EVENTS
    assert "PARTITION BY" in DDL_FACT_LINEAGE_EVENTS

    assert "CREATE OR REPLACE VIEW" in SQL_VIEW_RAW_OBJECTS_CURRENT
    assert "v_raw_objects_current" in SQL_VIEW_RAW_OBJECTS_CURRENT


def test_create_lineage_tables_executes_3_statements(monkeypatch) -> None:
    fake_client = MagicMock()
    fake_client.query.return_value.result.return_value = None
    monkeypatch.setattr(
        "core.bq.load.load_lineage_tables.get_client", lambda: fake_client
    )
    create_lineage_tables(dry_run=False)
    assert fake_client.query.call_count == 3


def test_create_lineage_tables_dry_run_does_not_call(monkeypatch) -> None:
    fake_client = MagicMock()
    monkeypatch.setattr(
        "core.bq.load.load_lineage_tables.get_client", lambda: fake_client
    )
    create_lineage_tables(dry_run=True)
    assert fake_client.query.call_count == 0
```

- [ ] **Step 5.3: Run, verify FAIL**

```bash
pytest tests/test_load_lineage_tables.py -v
```

- [ ] **Step 5.4: Implement loader**

Create `core/bq/load/load_lineage_tables.py`:

```python
"""DDL loader for the lineage tables.

Idempotent: CREATE TABLE IF NOT EXISTS for facts, CREATE OR REPLACE VIEW for the view.

Spec: §3.3, §4.2, §4.3, §4.4
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.bq.client import get_client

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"

DDL_FACT_RAW_OBJECTS = f"""
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.f_raw_objects` (
  raw_object_id        STRING NOT NULL,
  content_hash         STRING NOT NULL,
  raw_uri              STRING NOT NULL,
  raw_backend          STRING NOT NULL,
  file_name_original   STRING NOT NULL,
  file_name_canonical  STRING,
  bytes_size           INT64 NOT NULL,
  source_name          STRING,
  detector_category    STRING,
  societa_id           STRING,
  business_unit_id     STRING,
  banca_id             STRING,
  intake_at            TIMESTAMP NOT NULL,
  intake_actor         STRING NOT NULL,
  pipeline_run_id      STRING,
  pipeline_name        STRING,
  file_sorgente        STRING,
  ingestion_ts         TIMESTAMP NOT NULL
)
PARTITION BY DATE(intake_at)
CLUSTER BY content_hash, source_name
"""

DDL_FACT_LINEAGE_EVENTS = f"""
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.f_lineage_events` (
  event_id          STRING NOT NULL,
  raw_object_id     STRING NOT NULL,
  event_type        STRING NOT NULL,
  event_at          TIMESTAMP NOT NULL,
  actor             STRING NOT NULL,
  pipeline_run_id   STRING,
  pipeline_name     STRING,
  from_status       STRING,
  to_status         STRING,
  payload_json      STRING,
  reason            STRING
)
PARTITION BY DATE(event_at)
CLUSTER BY raw_object_id, event_type
"""

_VIEW_SQL_PATH = (
    Path(__file__).resolve().parents[1] / "views" / "v_raw_objects_current.sql"
)
SQL_VIEW_RAW_OBJECTS_CURRENT = _VIEW_SQL_PATH.read_text(encoding="utf-8")


def create_lineage_tables(dry_run: bool = False) -> None:
    """Create the 2 fact tables + 1 view. Idempotent."""
    statements = [
        ("f_raw_objects", DDL_FACT_RAW_OBJECTS),
        ("f_lineage_events", DDL_FACT_LINEAGE_EVENTS),
        ("v_raw_objects_current", SQL_VIEW_RAW_OBJECTS_CURRENT),
    ]
    if dry_run:
        for name, sql in statements:
            log.info("[DRY-RUN] would execute DDL for %s", name)
        return
    client = get_client()
    for name, sql in statements:
        log.info("Creating %s ...", name)
        client.query(sql).result()
        log.info("✓ %s ready", name)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    create_lineage_tables(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5.5: Run tests, verify pass**

```bash
pytest tests/test_load_lineage_tables.py -v
```

Expected: 3 passed.

- [ ] **Step 5.6: Commit**

```bash
git add core/bq/load/load_lineage_tables.py core/bq/views/v_raw_objects_current.sql tests/test_load_lineage_tables.py
git commit -m "feat(lineage): DDL loader + v_raw_objects_current view (task 5)"
```

- [ ] **Step 5.7: Materialize on BQ produzione (manual step)**

```bash
python -m core.bq.load.load_lineage_tables --dry-run   # preview
python -m core.bq.load.load_lineage_tables             # apply
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM `hotelops-suite.hotelops.f_raw_objects`'
bq query --use_legacy_sql=false 'SELECT COUNT(*) FROM `hotelops-suite.hotelops.v_raw_objects_current`'
```

Expected: both return 0 rows; no error.

---

## Task 6: Raw manifest store (high-level API)

**Files:**
- Create: `core/lineage/raw_manifest.py`
- Test: `tests/test_raw_manifest.py`

- [ ] **Step 6.1: Write failing tests**

Create `tests/test_raw_manifest.py`:

```python
"""High-level API for raw object lifecycle persistence."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from core.lineage.raw_manifest import (
    emit_event,
    register_raw_object,
)
from core.lineage.schemas import RawObject


def _fake_run(monkeypatch) -> None:
    fake_run = MagicMock()
    fake_run.run_id = "run-test"
    fake_run.pipeline_name = "test_pipeline"
    fake_run.file_sorgente = None
    monkeypatch.setattr(
        "core.bq.write.PipelineRun.get_current",
        lambda: fake_run,
        raising=False,
    )


def test_register_writes_via_gate(monkeypatch, tmp_path) -> None:
    written = {}
    def fake_write(table, rows, mode="append", natural_key=None):
        written.setdefault("calls", []).append((table, rows, mode))
    monkeypatch.setattr(
        "core.lineage.raw_manifest.bq_write_validated", fake_write
    )

    raw_id = register_raw_object(
        content_hash="abc",
        raw_uri="file:///tmp/x.xlsx",
        raw_backend="local",
        file_name_original="x.xlsx",
        bytes_size=10,
        intake_actor="cli",
    )
    assert raw_id
    assert "calls" in written
    table, rows, mode = written["calls"][0]
    assert table.endswith("f_raw_objects")
    assert mode == "append"
    assert isinstance(rows[0], RawObject)


def test_register_dedup_returns_existing_on_same_hash(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.lineage.raw_manifest.bq_write_validated", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "core.lineage.raw_manifest._lookup_existing_by_hash",
        lambda h: "existing-id" if h == "dedup-hash" else None,
    )
    raw_id = register_raw_object(
        content_hash="dedup-hash",
        raw_uri="file:///tmp/y.xlsx",
        raw_backend="local",
        file_name_original="y.xlsx",
        bytes_size=20,
        intake_actor="cli",
    )
    assert raw_id == "existing-id"


def test_emit_event_writes_to_lineage_events(monkeypatch) -> None:
    written = []
    monkeypatch.setattr(
        "core.lineage.raw_manifest.bq_write_validated",
        lambda table, rows, mode="append", natural_key=None: written.append((table, rows)),
    )
    emit_event(
        raw_object_id="abc-123",
        event_type="RAW_INGESTED",
        actor="cli",
        from_status=None,
        to_status="RAW_ONLY",
    )
    assert len(written) == 1
    table, rows = written[0]
    assert table.endswith("f_lineage_events")
    assert rows[0].event_type == "RAW_INGESTED"


def test_emit_event_validates_transition(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.lineage.raw_manifest.bq_write_validated", lambda *a, **kw: None
    )
    with pytest.raises(Exception):  # InvalidTransition raised by state_machine
        emit_event(
            raw_object_id="abc-123",
            event_type="PROMOTED",
            actor="cli",
            from_status="RAW_ONLY",   # forbidden: must be PROMOTABLE
            to_status="PROMOTED",
        )
```

- [ ] **Step 6.2: Run, verify FAIL**

```bash
pytest tests/test_raw_manifest.py -v
```

- [ ] **Step 6.3: Implement raw_manifest.py**

Create `core/lineage/raw_manifest.py`:

```python
"""High-level API for raw object lifecycle persistence.

Confined: ALL writes to f_raw_objects and f_lineage_events go through this module.
ALL writes use bq_write_validated(append) — never raw client. I1 strict.

Spec: §3.3, §5.3
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from core.bq.write import bq_write_validated
from core.lineage.schemas import (
    LineageEvent,
    LineageEventType,
    RawBackend,
    RawObject,
    RawObjectStatus,
    RejectionReason,
)
from core.lineage.state_machine import next_status_after_event

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"
F_RAW_OBJECTS = f"{PROJECT}.{DATASET}.f_raw_objects"
F_LINEAGE_EVENTS = f"{PROJECT}.{DATASET}.f_lineage_events"
V_RAW_OBJECTS_CURRENT = f"{PROJECT}.{DATASET}.v_raw_objects_current"


def _lookup_existing_by_hash(content_hash: str) -> Optional[str]:
    """Return raw_object_id of an existing row with this hash, or None."""
    from core.bq.client import get_client
    from google.cloud import bigquery

    client = get_client()
    sql = f"""
    SELECT raw_object_id
    FROM `{F_RAW_OBJECTS}`
    WHERE content_hash = @hash
    LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("hash", "STRING", content_hash)]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    return rows[0].raw_object_id if rows else None


def register_raw_object(
    content_hash: str,
    raw_uri: str,
    raw_backend: RawBackend,
    file_name_original: str,
    bytes_size: int,
    intake_actor: str,
    file_name_canonical: Optional[str] = None,
    source_name: Optional[str] = None,
    detector_category: Optional[str] = None,
    societa_id: Optional[str] = None,
    business_unit_id: Optional[str] = None,
    banca_id: Optional[str] = None,
    file_sorgente: Optional[str] = None,
) -> str:
    """Write a new row to f_raw_objects (or return existing id on dedup).

    Generates raw_object_id (UUID4). Lineage fields (pipeline_run_id, pipeline_name)
    are populated via PipelineRun.get_current() inside bq_write_validated.
    """
    existing = _lookup_existing_by_hash(content_hash)
    if existing:
        log.info(
            "register_raw_object: dedup hit on %s, returning existing %s",
            content_hash[:12], existing,
        )
        return existing

    now = datetime.now(timezone.utc)
    raw_object_id = str(uuid.uuid4())

    # PipelineRun ContextVar is read by bq_write_validated for lineage fields;
    # we still need to pass them on the Pydantic row (REQUIRED). Read here.
    from core.pipeline_run import PipelineRun

    run = PipelineRun.get_current()
    pipeline_run_id = run.run_id if run else str(uuid.uuid4())
    pipeline_name = run.pipeline_name if run else "intake_standalone"

    row = RawObject(
        raw_object_id=raw_object_id,
        content_hash=content_hash,
        raw_uri=raw_uri,
        raw_backend=raw_backend,
        file_name_original=file_name_original,
        file_name_canonical=file_name_canonical,
        bytes_size=bytes_size,
        source_name=source_name,
        detector_category=detector_category,
        societa_id=societa_id,
        business_unit_id=business_unit_id,
        banca_id=banca_id,
        intake_at=now,
        intake_actor=intake_actor,
        pipeline_run_id=pipeline_run_id,
        pipeline_name=pipeline_name,
        file_sorgente=file_sorgente,
        ingestion_ts=now,
    )
    bq_write_validated(F_RAW_OBJECTS, [row], mode="append")
    return raw_object_id


def emit_event(
    raw_object_id: str,
    event_type: LineageEventType,
    actor: str,
    from_status: Optional[RawObjectStatus] = None,
    to_status: Optional[RawObjectStatus] = None,
    reason: Optional[RejectionReason] = None,
    payload: Optional[dict] = None,
) -> str:
    """Append a LineageEvent. Validates transition before writing.

    For non-transitional events (DETECTED, VALIDATED_*, PROMOTION_REQUESTED),
    pass to_status=None.
    """
    # Validate transition (raises InvalidTransition if forbidden)
    expected_to = next_status_after_event(from_status, event_type)
    if to_status is not None and expected_to is not None and to_status != expected_to:
        raise ValueError(
            f"Inconsistent transition: event {event_type} from {from_status} "
            f"yields {expected_to}, caller passed to_status={to_status}"
        )

    from core.pipeline_run import PipelineRun

    run = PipelineRun.get_current()
    event = LineageEvent(
        event_id=str(uuid.uuid4()),
        raw_object_id=raw_object_id,
        event_type=event_type,
        event_at=datetime.now(timezone.utc),
        actor=actor,
        pipeline_run_id=run.run_id if run else None,
        pipeline_name=run.pipeline_name if run else None,
        from_status=from_status,
        to_status=to_status if to_status is not None else expected_to,
        payload_json=json.dumps(payload, default=str) if payload else None,
        reason=reason,
    )
    bq_write_validated(F_LINEAGE_EVENTS, [event], mode="append")
    return event.event_id


def latest_status(raw_object_id: str) -> Optional[RawObjectStatus]:
    """Read current status from v_raw_objects_current."""
    from core.bq.client import get_client
    from google.cloud import bigquery

    client = get_client()
    sql = f"""
    SELECT current_status
    FROM `{V_RAW_OBJECTS_CURRENT}`
    WHERE raw_object_id = @id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", raw_object_id)]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    return rows[0].current_status if rows else None
```

- [ ] **Step 6.4: Run tests, verify pass**

```bash
pytest tests/test_raw_manifest.py -v
```

Expected: 4 passed.

- [ ] **Step 6.5: Commit**

```bash
git add core/lineage/raw_manifest.py tests/test_raw_manifest.py
git commit -m "feat(lineage): raw_manifest API (register + emit_event via gate) (task 6)"
```

---

## Task 7: Intake entrypoint

**Files:**
- Create: `ingest/intake.py`
- Test: `tests/test_intake.py`

- [ ] **Step 7.1: Write failing tests**

Create `tests/test_intake.py`:

```python
"""Intake entrypoint: file → raw blob + RAW_INGESTED event."""

from pathlib import Path

import pytest

from ingest.intake import IntakeResult, intake_file


def _fixture_xlsx(tmp_path: Path) -> Path:
    f = tmp_path / "ESOLVER_BILANCINO_ORTI_apr.xls"
    f.write_bytes(b"FAKE_XLS_CONTENT_FOR_HASH")
    return f


def test_intake_basic(monkeypatch, tmp_path) -> None:
    captured = {}
    def fake_register(**kwargs):
        captured["register"] = kwargs
        return "raw-id-1"
    def fake_emit(**kwargs):
        captured.setdefault("events", []).append(kwargs)
        return f"ev-{len(captured['events'])}"
    monkeypatch.setattr("ingest.intake.register_raw_object", fake_register)
    monkeypatch.setattr("ingest.intake.emit_event", fake_emit)

    f = _fixture_xlsx(tmp_path)
    result = intake_file(
        f,
        source_name="ESOLVER_BILANCINO_ORTI_SNAPSHOT",
        actor="test",
    )
    assert isinstance(result, IntakeResult)
    assert result.raw_object_id == "raw-id-1"
    assert captured["register"]["content_hash"]
    assert captured["register"]["source_name"] == "ESOLVER_BILANCINO_ORTI_SNAPSHOT"
    # 1 event: RAW_INGESTED
    assert len(captured["events"]) == 1
    assert captured["events"][0]["event_type"] == "RAW_INGESTED"
    assert captured["events"][0]["to_status"] == "RAW_ONLY"


def test_intake_unknown_source_raises(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("ingest.intake.register_raw_object", lambda **kw: "x")
    monkeypatch.setattr("ingest.intake.emit_event", lambda **kw: "x")
    f = _fixture_xlsx(tmp_path)
    with pytest.raises(Exception):  # source_name not in registry
        intake_file(f, source_name="FAKE_DATASET_ORTI_APPEND", actor="test")


def test_intake_no_source_skips_classification_event(monkeypatch, tmp_path) -> None:
    captured = {"events": []}
    monkeypatch.setattr("ingest.intake.register_raw_object", lambda **kw: "raw-id")
    monkeypatch.setattr(
        "ingest.intake.emit_event",
        lambda **kw: captured["events"].append(kw) or "ev-1",
    )
    f = _fixture_xlsx(tmp_path)
    result = intake_file(f, source_name=None, actor="test")
    # Only RAW_INGESTED — no SOURCE_RESOLVED, no DETECTED
    types = [ev["event_type"] for ev in captured["events"]]
    assert types == ["RAW_INGESTED"]
```

- [ ] **Step 7.2: Run, verify FAIL**

```bash
pytest tests/test_intake.py -v
```

- [ ] **Step 7.3: Implement intake.py**

Create `ingest/intake.py`:

```python
"""Intake entrypoint — file + source metadata → raw blob + RAW_INGESTED event.

Spec: §3.1, §5.2 (∅ → RAW_ONLY transition)
"""

from __future__ import annotations

import argparse
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.lineage.policy_gate import enforce_loop_target_gate_consistency
from core.lineage.raw_manifest import emit_event, register_raw_object
from core.lineage.source_resolver import load_registry
from core.pipeline_run import PipelineRun

log = logging.getLogger(__name__)


@dataclass
class IntakeResult:
    raw_object_id: str
    content_hash: str
    source_name: Optional[str]
    deduped: bool


def _file_md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        while True:
            block = f.read(1 << 20)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def intake_file(
    path: Path,
    source_name: Optional[str] = None,
    actor: str = "cli",
    raw_backend: str = "local",
    raw_uri: Optional[str] = None,
) -> IntakeResult:
    """Register a file in the lineage layer.

    If source_name is provided, it must exist in the registry; the source_def
    is propagated to the RawObject row (societa, detector_category, etc.).
    If source_name is None, the row is registered as RAW_ONLY without source binding.

    Phase 1: blob storage is the file's existing path (raw_backend='local' or 'drive').
    Phase 4: blob is written to GCS first, then registered.
    """
    if not path.exists():
        raise FileNotFoundError(path)

    content_hash = _file_md5(path)
    bytes_size = path.stat().st_size
    raw_uri_final = raw_uri or path.resolve().as_uri()

    # Resolve source if provided
    source_def = None
    if source_name is not None:
        reg = load_registry()
        source_def = reg.get(source_name)
        if source_def is None:
            raise KeyError(f"source_name not in registry: {source_name}")
        # Boot-time check for the resolved source
        enforce_loop_target_gate_consistency(source_def)

    with PipelineRun(
        "ingest_intake",
        societa_id=source_def.societa if source_def else None,
        file_sorgente=str(path),
    ):
        raw_object_id = register_raw_object(
            content_hash=content_hash,
            raw_uri=raw_uri_final,
            raw_backend=raw_backend,
            file_name_original=path.name,
            bytes_size=bytes_size,
            intake_actor=actor,
            source_name=source_name,
            detector_category=source_def.detector_category if source_def else None,
            societa_id=source_def.societa if source_def else None,
            business_unit_id=source_def.business_unit if source_def else None,
            file_sorgente=str(path),
        )

        # Always emit RAW_INGESTED for new objects. (register_raw_object dedups
        # internally; if dedup hit, we skip the event to keep log idempotent.)
        # Heuristic: dedup ⇒ raw_object_id was already in BQ ⇒ check via lookup.
        # Phase 1 simplification: emit always; phase 2 add dedup check before emit.
        emit_event(
            raw_object_id=raw_object_id,
            event_type="RAW_INGESTED",
            actor=actor,
            from_status=None,
            to_status="RAW_ONLY",
            payload={
                "file_name": path.name,
                "bytes_size": bytes_size,
                "raw_backend": raw_backend,
            },
        )

    return IntakeResult(
        raw_object_id=raw_object_id,
        content_hash=content_hash,
        source_name=source_name,
        deduped=False,  # Phase 1 placeholder
    )


def main() -> None:
    p = argparse.ArgumentParser(prog="intake")
    p.add_argument("file", type=Path)
    p.add_argument("--source-name", default=None)
    p.add_argument("--actor", default="cli")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    result = intake_file(args.file, source_name=args.source_name, actor=args.actor)
    print(f"raw_object_id={result.raw_object_id}")
    print(f"content_hash={result.content_hash}")
    print(f"source_name={result.source_name}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7.4: Run tests, verify pass**

```bash
pytest tests/test_intake.py -v
```

Expected: 3 passed.

- [ ] **Step 7.5: Commit**

```bash
git add ingest/intake.py tests/test_intake.py
git commit -m "feat(lineage): intake entrypoint — file → RAW_INGESTED event (task 7)"
```

---

## Task 8: Promotion entrypoint

**Files:**
- Create: `ingest/promotion.py`
- Test: `tests/test_promotion.py`

- [ ] **Step 8.1: Write failing tests**

Create `tests/test_promotion.py`:

```python
"""Promotion entrypoint: PROMOTABLE raw_object → parser → bq_write_validated → PROMOTED."""

from unittest.mock import MagicMock

import pytest

from core.lineage.policy_gate import PolicyViolation
from ingest.promotion import PromotionResult, promote_raw_object


@pytest.fixture
def fake_registry(monkeypatch):
    """Patch source_resolver to return a fake source_def."""
    fake_source = MagicMock()
    fake_source.source_name = "ESOLVER_BILANCINO_ORTI_SNAPSHOT"
    fake_source.promotion_policy = "AUTO"
    fake_source.parser_module = "ingest.flussi.ingest_bilancino"
    fake_source.parser_entrypoint = "main"
    fake_source.canonical_table = "f_bilancino"
    fake_source.lifecycle = "SNAPSHOT"
    fake_source.natural_key = ["data_snapshot", "societa_id"]
    fake_source.loop_targets = ["monthly_close"]
    fake_source.societa = "ORTI"

    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source if name == fake_source.source_name else None
    monkeypatch.setattr("ingest.promotion.load_registry", lambda: fake_reg)
    return fake_source


@pytest.fixture
def captured_events(monkeypatch):
    events = []
    monkeypatch.setattr(
        "ingest.promotion.emit_event",
        lambda **kw: events.append(kw) or f"ev-{len(events)}",
    )
    return events


@pytest.fixture
def fake_raw_object(monkeypatch):
    """Patch the raw_object lookup to return a fake row."""
    fake = MagicMock()
    fake.raw_object_id = "raw-1"
    fake.source_name = "ESOLVER_BILANCINO_ORTI_SNAPSHOT"
    fake.raw_uri = "file:///tmp/x.xlsx"
    monkeypatch.setattr("ingest.promotion._fetch_raw_object", lambda rid: fake)
    return fake


def test_promote_happy_path(monkeypatch, fake_registry, captured_events, fake_raw_object) -> None:
    monkeypatch.setattr(
        "ingest.promotion.latest_status", lambda rid: "PROMOTABLE"
    )
    fake_parser_invoke = MagicMock(return_value={"rows_written": 42})
    monkeypatch.setattr("ingest.promotion._invoke_parser", fake_parser_invoke)

    result = promote_raw_object("raw-1", actor="test")

    assert result.status == "PROMOTED"
    types = [ev["event_type"] for ev in captured_events]
    assert "PROMOTION_REQUESTED" in types
    assert "VALIDATED_OK" in types
    assert "PROMOTED" in types
    fake_parser_invoke.assert_called_once()


def test_promote_raw_only_source_rejected(monkeypatch, captured_events, fake_raw_object) -> None:
    fake_raw_object.source_name = "POWERBI_CRUSCOTTO_ORTI_APPEND"
    fake_source = MagicMock()
    fake_source.source_name = "POWERBI_CRUSCOTTO_ORTI_APPEND"
    fake_source.promotion_policy = "RAW_ONLY"
    fake_source.loop_targets = []
    fake_reg = MagicMock()
    fake_reg.get = lambda name: fake_source
    monkeypatch.setattr("ingest.promotion.load_registry", lambda: fake_reg)
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")

    result = promote_raw_object("raw-1", actor="test")
    assert result.status == "REJECTED"
    assert result.reason == "NO_LOOP_TARGET"
    types = [ev["event_type"] for ev in captured_events]
    assert "REJECTED" in types


def test_promote_parser_failure_emits_validate_fail(monkeypatch, fake_registry, captured_events, fake_raw_object) -> None:
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTABLE")
    monkeypatch.setattr(
        "ingest.promotion._invoke_parser",
        MagicMock(side_effect=ValueError("parser broke")),
    )
    result = promote_raw_object("raw-1", actor="test")
    assert result.status == "REJECTED"
    assert result.reason == "VALIDATE_FAIL"
    types = [ev["event_type"] for ev in captured_events]
    assert "VALIDATED_FAIL" in types
    assert "REJECTED" in types


def test_promote_already_promoted_is_noop(monkeypatch, fake_registry, captured_events, fake_raw_object) -> None:
    monkeypatch.setattr("ingest.promotion.latest_status", lambda rid: "PROMOTED")
    fake_parser = MagicMock()
    monkeypatch.setattr("ingest.promotion._invoke_parser", fake_parser)
    result = promote_raw_object("raw-1", actor="test")
    assert result.status == "PROMOTED"
    assert result.noop is True
    fake_parser.assert_not_called()
    assert captured_events == []
```

- [ ] **Step 8.2: Run, verify FAIL**

```bash
pytest tests/test_promotion.py -v
```

- [ ] **Step 8.3: Implement promotion.py**

Create `ingest/promotion.py`:

```python
"""Promotion entrypoint — PROMOTABLE raw_object → parser run → canonical write → PROMOTED.

Spec: §3.1, §5.2 (PROMOTABLE → PROMOTED transition), §7.1 (hard gate)
"""

from __future__ import annotations

import argparse
import importlib
import logging
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

from core.lineage.policy_gate import (
    PolicyViolation,
    enforce_loop_target_gate_at_promotion,
)
from core.lineage.raw_manifest import (
    F_RAW_OBJECTS,
    emit_event,
    latest_status,
)
from core.lineage.source_resolver import load_registry
from core.pipeline_run import PipelineRun

log = logging.getLogger(__name__)


@dataclass
class PromotionResult:
    raw_object_id: str
    status: str               # PROMOTED | REJECTED | NOOP
    reason: Optional[str] = None
    rows_written: int = 0
    noop: bool = False


def _fetch_raw_object(raw_object_id: str):
    """Lookup raw_object row from BQ. Returns object with attribute access."""
    from core.bq.client import get_client
    from google.cloud import bigquery

    client = get_client()
    sql = f"SELECT * FROM `{F_RAW_OBJECTS}` WHERE raw_object_id = @id"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", raw_object_id)]
    )
    rows = list(client.query(sql, job_config=job_config).result())
    if not rows:
        raise KeyError(f"raw_object_id not found: {raw_object_id}")
    return rows[0]


def _invoke_parser(parser_module: str, raw_uri: str, source_def) -> dict:
    """Invoke the parser via subprocess (preserves PipelineRun isolation per parser).

    Phase 1: parsers expect --file <path> and optionally --societa. We translate
    raw_uri (file:// or gs://) to a local path. For drive backend in Phase 1,
    raw_uri is already file://.

    Returns: {"rows_written": int} (best-effort; parser may not report).
    """
    from urllib.parse import urlparse

    parsed = urlparse(raw_uri)
    if parsed.scheme not in ("file", ""):
        raise NotImplementedError(
            f"Phase 1 only supports file:// raw_uri, got {parsed.scheme}"
        )
    local_path = parsed.path

    cmd = [sys.executable, "-m", parser_module, "--file", local_path]
    if source_def.societa in ("ORTI", "INTUR"):
        cmd += ["--societa", source_def.societa]

    log.info("Invoking parser: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Parser {parser_module} failed (exit {proc.returncode}): "
            f"{proc.stderr.strip()[:500]}"
        )
    return {"rows_written": -1}  # parsers don't report; -1 = unknown


def promote_raw_object(raw_object_id: str, actor: str = "cli") -> PromotionResult:
    """Promote a single raw_object to canonical.

    Sequence:
      1. Fetch raw_object + source_def
      2. Check current_status (idempotent if already PROMOTED)
      3. Hard gate (NO_LOOP_TARGET if RAW_ONLY)
      4. Emit PROMOTION_REQUESTED
      5. Invoke parser via subprocess
      6. On parser ok: emit VALIDATED_OK + PROMOTED
      7. On parser fail: emit VALIDATED_FAIL + REJECTED(VALIDATE_FAIL)
    """
    raw = _fetch_raw_object(raw_object_id)

    # Idempotency
    current = latest_status(raw_object_id)
    if current == "PROMOTED":
        log.info("raw_object_id=%s already PROMOTED, skipping", raw_object_id)
        return PromotionResult(raw_object_id, status="PROMOTED", noop=True)

    if not raw.source_name:
        raise ValueError(
            f"raw_object_id={raw_object_id} has no source_name; classify first"
        )

    reg = load_registry()
    source_def = reg.get(raw.source_name)
    if source_def is None:
        raise KeyError(f"source_name not in registry: {raw.source_name}")

    # Hard gate
    try:
        enforce_loop_target_gate_at_promotion(source_def)
    except PolicyViolation as e:
        emit_event(
            raw_object_id=raw_object_id,
            event_type="REJECTED",
            actor=actor,
            from_status=current or "CLASSIFIED",
            to_status="REJECTED",
            reason="NO_LOOP_TARGET",
            payload={"source_name": raw.source_name, "message": str(e)},
        )
        return PromotionResult(raw_object_id, status="REJECTED", reason="NO_LOOP_TARGET")

    with PipelineRun(
        "promotion",
        societa_id=getattr(raw, "societa_id", None),
        file_sorgente=getattr(raw, "raw_uri", None),
    ):
        emit_event(
            raw_object_id=raw_object_id,
            event_type="PROMOTION_REQUESTED",
            actor=actor,
            from_status=current,
            to_status=None,
            payload={"parser_module": source_def.parser_module},
        )

        try:
            parser_result = _invoke_parser(
                source_def.parser_module, raw.raw_uri, source_def
            )
        except Exception as e:
            emit_event(
                raw_object_id=raw_object_id,
                event_type="VALIDATED_FAIL",
                actor=actor,
                payload={"error": str(e)[:500]},
            )
            emit_event(
                raw_object_id=raw_object_id,
                event_type="REJECTED",
                actor=actor,
                from_status="PROMOTABLE",
                to_status="REJECTED",
                reason="VALIDATE_FAIL",
                payload={"error": str(e)[:500]},
            )
            return PromotionResult(
                raw_object_id, status="REJECTED", reason="VALIDATE_FAIL"
            )

        emit_event(
            raw_object_id=raw_object_id,
            event_type="VALIDATED_OK",
            actor=actor,
            payload=parser_result,
        )
        emit_event(
            raw_object_id=raw_object_id,
            event_type="PROMOTED",
            actor=actor,
            from_status="PROMOTABLE",
            to_status="PROMOTED",
            payload={
                "canonical_table": source_def.canonical_table,
                **parser_result,
            },
        )
        return PromotionResult(
            raw_object_id,
            status="PROMOTED",
            rows_written=parser_result.get("rows_written", 0),
        )


def main() -> None:
    p = argparse.ArgumentParser(prog="promotion")
    p.add_argument("--raw-object-id", required=True)
    p.add_argument("--actor", default="cli")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    r = promote_raw_object(args.raw_object_id, actor=args.actor)
    print(f"status={r.status} reason={r.reason or '-'} rows_written={r.rows_written} noop={r.noop}")
    if r.status == "REJECTED":
        sys.exit(2)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8.4: Run tests, verify pass**

```bash
pytest tests/test_promotion.py -v
```

Expected: 4 passed.

- [ ] **Step 8.5: Commit**

```bash
git add ingest/promotion.py tests/test_promotion.py
git commit -m "feat(lineage): promotion entrypoint with hard gate + parser dispatch (task 8)"
```

---

## Task 9: CLI subcommands (additive)

**Files:**
- Modify: `cli.py` (add 3 subparsers + handlers, no change to existing handlers)

- [ ] **Step 9.1: Add handlers + subparsers**

Edit `cli.py`. Find the imports block (around line 67-79) and add a comment marker for traceability — actual lazy imports happen inside handlers per existing convention.

Then, after the existing `cmd_drop` definition (around line 428), add:

```python
# ── Lineage subcommands (Phase 1 — additive) ──────────────────────────────────


def cmd_intake(args):
    """Register a file in the lineage layer (no canonical write)."""
    from pathlib import Path

    from ingest.intake import intake_file

    result = intake_file(
        Path(args.file),
        source_name=args.source_name,
        actor="cli",
    )
    print(f"raw_object_id: {result.raw_object_id}")
    print(f"content_hash:  {result.content_hash}")
    print(f"source_name:   {result.source_name or '(none)'}")


def cmd_promote(args):
    """Promote a PROMOTABLE raw_object to canonical via its source policy."""
    from ingest.promotion import promote_raw_object

    if args.raw_object_id:
        r = promote_raw_object(args.raw_object_id, actor="cli")
        print(f"status={r.status} reason={r.reason or '-'} rows={r.rows_written} noop={r.noop}")
        if r.status == "REJECTED":
            sys.exit(2)
        return

    print("--all-promotable not yet implemented in Phase 1 (use --raw-object-id)")
    sys.exit(1)


def cmd_lineage(args):
    """Inspect a raw_object: identity + event history + current status."""
    from core.bq.client import get_client
    from core.lineage.raw_manifest import (
        F_LINEAGE_EVENTS,
        F_RAW_OBJECTS,
        V_RAW_OBJECTS_CURRENT,
    )
    from google.cloud import bigquery

    client = get_client()
    p = bigquery.ScalarQueryParameter("id", "STRING", args.raw_object_id)
    qc = bigquery.QueryJobConfig(query_parameters=[p])

    print("\n  Identity:")
    rows = list(client.query(
        f"SELECT * FROM `{F_RAW_OBJECTS}` WHERE raw_object_id = @id",
        job_config=qc,
    ).result())
    if not rows:
        print(f"  ❌ raw_object_id not found: {args.raw_object_id}")
        sys.exit(1)
    r = rows[0]
    for k in ("source_name", "societa_id", "file_name_original", "intake_at", "raw_uri"):
        print(f"    {k}: {getattr(r, k, '-')}")

    print("\n  Current status:")
    cur = list(client.query(
        f"SELECT current_status, last_event_at FROM `{V_RAW_OBJECTS_CURRENT}` "
        f"WHERE raw_object_id = @id",
        job_config=qc,
    ).result())
    if cur:
        print(f"    {cur[0].current_status}  (last event: {cur[0].last_event_at})")

    print("\n  Event history:")
    events = list(client.query(
        f"SELECT event_type, event_at, actor, from_status, to_status, reason "
        f"FROM `{F_LINEAGE_EVENTS}` WHERE raw_object_id = @id ORDER BY event_at",
        job_config=qc,
    ).result())
    for ev in events:
        transition = (
            f"{ev.from_status or '∅'} → {ev.to_status}" if ev.to_status else "(no transition)"
        )
        reason = f"  [{ev.reason}]" if ev.reason else ""
        print(f"    {ev.event_at}  {ev.event_type:<22s} {transition}{reason}")
    print()
```

- [ ] **Step 9.2: Add subparsers in `main()`**

In `cli.py` `main()`, after the existing `p_rec` block (around line 779), add:

```python
    # ── Lineage subcommands (Phase 1) ──────────────────────────────────────
    p_intake = sub.add_parser(
        "intake",
        help="Lineage: registra un file (raw blob + RAW_INGESTED event)",
    )
    p_intake.add_argument("file", help="Path al file")
    p_intake.add_argument(
        "--source-name",
        default=None,
        help="source_name del registry (es. ESOLVER_BILANCINO_ORTI_SNAPSHOT)",
    )

    p_promote = sub.add_parser(
        "promote",
        help="Lineage: promuovi raw_object a canonical (parser + bq_write_validated)",
    )
    p_promote.add_argument("--raw-object-id", required=True)

    p_lin = sub.add_parser(
        "lineage", help="Lineage: ispeziona raw_object + storia eventi"
    )
    p_lin.add_argument("raw_object_id")
```

And add to the `handlers` dict:

```python
        "intake": cmd_intake,
        "promote": cmd_promote,
        "lineage": cmd_lineage,
```

- [ ] **Step 9.3: Smoke test the CLI**

```bash
hotelops intake --help
hotelops promote --help
hotelops lineage --help
hotelops --help | grep -E "(intake|promote|lineage)"
```

Expected: each subcommand renders its help; root help lists all 3.

- [ ] **Step 9.4: Run full test suite**

```bash
pytest -q
```

Expected: all tests pass — both new (lineage) and existing (untouched).

- [ ] **Step 9.5: Commit**

```bash
git add cli.py
git commit -m "feat(cli): add hotelops intake/promote/lineage subcommands (task 9)"
```

---

## Task 10: Documentation updates

**Files:**
- Modify: `CLAUDE.md` (add §Lineage)
- Modify: `docs/architecture/DATA_ENGINEERING_RULES.md` (add §10 link)
- Modify: `docs/superpowers/specs/2026-04-02-manifest-shadow-os-design.md` (banner SUPERSEDED)
- Modify: `STATUS.md` (in-corso entry)

- [ ] **Step 10.1: Add §Lineage to `CLAUDE.md`**

In `CLAUDE.md`, find the "Architecture" section. After the description of `core/`, before `**ingest/**`, insert:

```markdown
**core/lineage/** -- Per-raw-object lineage layer (Phase 1, additive)
- `core/lineage/schemas.py` -- Pydantic: SourceDefinition, RawObject, LineageEvent + naming grammar (`<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>` strict 4 parts)
- `core/lineage/source_resolver.py` -- Loads `core/source_registry.yaml` (SSOT policy per source), validates invariant `loop_targets == [] ⇔ promotion_policy == RAW_ONLY` at boot
- `core/lineage/state_machine.py` -- Pure transitions (RAW_ONLY → CLASSIFIED → PROMOTABLE → PROMOTED, REJECTED side-state)
- `core/lineage/policy_gate.py` -- Hard gate: no loop target ⇒ no canonical promotion
- `core/lineage/raw_manifest.py` -- API: register_raw_object + emit_event (always via `bq_write_validated(append)` — I1 strict)

Tabelle: `f_raw_objects` (identity, write-once), `f_lineage_events` (state log, append-only), view `v_raw_objects_current`.
Spec: `docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md`.
```

Also add to the CLI commands list (Commands section):

```markdown
hotelops intake <file> --source-name X      # Register a file (RAW_INGESTED event)
hotelops promote --raw-object-id Y          # Promote PROMOTABLE → PROMOTED
hotelops lineage Y                          # Inspect raw_object identity + event history
```

- [ ] **Step 10.2: Add §10 link in DATA_ENGINEERING_RULES.md**

Open `docs/architecture/DATA_ENGINEERING_RULES.md`, find §10 "Related". Add a bullet:

```markdown
- `docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md` — lineage layer Phase 1 design (raw object lifecycle, source_registry, hard gate)
```

- [ ] **Step 10.3: Banner SUPERSEDED on prior spec**

Open `docs/superpowers/specs/2026-04-02-manifest-shadow-os-design.md`. Insert at the very top (above any frontmatter, OR right after the existing frontmatter `---`):

```markdown
> **⚠️ SUPERSEDED by `2026-05-05-ingest-lineage-gcs-design.md`** (2026-05-05) — il modello dati è stato semplificato (append-only via gate, view per latest state), il name "manifest" è disambiguato (catalog vs lineage), e lo scope è ora chiaramente Phase-driven.
```

- [ ] **Step 10.4: Add "in corso" entry to STATUS.md**

Open `STATUS.md`, in the "## In corso" section, prepend:

```markdown
- **Ingest lineage Phase 1** (`refactor/ingest-lineage-gcs`): spec + plan committati. 10 task TDD additive-only — moduli `core/lineage/`, tabelle `f_raw_objects` + `f_lineage_events` + view `v_raw_objects_current`, CLI `hotelops intake/promote/lineage`. Zero modifica a parser esistenti, zero shadow su `cmd_drop`. Phase 1 = foundation; Phase 2 = shadow opt-in; Phase 3 = cutover.
```

- [ ] **Step 10.5: Run tests one more time**

```bash
pytest -q
```

Expected: green.

- [ ] **Step 10.6: Materialize tables on BQ produzione (real, not dry-run)**

```bash
python -m core.bq.load.load_lineage_tables
bq query --use_legacy_sql=false 'SELECT table_id, row_count FROM `hotelops-suite.hotelops.__TABLES__` WHERE table_id LIKE "f_raw_objects" OR table_id LIKE "f_lineage_events"'
```

Expected: both tables exist with row_count=0.

- [ ] **Step 10.7: End-to-end smoke test on a real file**

Pick a small fixture (e.g. an existing partite_fornitori xlsx) and run:

```bash
# Intake the file (manual source binding)
hotelops intake /path/to/INTUR_PARTITE_FORNITORI_20260415.xlsx \
  --source-name ESOLVER_PARTITE_INTUR_SNAPSHOT
# Note the printed raw_object_id, then:
hotelops lineage <that-id>
```

Expected output of `lineage`:
- Identity row populated with file_name + source_name
- Current status: `RAW_ONLY` (intake-only, no promote)
- 1 event: `RAW_INGESTED  ∅ → RAW_ONLY`

(Skip canonical promotion in this smoke test — that would touch production `f_partite_aperte_fornitori`. Validate promotion path with a fixture file in Phase 1 demo session, not in CI.)

- [ ] **Step 10.8: Commit**

```bash
git add CLAUDE.md docs/architecture/DATA_ENGINEERING_RULES.md docs/superpowers/specs/2026-04-02-manifest-shadow-os-design.md STATUS.md
git commit -m "docs(lineage): CLAUDE.md + RULES + SUPERSEDED banner + STATUS update (task 10)"
```

---

## Final verification — Phase 1 Definition of Done

- [ ] `pytest` green: existing 33 test files unchanged + 7 new files (~30 test cases)
- [ ] `core/source_registry.yaml` boot-validated: `loop_targets == [] ⇔ RAW_ONLY` enforced; invalid `source_name` format rejected
- [ ] `f_raw_objects`, `f_lineage_events`, `v_raw_objects_current` materialized on BQ produzione
- [ ] `hotelops intake <file> --source-name X` works end-to-end (writes raw_object + emits RAW_INGESTED)
- [ ] `hotelops promote --raw-object-id X` on a RAW_ONLY source (e.g. `POWERBI_CRUSCOTTO_ORTI_APPEND`) → REJECTED + `reason=NO_LOOP_TARGET`, no canonical write
- [ ] `hotelops lineage X` shows identity + event history + current status
- [ ] `hotelops drop`, `hotelops classifica`, `hotelops ingest` produce **identical** output as before this branch (regression check via diffing JSONL audit log on a fixed fixture)
- [ ] CLAUDE.md, DATA_ENGINEERING_RULES.md updated; prior spec carries SUPERSEDED banner; STATUS.md tracks Phase 1 in-corso
- [ ] All 10 task commits pushed; branch ready for PR / merge to main

---

## Execution choice

Plan completo e salvato. Due opzioni di esecuzione:

**1. Subagent-Driven (raccomandato)** — dispatch un subagent fresh per ogni task, review tra un task e l'altro, iterazione veloce.

**2. Inline Execution** — esegui task in questa sessione via `executing-plans`, batch con checkpoint per review.

**Quale approccio?**
