# Freshness Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `hotelops health` legge `core/source_registry.yaml` e, per ogni sorgente, dice se è fresca e, se no, cosa esportare, da dove, da quale giorno, chi lo fa e quale comando lanciare.

**Architecture:** Due blocchi Pydantic opzionali (`freshness`, `acquisition`) dentro `SourceDefinition`; un motore puro in `core/freshness.py` (`status_for`, `action_for`) più un `compute()` che fa tre query BigQuery iniettate; `cmd_health` sostituisce i suoi quattro blocchi hardcoded con un loop sul registry e guadagna `--json`, `--source`, `--all`. I due fetcher automatici aprono un `PipelineRun` col proprio nome così "job verde" diventa leggibile.

**Tech Stack:** Python ≥3.11, Pydantic v2, PyYAML, google-cloud-bigquery (solo in `compute` via `query` iniettata), pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-freshness-contract-design.md`

## Global Constraints

- Nessun YAML nuovo: il contratto vive solo in `core/source_registry.yaml` (spec §3).
- `cadence` ∈ {daily, weekly, monthly, quarterly, adhoc}; `monthly` = mese di calendario, `grace_day` default 10, famiglie Esolver 20 (spec §4).
- Stati esatti: `OK, DUE, STALE, DORMANT, JOB_DOWN, DATA_STUCK, NO_CONTRACT`; icone `✓ ! 🔴 ⏸ 🔴 🔴 ?` (spec §4).
- Job stale = nessun run `OK` in `f_pipeline_runs` nelle ultime 36 ore (riusa `PIPELINE_STALENESS_HOURS`).
- Tre query BigQuery in tutto in `compute()`; `query` è iniettata con la firma `Callable[[str], list[dict]]` di `cli.query` (spec §6).
- Exit code di `hotelops health` resta 0. Nessun nudge, nessuna pagina hub in questa slice (spec §11).
- Ogni write BQ passa da `core/bq/write.py` (I1): questa slice non scrive su BQ, solo legge.
- Deviazione dichiarata dalla spec §3: la regola "source promuovibile ⇒ contratto presente" è un **test di configurazione** (`tests/test_registry_freshness_contracts.py`), non un validator al load, perché decine di test esistenti costruiscono `SourceDefinition` senza i blocchi.
- Branch di lavoro: `feat/freshness-contract` da `main`. Commit atomici per task, mai `git add .`.
- Suite di riferimento: `pytest -q` verde prima e dopo ogni task; `ruff check .` pulito.

---

## File Structure

| File | Ruolo |
|---|---|
| `core/lineage/schemas.py` (modify) | `FreshnessContract`, `AcquisitionContract`, due campi nuovi su `SourceDefinition` |
| `core/freshness.py` (create) | motore: date attese, stato, frase azione, `compute`, `render_text`, `to_json` |
| `core/source_registry.yaml` (modify) | i due blocchi per tutte le 48 source |
| `verticals/condges/cli_commands.py` (modify) | `cmd_health`: blocco SORGENTI al posto di BANCHE/MOVIMENTI/IMPEGNO/SCHEDA |
| `cli.py` (modify) | flag `--json`, `--source`, `--all` sul parser `health` |
| `core/pipeline_run.py` (modify) | rimozione di `check_impegno_freshness` e `IMPEGNO_STALENESS_DAYS`, orfani del task 5 |
| `ingest/drive_fetch.py`, `ingest/pec_fetch.py` (modify) | `PipelineRun` col nome del job |
| `tests/test_freshness_contract_schema.py` (create) | validazione dei blocchi |
| `tests/test_freshness_status.py` (create) | funzioni pure |
| `tests/test_freshness_compute.py` (create) | `compute`/`render_text`/`to_json` con query finta |
| `tests/test_registry_freshness_contracts.py` (create) | test di configurazione sul registry reale |
| `tests/test_health_sorgenti_cli.py` (create) | `cmd_health --json` con motore finto |
| `tests/test_health_checks.py` (modify) | rimozione dei test di `check_impegno_freshness` |
| `tests/test_drive_fetch.py`, `tests/test_pec_fetch.py` (modify) | il job apre un `PipelineRun` |
| `STATUS.md`, `CLAUDE.md` (modify) | diario + cheat-sheet |

---

### Task 0: Branch

**Files:** nessuno.

- [ ] **Step 1: Branch da main pulito**

```bash
cd ~/dev/Projects/hotelops
git status --short   # STATUS.md e altri file sono già sporchi: NON toccarli, non stagiarli
git checkout -b feat/freshness-contract
pytest -q 2>&1 | tail -3   # baseline verde
```

Expected: `pytest` termina con `passed`, nessun `failed`.

---

### Task 1: Contratti Pydantic

**Files:**
- Modify: `core/lineage/schemas.py:115-181` (dopo `RawStorage`/`ImapMailbox`, dentro `SourceDefinition`)
- Test: `tests/test_freshness_contract_schema.py`

**Interfaces:**
- Produces: `FreshnessContract(tier, cadence, grace_day=10, grain, basis="canonical", coverage_column=None, dims=[], dim_filter={}, dormant=None)`; `AcquisitionContract(mode, owner, location, report, filters=None, format=None, job=None)`; `SourceDefinition.freshness: Optional[FreshnessContract]`, `SourceDefinition.acquisition: Optional[AcquisitionContract]`.

- [ ] **Step 1: Scrivi i test che falliscono**

```python
# tests/test_freshness_contract_schema.py
"""Contratto freshness/acquisition dentro SourceDefinition (spec 2026-09-09 §3)."""

import pytest
from pydantic import ValidationError

from core.lineage.schemas import (
    AcquisitionContract,
    FreshnessContract,
    SourceDefinition,
)


def _base(**over) -> dict:
    d = dict(
        source_name="MPS_BANCA_ORTI_APPEND",
        system="MPS",
        dataset="BANCA",
        societa="ORTI",
        lifecycle="APPEND",
        canonical_table="f_banche_movimenti",
        parser_module="ingest.banca.ingest",
        loop_targets=["cash_control"],
        promotion_policy="AUTO",
        detector_category="banca",
        raw_storage={"backend": "gcs", "bucket": "hotelops-raw"},
    )
    d.update(over)
    return d


def test_source_definition_senza_contratto_carica_ancora():
    sd = SourceDefinition(**_base())
    assert sd.freshness is None and sd.acquisition is None


def test_freshness_canonical_richiede_coverage_column():
    with pytest.raises(ValidationError, match="coverage_column"):
        FreshnessContract(tier="E", cadence="monthly", grain="daily")


def test_freshness_raw_non_ammette_coverage_column_ne_dims():
    with pytest.raises(ValidationError, match="raw"):
        FreshnessContract(tier="E", cadence="monthly", grain="daily", basis="raw",
                          coverage_column="data")
    with pytest.raises(ValidationError, match="raw"):
        FreshnessContract(tier="E", cadence="monthly", grain="daily", basis="raw",
                          dims=["banca_id"])


def test_grace_day_fuori_range_rifiutato():
    with pytest.raises(ValidationError, match="grace_day"):
        FreshnessContract(tier="E", cadence="monthly", grain="daily",
                          coverage_column="data", grace_day=31)


def test_acquisition_auto_richiede_job_e_owner_job():
    with pytest.raises(ValidationError, match="job"):
        AcquisitionContract(mode="AUTO", owner="job", location="Drive", report="x")
    with pytest.raises(ValidationError, match="owner"):
        AcquisitionContract(mode="AUTO", owner="Stefano", location="Drive", report="x",
                            job="drive_fetch:X")


def test_acquisition_semi_non_ammette_job():
    with pytest.raises(ValidationError, match="job"):
        AcquisitionContract(mode="SEMI", owner="Stefano", location="Esolver", report="x",
                            job="ingest_x")


def test_raw_only_con_freshness_deve_essere_basis_raw():
    with pytest.raises(ValidationError, match="RAW_ONLY"):
        SourceDefinition(**_base(
            promotion_policy="RAW_ONLY", loop_targets=[],
            freshness={"tier": "M", "cadence": "adhoc", "grain": "snapshot",
                       "coverage_column": "data"},
        ))


def test_contratto_completo_round_trip():
    sd = SourceDefinition(**_base(
        freshness={"tier": "E", "cadence": "monthly", "grain": "daily",
                   "coverage_column": "data_operazione", "dims": ["banca_id"],
                   "dim_filter": {"banca_id": ["MPS", "MPS_KROSS"]}},
        acquisition={"mode": "SEMI", "owner": "Stefano", "location": "Homebanking MPS",
                     "report": "Lista movimenti", "filters": "mese pieno", "format": "xls"},
    ))
    assert sd.freshness.grace_day == 10
    assert sd.freshness.dim_filter["banca_id"] == ["MPS", "MPS_KROSS"]
    assert sd.acquisition.job is None
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_freshness_contract_schema.py -q`
Expected: FAIL con `ImportError: cannot import name 'FreshnessContract'`.

- [ ] **Step 3: Implementa i modelli**

In `core/lineage/schemas.py`, subito dopo la classe `ImapMailbox` e prima di `SourceDefinition`:

```python
class FreshnessContract(BaseModel):
    """Come si misura la freschezza di una sorgente (spec 2026-09-09 §3-4).

    `basis: canonical` legge MAX(coverage_column) dalla canonical_table, per
    combinazione di `dims` (societa_id è sempre implicito). `basis: raw` legge
    l'ultimo intake in f_raw_objects: serve alle sorgenti che condividono la
    tabella senza una colonna che le distingua, e alle RAW_ONLY.
    """

    tier: Literal["R", "E", "M"]
    cadence: Literal["daily", "weekly", "monthly", "quarterly", "adhoc"]
    grace_day: int = 10
    grain: Literal["daily", "monthly", "snapshot"]
    basis: Literal["canonical", "raw"] = "canonical"
    coverage_column: Optional[str] = None
    dims: list[str] = Field(default_factory=list)
    dim_filter: dict[str, list[str]] = Field(default_factory=dict)
    dormant: Optional[str] = None

    @model_validator(mode="after")
    def _coerenza(self):
        if not 1 <= self.grace_day <= 28:
            raise ValueError("grace_day deve stare tra 1 e 28")
        if self.basis == "canonical" and not self.coverage_column:
            raise ValueError("basis canonical richiede coverage_column")
        if self.basis == "raw" and (self.coverage_column or self.dims or self.dim_filter):
            raise ValueError("basis raw non ammette coverage_column, dims o dim_filter")
        for dim in self.dim_filter:
            if dim not in self.dims:
                raise ValueError(f"dim_filter su {dim!r} che non è in dims")
        return self


class AcquisitionContract(BaseModel):
    """Chi esporta cosa, da dove (spec 2026-09-09 §3, §5)."""

    mode: Literal["AUTO", "SEMI", "MANUAL"]
    owner: Literal["Stefano", "Rosa", "Antonio", "job"]
    location: str
    report: str
    filters: Optional[str] = None
    format: Optional[str] = None
    job: Optional[str] = None

    @model_validator(mode="after")
    def _coerenza(self):
        if self.mode == "AUTO":
            if not self.job:
                raise ValueError("mode AUTO richiede job (pipeline_name in f_pipeline_runs)")
            if self.owner != "job":
                raise ValueError("mode AUTO richiede owner 'job'")
        elif self.job:
            raise ValueError("job è ammesso solo con mode AUTO")
        return self
```

Poi in `SourceDefinition`, dopo `notes: Optional[str] = None`:

```python
    freshness: Optional[FreshnessContract] = None
    acquisition: Optional[AcquisitionContract] = None
```

e un secondo validator dopo `_pec_richiede_identita_casella`:

```python
    @model_validator(mode="after")
    def _raw_only_usa_basis_raw(self):
        if (
            self.promotion_policy == "RAW_ONLY"
            and self.freshness is not None
            and self.freshness.basis != "raw"
        ):
            raise ValueError(
                f"{self.source_name}: sorgente RAW_ONLY con freshness deve avere basis raw"
            )
        return self
```

- [ ] **Step 4: Verifica che passino**

Run: `pytest tests/test_freshness_contract_schema.py tests/test_lineage_schemas.py tests/test_source_resolver.py -q`
Expected: tutti PASS (i test esistenti non usano i campi nuovi e restano verdi).

- [ ] **Step 5: Commit**

```bash
git add core/lineage/schemas.py tests/test_freshness_contract_schema.py
git commit -m "feat(lineage): contratti freshness/acquisition opzionali in SourceDefinition"
```

---

### Task 2: Motore puro — date attese, stato, frase azione

**Files:**
- Create: `core/freshness.py`
- Test: `tests/test_freshness_status.py`

**Interfaces:**
- Consumes: `FreshnessContract`, `AcquisitionContract`, `SourceDefinition` (Task 1).
- Produces:
  - `expected_through(cadence: str, today: date) -> date | None`
  - `coverage_status(fc: FreshnessContract, covered: date | None, today: date) -> Literal["OK","DUE","STALE"]`
  - `status_for(fc, ac, covered, today, job_ok: bool | None) -> Status`
  - `action_for(sd: SourceDefinition, status: Status, covered: date | None) -> str | None`
  - costanti `SEVERITY: dict[Status,int]`, `ICON: dict[Status,str]`, `JOB_STALE_HOURS = 36`

- [ ] **Step 1: Scrivi i test che falliscono**

```python
# tests/test_freshness_status.py
"""Funzioni pure del freshness contract (spec 2026-09-09 §4-5)."""

from datetime import date

import pytest

from core.freshness import action_for, coverage_status, expected_through, status_for
from core.lineage.schemas import AcquisitionContract, FreshnessContract, SourceDefinition


def fc(**over) -> FreshnessContract:
    d = dict(tier="E", cadence="monthly", grain="daily", coverage_column="data")
    d.update(over)
    return FreshnessContract(**d)


def ac(**over) -> AcquisitionContract:
    d = dict(mode="SEMI", owner="Stefano", location="Homebanking MPS",
             report="Lista movimenti", filters="mese pieno")
    d.update(over)
    return AcquisitionContract(**d)


def sd(**over) -> SourceDefinition:
    d = dict(
        source_name="MPS_BANCA_ORTI_APPEND", system="MPS", dataset="BANCA", societa="ORTI",
        lifecycle="APPEND", canonical_table="f_banche_movimenti",
        parser_module="ingest.banca.ingest", loop_targets=["cash_control"],
        promotion_policy="AUTO", detector_category="banca",
        raw_storage={"backend": "gcs", "bucket": "hotelops-raw"},
        freshness=fc(), acquisition=ac(),
    )
    d.update(over)
    return SourceDefinition(**d)


# ── expected_through ────────────────────────────────────────────────────────

@pytest.mark.parametrize("cadence,today,atteso", [
    ("daily", date(2026, 9, 9), date(2026, 9, 7)),
    ("weekly", date(2026, 9, 9), date(2026, 8, 30)),
    ("monthly", date(2026, 9, 9), date(2026, 8, 31)),
    ("monthly", date(2026, 1, 3), date(2025, 12, 31)),
    ("quarterly", date(2026, 9, 9), date(2026, 6, 30)),
    ("quarterly", date(2026, 1, 15), date(2025, 12, 31)),
    ("adhoc", date(2026, 9, 9), None),
])
def test_expected_through(cadence, today, atteso):
    assert expected_through(cadence, today) == atteso


# ── coverage_status: mensile di calendario con grazia ───────────────────────

def test_mensile_coperto_ok():
    assert coverage_status(fc(), date(2026, 8, 31), date(2026, 9, 9)) == "OK"


def test_mensile_in_grazia_e_due():
    # 9/9, grazia 10, coperto fino al 20/8 (≥ 31/7): in scadenza
    assert coverage_status(fc(), date(2026, 8, 20), date(2026, 9, 9)) == "DUE"


def test_mensile_giorno_di_grazia_incluso():
    assert coverage_status(fc(grace_day=10), date(2026, 8, 20), date(2026, 9, 10)) == "DUE"


def test_mensile_oltre_grazia_e_stale():
    assert coverage_status(fc(grace_day=10), date(2026, 8, 20), date(2026, 9, 11)) == "STALE"


def test_mensile_grazia_20_esolver():
    assert coverage_status(fc(grace_day=20), date(2026, 8, 14), date(2026, 9, 19)) == "DUE"
    assert coverage_status(fc(grace_day=20), date(2026, 8, 14), date(2026, 9, 21)) == "STALE"


def test_mensile_in_grazia_ma_manca_anche_il_mese_prima_e_stale():
    # 9/9, coperto solo fino al 30/6: manca luglio intero → rosso anche in grazia
    assert coverage_status(fc(), date(2026, 6, 30), date(2026, 9, 9)) == "STALE"


def test_mensile_senza_dati_e_stale():
    assert coverage_status(fc(), None, date(2026, 9, 9)) == "STALE"


def test_daily_weekly_eta_semplice():
    assert coverage_status(fc(cadence="daily"), date(2026, 9, 7), date(2026, 9, 9)) == "OK"
    assert coverage_status(fc(cadence="daily"), date(2026, 9, 6), date(2026, 9, 9)) == "STALE"
    assert coverage_status(fc(cadence="weekly"), date(2026, 8, 30), date(2026, 9, 9)) == "OK"
    assert coverage_status(fc(cadence="weekly"), date(2026, 8, 29), date(2026, 9, 9)) == "STALE"


def test_quarterly_grazia_30_giorni():
    q = fc(cadence="quarterly", basis="raw", coverage_column=None)
    assert coverage_status(q, date(2026, 6, 30), date(2026, 7, 20)) == "OK"
    assert coverage_status(q, date(2026, 3, 31), date(2026, 7, 20)) == "DUE"
    assert coverage_status(q, date(2026, 3, 31), date(2026, 8, 5)) == "STALE"


def test_adhoc_mai_colorato():
    assert coverage_status(fc(cadence="adhoc"), None, date(2026, 9, 9)) == "OK"


# ── status_for ──────────────────────────────────────────────────────────────

def test_no_contract():
    assert status_for(None, None, None, date(2026, 9, 9), None) == "NO_CONTRACT"
    assert status_for(fc(), None, None, date(2026, 9, 9), None) == "NO_CONTRACT"


def test_dormant_vince_su_tutto():
    assert status_for(fc(dormant="conto senza flussi"), ac(), None, date(2026, 9, 9), None) == "DORMANT"


def test_auto_job_down():
    a = ac(mode="AUTO", owner="job", job="ingest_coperti")
    assert status_for(fc(cadence="daily"), a, date(2026, 9, 8), date(2026, 9, 9), False) == "JOB_DOWN"
    assert status_for(fc(cadence="daily"), a, date(2026, 9, 8), date(2026, 9, 9), None) == "JOB_DOWN"


def test_auto_job_verde_dati_fermi():
    a = ac(mode="AUTO", owner="job", job="ingest_coperti")
    assert status_for(fc(cadence="daily"), a, date(2026, 8, 1), date(2026, 9, 9), True) == "DATA_STUCK"


def test_auto_tutto_verde():
    a = ac(mode="AUTO", owner="job", job="ingest_coperti")
    assert status_for(fc(cadence="daily"), a, date(2026, 9, 8), date(2026, 9, 9), True) == "OK"


def test_semi_ignora_job_ok():
    assert status_for(fc(), ac(), date(2026, 8, 31), date(2026, 9, 9), False) == "OK"


# ── action_for ──────────────────────────────────────────────────────────────

def test_nessuna_azione_se_ok_dormant_no_contract():
    for st in ("OK", "DORMANT", "NO_CONTRACT"):
        assert action_for(sd(), st, date(2026, 8, 31)) is None


def test_azione_semi_append_con_dal_e_capture():
    txt = action_for(sd(), "DUE", date(2026, 8, 20))
    assert txt.startswith("→ Homebanking MPS › Lista movimenti › mese pieno › dal 21/08 (sovrapporre")
    assert txt.endswith("› Stefano\n  poi: hotelops capture <file>")


def test_azione_manual_snapshot_intake_promote():
    s = sd(source_name="POWERBI_PRODUZIONE_ORTI_SNAPSHOT", lifecycle="SNAPSHOT",
           acquisition=ac(mode="MANUAL", location="Power BI PanoramaGroup",
                          report="Daily Production Report", filters=None))
    txt = action_for(s, "STALE", date(2026, 8, 15))
    assert "dal 16/08 (fotografia a oggi, sostituisce la precedente)" in txt
    assert txt.endswith(
        "poi: hotelops intake <file> --source-name POWERBI_PRODUZIONE_ORTI_SNAPSHOT"
        " && hotelops promote --raw-object-id <id>"
    )


def test_azione_basis_raw_senza_dal():
    s = sd(freshness=fc(basis="raw", coverage_column=None))
    txt = action_for(s, "STALE", date(2026, 7, 5))
    assert "dal " not in txt


def test_azione_auto():
    s = sd(acquisition=ac(mode="AUTO", owner="job", job="ingest_coperti",
                          location="Google Sheet Scarico Coperti", report="form"))
    assert action_for(s, "JOB_DOWN", None) == "→ controlla il job ingest_coperti"
    assert action_for(s, "DATA_STUCK", None) == (
        "→ job ingest_coperti verde, dati fermi: controlla la fonte Google Sheet Scarico Coperti"
    )
    assert action_for(s, "OK", None) is None
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_freshness_status.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'core.freshness'`.

- [ ] **Step 3: Implementa `core/freshness.py` (parte pura)**

```python
# core/freshness.py
"""Freshness contract: da `core/source_registry.yaml` a "cosa esportare, da dove, da quando".

Spec: docs/superpowers/specs/2026-09-09-freshness-contract-design.md.

Tre livelli, dal basso:
- funzioni pure (`expected_through`, `coverage_status`, `status_for`, `action_for`);
- `compute(registry, query, now)`: tre query BigQuery iniettate, una lista di SourceFreshness;
- `render_text` / `to_json`: le due superfici (CLI oggi, hub e nudge domani).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Literal, Optional
from zoneinfo import ZoneInfo

from core.lineage.schemas import AcquisitionContract, FreshnessContract, SourceDefinition

Status = Literal["OK", "DUE", "STALE", "DORMANT", "JOB_DOWN", "DATA_STUCK", "NO_CONTRACT"]

SEVERITY: dict[str, int] = {
    "STALE": 0, "JOB_DOWN": 0, "DATA_STUCK": 0,
    "DUE": 1, "OK": 2, "DORMANT": 3, "NO_CONTRACT": 4,
}
ICON: dict[str, str] = {
    "OK": "✓", "DUE": "!", "STALE": "🔴", "JOB_DOWN": "🔴", "DATA_STUCK": "🔴",
    "DORMANT": "⏸", "NO_CONTRACT": "?",
}
JOB_STALE_HOURS = 36
ROME = ZoneInfo("Europe/Rome")


# ── Date attese ─────────────────────────────────────────────────────────────


def _month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _prev_month_end(d: date) -> date:
    return date(d.year, d.month, 1) - timedelta(days=1)


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def expected_through(cadence: str, today: date) -> Optional[date]:
    """Ultimo giorno che una sorgente con questa cadenza deve coprire oggi."""
    if cadence == "daily":
        return today - timedelta(days=2)
    if cadence == "weekly":
        return today - timedelta(days=10)
    if cadence == "monthly":
        return _prev_month_end(today)
    if cadence == "quarterly":
        return _quarter_start(today) - timedelta(days=1)
    return None  # adhoc


def coverage_status(fc: FreshnessContract, covered: Optional[date], today: date) -> str:
    """OK / DUE / STALE dal solo confronto copertura vs atteso (spec §4)."""
    if fc.cadence == "adhoc":
        return "OK"
    atteso = expected_through(fc.cadence, today)
    if covered is None:
        return "STALE"
    if covered >= atteso:
        return "OK"
    if fc.cadence == "monthly":
        in_grazia = today.day <= fc.grace_day
        if in_grazia and covered >= _prev_month_end(atteso):
            return "DUE"
        return "STALE"
    if fc.cadence == "quarterly":
        in_grazia = (today - _quarter_start(today)).days < 30
        if in_grazia and covered >= _quarter_start(atteso) - timedelta(days=1):
            return "DUE"
        return "STALE"
    return "STALE"  # daily / weekly: età semplice, niente grazia


def status_for(
    fc: Optional[FreshnessContract],
    ac: Optional[AcquisitionContract],
    covered: Optional[date],
    today: date,
    job_ok: Optional[bool],
) -> str:
    if fc is None or ac is None:
        return "NO_CONTRACT"
    if fc.dormant:
        return "DORMANT"
    cov = coverage_status(fc, covered, today)
    if ac.mode == "AUTO":
        if not job_ok:
            return "JOB_DOWN"
        if cov == "STALE":
            return "DATA_STUCK"
    return cov


# ── Frase azione ────────────────────────────────────────────────────────────


def action_for(sd: SourceDefinition, status: str, covered: Optional[date]) -> Optional[str]:
    if status in ("OK", "DORMANT", "NO_CONTRACT"):
        return None
    fc, ac = sd.freshness, sd.acquisition
    if ac.mode == "AUTO":
        if status == "JOB_DOWN":
            return f"→ controlla il job {ac.job}"
        if status == "DATA_STUCK":
            return f"→ job {ac.job} verde, dati fermi: controlla la fonte {ac.location}"
        return None
    parts = [ac.location, ac.report]
    if ac.filters:
        parts.append(ac.filters)
    if fc.basis == "canonical" and covered is not None:
        nota = (
            "sovrapporre qualche giorno è innocuo, dedup su hash"
            if sd.lifecycle == "APPEND"
            else "fotografia a oggi, sostituisce la precedente"
        )
        parts.append(f"dal {covered + timedelta(days=1):%d/%m} ({nota})")
    elif sd.lifecycle == "SNAPSHOT":
        parts.append("fotografia a oggi")
    parts.append(ac.owner)
    if ac.mode == "SEMI":
        cmd = "hotelops capture <file>"
    else:
        cmd = (
            f"hotelops intake <file> --source-name {sd.source_name}"
            " && hotelops promote --raw-object-id <id>"
        )
    return "→ " + " › ".join(parts) + f"\n  poi: {cmd}"
```

(`dataclass`, `field`, `datetime`, `timezone`, `Callable`, `ROME` servono al Task 3: lasciarli importati, `ruff` li segnalerebbe come inutilizzati solo se il Task 3 non li usa.)

- [ ] **Step 4: Verifica che passino**

Run: `pytest tests/test_freshness_status.py -q && ruff check core/freshness.py`
Expected: PASS; se ruff segnala import inutilizzati, aggiungere `# noqa: F401` temporaneo sulla riga degli import che il Task 3 userà, e rimuoverlo nel Task 3.

- [ ] **Step 5: Commit**

```bash
git add core/freshness.py tests/test_freshness_status.py
git commit -m "feat(freshness): motore puro — date attese, stato, frase azione"
```

---

### Task 3: `compute`, `render_text`, `to_json`

**Files:**
- Modify: `core/freshness.py` (append)
- Test: `tests/test_freshness_compute.py`

**Interfaces:**
- Consumes: Task 2.
- Produces:
  - `@dataclass SourceFreshness(source_name, tier, mode, owner, status, covered_through, expected_through, age_days, last_raw_at, per_dim, blocks, action, raw_only, job, dormant)`
  - `compute(registry, query: Callable[[str], list[dict]], now: datetime | None = None) -> list[SourceFreshness]` ordinata per severità poi per numero di loop bloccati (decrescente) poi per nome.
  - `render_text(items, today: date, show_all: bool = False) -> str`
  - `to_json(items) -> list[dict]`

- [ ] **Step 1: Scrivi i test che falliscono**

```python
# tests/test_freshness_compute.py
"""compute/render_text/to_json con query finta (spec 2026-09-09 §6-7)."""

from datetime import date, datetime, timedelta, timezone

from core.freshness import compute, render_text, to_json
from core.lineage.schemas import SourceDefinition
from core.lineage.source_resolver import SourceRegistry

NOW = datetime(2026, 9, 9, 10, 0, tzinfo=timezone.utc)


def _sd(name, **over):
    d = dict(
        source_name=name, system=name.split("_")[0], dataset="X", societa="ORTI",
        lifecycle="APPEND", canonical_table="f_banche_movimenti",
        parser_module="ingest.banca.ingest", loop_targets=["cash_control"],
        promotion_policy="AUTO", detector_category="banca",
        raw_storage={"backend": "gcs", "bucket": "hotelops-raw"},
        freshness={"tier": "E", "cadence": "monthly", "grain": "daily",
                   "coverage_column": "data_operazione", "dims": ["banca_id"],
                   "dim_filter": {"banca_id": ["MPS", "MPS_KROSS"]}},
        acquisition={"mode": "SEMI", "owner": "Stefano", "location": "Homebanking MPS",
                     "report": "Lista movimenti", "filters": "mese pieno"},
    )
    d.update(over)
    return SourceDefinition(**d)


def _registry(*sds) -> SourceRegistry:
    return SourceRegistry({s.source_name: s for s in sds})


class FakeQuery:
    """Risponde per tabella: la SQL è ispezionata solo per capire quale query è."""

    def __init__(self, coverage=None, raw=None, jobs=None):
        self.coverage = coverage or {}   # canonical_table -> rows
        self.raw = raw or []
        self.jobs = jobs or []
        self.calls: list[str] = []

    def __call__(self, sql: str) -> list[dict]:
        self.calls.append(sql)
        if "f_raw_objects" in sql:
            return self.raw
        if "f_pipeline_runs" in sql:
            return self.jobs
        for table, rows in self.coverage.items():
            if f"hotelops.{table}" in sql:
                return rows
        return []


def test_una_query_per_gruppo_tabella_e_tre_in_tutto_con_due_banche():
    mps = _sd("MPS_BANCA_ORTI_APPEND")
    sella = _sd("SELLA_BANCA_INTUR_APPEND", societa="INTUR",
                freshness={**mps.freshness.model_dump(), "dim_filter": {"banca_id": ["SELLA"]}})
    q = FakeQuery(coverage={"f_banche_movimenti": [
        {"societa_id": "ORTI", "banca_id": "MPS", "covered": date(2026, 8, 20)},
        {"societa_id": "ORTI", "banca_id": "MPS_KROSS", "covered": date(2026, 8, 18)},
        {"societa_id": "ORTI", "banca_id": "INTESA", "covered": date(2026, 6, 5)},
        {"societa_id": "INTUR", "banca_id": "SELLA", "covered": date(2026, 8, 31)},
    ]})
    items = compute(_registry(mps, sella), q, now=NOW)
    assert len(q.calls) == 3
    by = {i.source_name: i for i in items}
    assert by["MPS_BANCA_ORTI_APPEND"].covered_through == date(2026, 8, 18)   # la peggiore delle sue dims
    assert by["MPS_BANCA_ORTI_APPEND"].status == "DUE"
    assert by["MPS_BANCA_ORTI_APPEND"].per_dim == [
        ({"banca_id": "MPS"}, date(2026, 8, 20)),
        ({"banca_id": "MPS_KROSS"}, date(2026, 8, 18)),
    ]
    assert by["SELLA_BANCA_INTUR_APPEND"].status == "OK"
    # INTESA non appartiene a nessuna delle due: non compare
    assert all(d[0]["banca_id"] != "INTESA" for d in by["MPS_BANCA_ORTI_APPEND"].per_dim)


def test_basis_raw_usa_ultimo_intake():
    fatt = _sd("ESOLVER_FATTUREACQUISTO_ORTI_APPEND", canonical_table="f_fatture_righe",
               freshness={"tier": "E", "cadence": "monthly", "grace_day": 20, "grain": "daily",
                          "basis": "raw"},
               acquisition={"mode": "MANUAL", "owner": "Stefano", "location": "Esolver",
                            "report": "Lista fatture acquisto"})
    q = FakeQuery(raw=[{"source_name": "ESOLVER_FATTUREACQUISTO_ORTI_APPEND",
                        "last_intake": date(2026, 7, 5)}])
    [it] = compute(_registry(fatt), q, now=NOW)
    assert it.covered_through == date(2026, 7, 5)
    assert it.status == "STALE"
    assert "dal " not in it.action
    assert len([c for c in q.calls if "MAX(" in c and "f_fatture_righe" in c]) == 0


def test_auto_job_ok_entro_36h_e_data_stuck():
    cop = _sd("ORTI_COPERTI_ORTI_APPEND", canonical_table="f_coperti_giornalieri",
              freshness={"tier": "R", "cadence": "daily", "grain": "daily",
                         "coverage_column": "data_servizio"},
              acquisition={"mode": "AUTO", "owner": "job", "job": "ingest_coperti",
                           "location": "Google Sheet Scarico Coperti", "report": "form"})
    q = FakeQuery(
        coverage={"f_coperti_giornalieri": [{"societa_id": "ORTI", "covered": date(2026, 8, 1)}]},
        jobs=[{"pipeline_name": "ingest_coperti", "last_ok": NOW - timedelta(hours=2)}],
    )
    [it] = compute(_registry(cop), q, now=NOW)
    assert it.status == "DATA_STUCK"
    q.jobs = [{"pipeline_name": "ingest_coperti", "last_ok": NOW - timedelta(hours=40)}]
    [it] = compute(_registry(cop), q, now=NOW)
    assert it.status == "JOB_DOWN"


def test_societa_non_filtrabile_usa_solo_dim_filter():
    vigna = _sd("PEC_MAILBOX_VIGNA_APPEND", system="PEC", societa="VIGNA",
                canonical_table="f_pec_messages", detector_category="pec_mbox",
                casella="vineyardamalficoast@pec.it", entity_id="VIGNA",
                freshness={"tier": "R", "cadence": "adhoc", "grain": "daily", "basis": "raw"},
                acquisition={"mode": "AUTO", "owner": "job", "job": "pec_fetch",
                             "location": "PEC Aruba", "report": "IMAP"})
    q = FakeQuery(raw=[{"source_name": "PEC_MAILBOX_VIGNA_APPEND", "last_intake": date(2026, 8, 3)}],
                  jobs=[{"pipeline_name": "pec_fetch", "last_ok": NOW - timedelta(hours=8)}])
    [it] = compute(_registry(vigna), q, now=NOW)
    assert it.status == "OK"           # adhoc: la copertura non colora, il job sì
    assert it.covered_through == date(2026, 8, 3)


def test_senza_contratto_e_ordinamento():
    no = _sd("HOTELCUBE_ACCODAMENTI_ORTI_APPEND", freshness=None, acquisition=None,
             loop_targets=["daily_reconciliation", "cash_control"])
    dorm = _sd("INTESA_BANCA_ORTI_APPEND",
               freshness={"tier": "E", "cadence": "monthly", "grain": "daily",
                          "coverage_column": "data_operazione", "dims": ["banca_id"],
                          "dim_filter": {"banca_id": ["INTESA"]}, "dormant": "conto senza flussi"})
    stale = _sd("MPS_BANCA_ORTI_APPEND", loop_targets=["cash_control", "monthly_close"])
    q = FakeQuery(coverage={"f_banche_movimenti": [
        {"societa_id": "ORTI", "banca_id": "MPS", "covered": date(2026, 6, 30)}]})
    items = compute(_registry(no, dorm, stale), q, now=NOW)
    assert [i.source_name for i in items] == [
        "MPS_BANCA_ORTI_APPEND", "INTESA_BANCA_ORTI_APPEND", "HOTELCUBE_ACCODAMENTI_ORTI_APPEND"]
    assert items[1].status == "DORMANT" and items[2].status == "NO_CONTRACT"


def test_render_text_e_to_json():
    stale = _sd("MPS_BANCA_ORTI_APPEND", loop_targets=["cash_control", "monthly_close"])
    raw_only = _sd("HOTELCUBE_STAMPACASSA_ORTI_APPEND", promotion_policy="RAW_ONLY",
                   loop_targets=[], canonical_table="f_stampa_cassa",
                   freshness={"tier": "M", "cadence": "adhoc", "grain": "snapshot", "basis": "raw"},
                   acquisition={"mode": "MANUAL", "owner": "Stefano", "location": "HotelCube",
                                "report": "Stampa Cassa"})
    q = FakeQuery(coverage={"f_banche_movimenti": [
        {"societa_id": "ORTI", "banca_id": "MPS", "covered": date(2026, 6, 30)}]},
        raw=[{"source_name": "HOTELCUBE_STAMPACASSA_ORTI_APPEND", "last_intake": date(2026, 7, 12)}])
    items = compute(_registry(stale, raw_only), q, now=NOW)

    txt = render_text(items, today=NOW.date())
    assert "SORGENTI — 2026-09-09" in txt
    assert "🔴 MPS_BANCA_ORTI_APPEND" in txt
    assert "coperto 30/06 · atteso 31/08 · 71gg" in txt
    assert "→ Homebanking MPS › Lista movimenti › mese pieno › dal 01/07" in txt
    assert "blocca: cash_control, monthly_close" in txt
    assert "STAMPACASSA" not in txt                       # RAW_ONLY nascosta
    assert "STAMPACASSA" in render_text(items, today=NOW.date(), show_all=True)

    js = to_json(items)
    assert js[0]["source_name"] == "MPS_BANCA_ORTI_APPEND"
    assert js[0]["status"] == "STALE"
    assert js[0]["covered_through"] == "2026-06-30"
    assert js[0]["expected_through"] == "2026-08-31"
    assert js[0]["per_dim"] == [{"dims": {"banca_id": "MPS"}, "covered_through": "2026-06-30"}]
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_freshness_compute.py -q`
Expected: FAIL con `ImportError: cannot import name 'compute'`.

- [ ] **Step 3: Implementa compute/render/json (append a `core/freshness.py`)**

```python
# ── Risultato ───────────────────────────────────────────────────────────────


@dataclass
class SourceFreshness:
    source_name: str
    tier: Optional[str]
    mode: Optional[str]
    owner: Optional[str]
    status: str
    covered_through: Optional[date]
    expected_through: Optional[date]
    age_days: Optional[int]
    last_raw_at: Optional[date]
    per_dim: list[tuple[dict, Optional[date]]]
    blocks: list[str]
    action: Optional[str]
    raw_only: bool = False
    job: Optional[str] = None
    job_last_ok: Optional[datetime] = None
    dormant: Optional[str] = None
    grace_day: Optional[int] = None
    basis: Optional[str] = None


# ── compute ─────────────────────────────────────────────────────────────────

_SOCIETA_FILTRABILI = ("ORTI", "INTUR")


def _as_date(v) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def _as_dt(v) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(v)).replace(tzinfo=timezone.utc)


def _rows_for(sd: SourceDefinition, rows: list[dict]) -> list[dict]:
    fc = sd.freshness
    out = []
    for r in rows:
        if sd.societa in _SOCIETA_FILTRABILI and r.get("societa_id") != sd.societa:
            continue
        if any(r.get(dim) not in allowed for dim, allowed in fc.dim_filter.items()):
            continue
        out.append(r)
    return out


def _coverage_sql(table: str, expr: str, dims: tuple[str, ...]) -> str:
    cols = ["societa_id", *dims]
    group = ", ".join(str(i + 1) for i in range(len(cols)))
    return (
        f"SELECT {', '.join(cols)}, MAX({expr}) AS covered "
        f"FROM hotelops.{table} GROUP BY {group}"
    )


RAW_SQL = (
    "SELECT source_name, DATE(MAX(intake_at)) AS last_intake "
    "FROM hotelops.f_raw_objects GROUP BY 1"
)
JOBS_SQL = (
    "SELECT pipeline_name, MAX(ended_at) AS last_ok "
    "FROM hotelops.f_pipeline_runs WHERE status = 'OK' GROUP BY 1"
)


def compute(
    registry,
    query: Callable[[str], list[dict]],
    now: Optional[datetime] = None,
) -> list[SourceFreshness]:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(ROME).date()
    sources: list[SourceDefinition] = list(registry.sources.values())

    raw_last = {r["source_name"]: _as_date(r["last_intake"]) for r in query(RAW_SQL)}
    jobs_last = {r["pipeline_name"]: _as_dt(r["last_ok"]) for r in query(JOBS_SQL)}

    groups: dict[tuple[str, str, tuple[str, ...]], list[dict]] = {}
    for sd in sources:
        fc = sd.freshness
        if fc is None or fc.basis != "canonical":
            continue
        key = (sd.canonical_table, fc.coverage_column, tuple(fc.dims))
        if key not in groups:
            groups[key] = query(_coverage_sql(*key))

    items: list[SourceFreshness] = []
    for sd in sources:
        fc, ac = sd.freshness, sd.acquisition
        per_dim: list[tuple[dict, Optional[date]]] = []
        covered: Optional[date] = None
        if fc is not None and fc.basis == "canonical":
            key = (sd.canonical_table, fc.coverage_column, tuple(fc.dims))
            for r in _rows_for(sd, groups[key]):
                d = _as_date(r.get("covered"))
                per_dim.append(({k: r.get(k) for k in fc.dims}, d))
            dates = [d for _, d in per_dim if d is not None]
            covered = min(dates) if dates and len(dates) == len(per_dim) else None
            per_dim.sort(key=lambda t: tuple(str(v) for v in t[0].values()))
        elif fc is not None:
            covered = raw_last.get(sd.source_name)

        job_ok: Optional[bool] = None
        job_last = None
        if ac is not None and ac.mode == "AUTO":
            job_last = jobs_last.get(ac.job)
            job_ok = job_last is not None and (now - job_last) <= timedelta(hours=JOB_STALE_HOURS)

        status = status_for(fc, ac, covered, today, job_ok)
        atteso = expected_through(fc.cadence, today) if fc else None
        items.append(SourceFreshness(
            source_name=sd.source_name,
            tier=fc.tier if fc else None,
            mode=ac.mode if ac else None,
            owner=ac.owner if ac else None,
            status=status,
            covered_through=covered,
            expected_through=atteso,
            age_days=(today - covered).days if covered else None,
            last_raw_at=raw_last.get(sd.source_name),
            per_dim=per_dim,
            blocks=list(sd.loop_targets),
            action=action_for(sd, status, covered) if fc and ac else None,
            raw_only=sd.promotion_policy == "RAW_ONLY",
            job=ac.job if ac else None,
            job_last_ok=job_last,
            dormant=fc.dormant if fc else None,
            grace_day=fc.grace_day if fc else None,
            basis=fc.basis if fc else None,
        ))

    items.sort(key=lambda i: (SEVERITY[i.status], -len(i.blocks), i.source_name))
    return items


# ── Superfici ───────────────────────────────────────────────────────────────


def _fmt(d: Optional[date]) -> str:
    return f"{d:%d/%m}" if d else "mai"


def _summary(it: SourceFreshness, now_date: date) -> str:
    if it.status == "DORMANT":
        return f"dormiente: {it.dormant}"
    if it.status == "NO_CONTRACT":
        return "senza contratto"
    cop = f"ultimo raw {_fmt(it.covered_through)}" if it.basis == "raw" else f"coperto {_fmt(it.covered_through)}"
    if it.mode == "AUTO":
        if it.job_last_ok is None:
            job = f"job {it.job} mai OK"
        else:
            ore = int((datetime.now(timezone.utc) - it.job_last_ok).total_seconds() // 3600)
            job = f"job {it.job} OK {ore}h fa"
        return f"{cop} · {job}"
    if it.status == "OK":
        return cop
    if it.status == "DUE":
        return f"{cop} · atteso {_fmt(it.expected_through)} · in scadenza (grazia fino al {it.grace_day})"
    return f"{cop} · atteso {_fmt(it.expected_through)} · {it.age_days if it.age_days is not None else '?'}gg"


def render_text(items: list[SourceFreshness], today: date, show_all: bool = False) -> str:
    out = [f"  SORGENTI — {today:%Y-%m-%d} (mensile: mese precedente pieno entro il giorno di grazia)", ""]
    for it in items:
        if it.raw_only and not show_all:
            continue
        out.append(f"  {ICON[it.status]:<2} {it.source_name:<40} {_summary(it, today)}")
        if len(it.per_dim) > 1:
            out.append("       " + " · ".join(
                f"{'/'.join(str(v) for v in dims.values())} {_fmt(d)}" for dims, d in it.per_dim))
        if it.action:
            for line in it.action.splitlines():
                out.append("     " + line)
        if it.action and it.blocks:
            out.append(f"       blocca: {', '.join(it.blocks)}")
    return "\n".join(out)


def to_json(items: list[SourceFreshness]) -> list[dict]:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return [
        {
            "source_name": it.source_name,
            "tier": it.tier,
            "mode": it.mode,
            "owner": it.owner,
            "status": it.status,
            "covered_through": iso(it.covered_through),
            "expected_through": iso(it.expected_through),
            "age_days": it.age_days,
            "last_raw_at": iso(it.last_raw_at),
            "per_dim": [{"dims": dims, "covered_through": iso(d)} for dims, d in it.per_dim],
            "blocks": it.blocks,
            "action": it.action,
            "raw_only": it.raw_only,
            "job": it.job,
            "job_last_ok": iso(it.job_last_ok),
            "dormant": it.dormant,
        }
        for it in items
    ]
```

Nota su `covered`: se una dim non ha righe la copertura è `None` per costruzione solo quando nessuna riga esiste; con righe miste (una dim senza data) il `min` prende le date presenti. Il test "peggiore delle sue dims" copre il caso normale.

- [ ] **Step 4: Verifica che passino, più ruff**

Run: `pytest tests/test_freshness_compute.py tests/test_freshness_status.py -q && ruff check core/freshness.py && ruff format --check core/freshness.py`
Expected: PASS, ruff pulito (rimuovere l'eventuale `# noqa: F401` del Task 2).

- [ ] **Step 5: Commit**

```bash
git add core/freshness.py tests/test_freshness_compute.py
git commit -m "feat(freshness): compute su registry con tre query, render testo e json"
```

---

### Task 4: Popolare il registry e test di configurazione

**Files:**
- Modify: `core/source_registry.yaml` (ogni voce sotto `sources:`)
- Test: `tests/test_registry_freshness_contracts.py`

**Interfaces:**
- Consumes: Task 1. Il loader `load_registry()` non cambia.
- Produces: 48 voci con `freshness:` e `acquisition:`.

- [ ] **Step 1: Scrivi i test di configurazione che falliscono**

```python
# tests/test_registry_freshness_contracts.py
"""Il registry reale rispetta il freshness contract (spec 2026-09-09 §3, §9)."""

from collections import defaultdict

from core.lineage.source_resolver import load_registry


def _reg():
    return load_registry()


def test_ogni_sorgente_promuovibile_ha_il_contratto():
    mancanti = [
        sd.source_name for sd in _reg().sources.values()
        if sd.promotion_policy != "RAW_ONLY" and (sd.freshness is None or sd.acquisition is None)
    ]
    assert mancanti == [], f"senza freshness/acquisition: {mancanti}"


def test_le_raw_only_hanno_contratto_su_base_raw():
    for sd in _reg().sources.values():
        if sd.promotion_policy == "RAW_ONLY":
            assert sd.freshness is not None and sd.freshness.basis == "raw", sd.source_name
            assert sd.acquisition is not None and sd.acquisition.mode == "MANUAL", sd.source_name


def test_esolver_ha_grazia_20_tutti_gli_altri_mensili_10():
    for sd in _reg().sources.values():
        if sd.freshness is None or sd.freshness.cadence != "monthly":
            continue
        atteso = 20 if sd.system == "ESOLVER" else 10
        assert sd.freshness.grace_day == atteso, sd.source_name


def test_auto_solo_dove_esiste_un_job():
    attesi = {
        "ORTI_COPERTI_ORTI_APPEND": "ingest_coperti",
        "RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT": "drive_fetch:RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT",
        "PEC_MAILBOX_INTUR_APPEND": "pec_fetch",
        "PEC_MAILBOX_ORTI_APPEND": "pec_fetch",
        "PEC_MAILBOX_VIGNA_APPEND": "pec_fetch",
    }
    auto = {sd.source_name: sd.acquisition.job for sd in _reg().sources.values()
            if sd.acquisition and sd.acquisition.mode == "AUTO"}
    assert auto == attesi


def test_sorgenti_che_condividono_tabella_e_societa_si_distinguono_con_dim_filter():
    gruppi = defaultdict(list)
    for sd in _reg().sources.values():
        fc = sd.freshness
        if fc is None or fc.basis != "canonical":
            continue
        societa = sd.societa if sd.societa in ("ORTI", "INTUR") else "*"
        gruppi[(sd.canonical_table, societa)].append(sd)
    for key, sds in gruppi.items():
        if len(sds) > 1:
            for sd in sds:
                assert sd.freshness.dim_filter, f"{sd.source_name} condivide {key} senza dim_filter"


def test_dormienti_dichiarate():
    reg = _reg()
    for name in ("INTESA_BANCA_ORTI_APPEND", "INTESA_BANCA_INTUR_APPEND"):
        assert reg.get(name).freshness.dormant, name
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_registry_freshness_contracts.py -q`
Expected: FAIL al primo test con la lista delle 42 sorgenti promuovibili senza contratto.

- [ ] **Step 3: Aggiungi i blocchi a tutte le 48 voci**

Formato: i due blocchi vanno **in coda alla voce**, dopo `raw_storage:` (e dopo `notes:` dove c'è), con la stessa indentazione a 4 spazi degli altri campi. Tre esempi completi, poi la tabella con i valori esatti di tutte le altre.

```yaml
  MPS_BANCA_ORTI_APPEND:
    # ...campi esistenti invariati...
    freshness:
      tier: E
      cadence: monthly
      grain: daily
      coverage_column: data_operazione
      dims: [banca_id]
      dim_filter: {banca_id: [MPS, MPS_KROSS]}
    acquisition:
      mode: SEMI
      owner: Stefano
      location: "Homebanking MPS"
      report: "Lista movimenti"
      filters: "mese pieno, un file per conto (MPS e MPS KROSS)"
      format: xls

  ESOLVER_BILANCINO_ORTI_SNAPSHOT:
    # ...campi esistenti invariati...
    freshness:
      tier: E
      cadence: monthly
      grace_day: 20
      grain: monthly
      coverage_column: "LAST_DAY(PARSE_DATE('%Y-%m', mese))"
    acquisition:
      mode: SEMI
      owner: Stefano
      location: "Esolver"
      report: "Bilancio di verifica"
      filters: "mese chiuso, solo conti di livello imputazione"
      format: xls

  RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT:
    # ...campi esistenti invariati...
    freshness:
      tier: R
      cadence: monthly
      grain: daily
      coverage_column: data
    acquisition:
      mode: AUTO
      owner: job
      location: "Drive › Registro corrispettivi spiaggia"
      report: "INTUR_REGISTRO CORRISPETTIVI SPIAGGIA_<anno>.xlsx"
      filters: "compilato da amministrazione, un file per anno"
      job: "drive_fetch:RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT"
```

Valori per ogni voce. Colonne: tier · cadence (grace se ≠10) · grain · basis · coverage_column · dims · dim_filter · dormant ‖ mode · owner · location · report · filters · format · job. Dove una cella è `—` il campo si omette.

| source | tier | cadence | grain | basis | coverage_column | dims | dim_filter | dormant | mode | owner | location | report | filters | format | job |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MPS_BANCA_ORTI_APPEND | E | monthly | daily | canonical | data_operazione | [banca_id] | {banca_id: [MPS, MPS_KROSS]} | — | SEMI | Stefano | Homebanking MPS | Lista movimenti | mese pieno, un file per conto (MPS e MPS KROSS) | xls | — |
| MPS_BANCA_INTUR_APPEND | E | monthly | daily | canonical | data_operazione | [banca_id] | {banca_id: [MPS]} | — | SEMI | Stefano | Homebanking MPS | Lista movimenti | mese pieno | xls | — |
| SELLA_BANCA_INTUR_APPEND | E | monthly | daily | canonical | data_operazione | [banca_id] | {banca_id: [SELLA]} | — | SEMI | Stefano | Homebanking Sella | Lista movimenti conto | mese pieno | xls | — |
| INTESA_BANCA_INTUR_APPEND | E | monthly | daily | canonical | data_operazione | [banca_id] | {banca_id: [INTESA]} | "conto senza flussi dal 10/06/2026 (deciso 2026-06-30)" | SEMI | Stefano | Homebanking Intesa | Movimenti | mese pieno | xlsx | — |
| INTESA_BANCA_ORTI_APPEND | E | monthly | daily | canonical | data_operazione | [banca_id] | {banca_id: [INTESA]} | "conto senza flussi dal 05/06/2026 (deciso 2026-06-30)" | SEMI | Stefano | Homebanking Intesa | Movimenti | mese pieno | xlsx | — |
| ESOLVER_MOVIMENTI_ORTI_APPEND | E | monthly (20) | daily | canonical | data_registrazione | — | — | — | SEMI | Stefano | Esolver | Prima nota › Lista movimenti contabili (LISTAMOVCONT) | mese pieno | xls | — |
| ESOLVER_MOVIMENTI_INTUR_APPEND | E | monthly (20) | daily | canonical | data_registrazione | — | — | — | SEMI | Stefano | Esolver | Prima nota › Lista movimenti contabili (LISTAMOVCONT) | mese pieno | xls | — |
| ESOLVER_SCHEDA_ORTI_APPEND | E | monthly (20) | snapshot | canonical | data_snapshot | [banca_id] | — | — | SEMI | Stefano | Esolver | Scheda contabile raggruppata (mastrino, tutte le banche) | a fine mese | xlsx | — |
| ESOLVER_SCHEDA_INTUR_APPEND | E | monthly (20) | snapshot | canonical | data_snapshot | [banca_id] | — | — | SEMI | Stefano | Esolver | Scheda contabile raggruppata (mastrino, tutte le banche) | a fine mese | xlsx | — |
| ESOLVER_FATTUREACQUISTO_ORTI_APPEND | E | monthly (20) | daily | raw | — | — | — | — | MANUAL | Stefano | Esolver | Lista fatture acquisto per numero dettagliata | filtro su data di registrazione, salvato .xlsx | xlsx | — |
| ESOLVER_FATTUREACQUISTO_INTUR_APPEND | E | monthly (20) | daily | raw | — | — | — | — | MANUAL | Stefano | Esolver | Lista fatture acquisto per numero dettagliata | filtro su data di registrazione, salvato .xlsx | xlsx | — |
| ESOLVER_FATTUREVENDITA_ORTI_APPEND | E | monthly (20) | daily | raw | — | — | — | — | MANUAL | Stefano | Esolver | Lista fatture di vendita per cliente dettagliata | filtro su data di registrazione, salvato .xlsx | xlsx | — |
| ESOLVER_FATTUREVENDITA_INTUR_APPEND | E | monthly (20) | daily | raw | — | — | — | — | MANUAL | Stefano | Esolver | Lista fatture di vendita per cliente dettagliata | filtro su data di registrazione, salvato .xlsx | xlsx | — |
| ESOLVER_PARTITE_ORTI_SNAPSHOT | E | monthly (20) | snapshot | canonical | data_snapshot | — | — | — | SEMI | Stefano | Esolver | Situazione partite sintetica per fornitori | senza filtri | xlsx | — |
| ESOLVER_PARTITE_INTUR_SNAPSHOT | E | monthly (20) | snapshot | canonical | data_snapshot | — | — | — | SEMI | Stefano | Esolver | Situazione partite sintetica per fornitori | senza filtri | xlsx | — |
| ESOLVER_BILANCINO_ORTI_SNAPSHOT | E | monthly (20) | monthly | canonical | "LAST_DAY(PARSE_DATE('%Y-%m', mese))" | — | — | — | SEMI | Stefano | Esolver | Bilancio di verifica | mese chiuso, solo conti di livello imputazione | xls | — |
| ESOLVER_BILANCINO_INTUR_SNAPSHOT | E | monthly (20) | monthly | canonical | "LAST_DAY(PARSE_DATE('%Y-%m', mese))" | — | — | — | SEMI | Stefano | Esolver | Bilancio di verifica | mese chiuso, solo conti di livello imputazione | xls | — |
| ESOLVER_BUDGET_ORTI_SNAPSHOT | M | adhoc | snapshot | raw | — | — | — | — | SEMI | Stefano | Drive (Romita) | Master Completo / Budget ORTI | rilascio annuale | xlsx | — |
| ESOLVER_PF_ORTI_SNAPSHOT | E | monthly (20) | snapshot | raw | — | — | — | — | SEMI | Stefano | Drive › cartella master PF | Piano Finanziario post-rotate | rotation mensile | xlsx | — |
| ESOLVER_PF_INTUR_SNAPSHOT | E | monthly (20) | snapshot | raw | — | — | — | — | SEMI | Stefano | Drive › cartella master PF | Piano Finanziario post-rotate | rotation mensile | xlsx | — |
| HOTELCUBE_ACCODAMENTI_ORTI_APPEND | E | monthly | daily | canonical | data_registrazione | [business_unit_id] | — | — | SEMI | Stefano | HotelCube | Export accodamenti H_/R_/C_ (Corrispettivi, Movimenti, Fatture, Clienti .txt) | cartella giornaliera ACCODAMENTI HOTEL CUBE | txt | — |
| HOTELCUBE_STAMPACASSA_ORTI_APPEND | M | adhoc | snapshot | raw | — | — | — | — | MANUAL | Stefano | HotelCube | Stampa Cassa | per struttura, max 1000 righe per export | xlsx | — |
| RISTOCUBE_STAMPACASSA_ORTI_APPEND | M | adhoc | snapshot | raw | — | — | — | — | MANUAL | Stefano | RistoCube | Stampa Cassa | max 1000 righe per export | xlsx | — |
| ORTI_COPERTI_ORTI_APPEND | R | daily | daily | canonical | data_servizio | — | — | — | AUTO | job | Google Sheet Scarico Coperti | form conteggio pasti | — | — | ingest_coperti |
| ORTI_ECONOMATO_ORTI_APPEND | E | monthly | daily | raw | — | — | — | — | SEMI | Stefano | HotelCube economato | Situazione consumi / Consumi articoli | mese pieno | xlsx | — |
| POWERBI_CONSUMI_ORTI_APPEND | E | monthly | monthly | canonical | "LAST_DAY(DATE(anno, mese, 1))" | — | — | — | SEMI | Stefano | Power BI PanoramaGroup | Consumptions F&B Data | senza filtro Mese, sheet Export | xlsx | — |
| POWERBI_SEMANTICMODEL_ORTI_APPEND | M | adhoc | snapshot | raw | — | — | — | — | MANUAL | Stefano | Power BI PanoramaGroup | documentazione semantic model Z_DataSet | — | xlsx | — |
| POWERBI_RICAVIFB_ORTI_SNAPSHOT | E | monthly | monthly | canonical | "LAST_DAY(DATE(anno, mese, 1))" | [business_unit_id] | — | — | SEMI | Stefano | Power BI PanoramaGroup | Produzione Netta Dashboard | un file per struttura e mese | xlsx | — |
| POWERBI_VENDITEFB_ORTI_APPEND | E | monthly | daily | canonical | data_servizio | — | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Consumptions F&B Data (vendite RistoCube) | mese pieno | xlsx | — |
| POWERBI_MENUENGINEERING_ORTI_SNAPSHOT | E | adhoc | snapshot | canonical | snapshot_date | — | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Engineering F&B Data | periodo nel filtro, non scritto nel file | xlsx | — |
| POWERBI_PRODUZIONE_ORTI_SNAPSHOT | E | monthly | daily | canonical | data | [business_unit_id] | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Daily Production Report | Anno 2026, un file per struttura | xlsx | — |
| POWERBI_OCCUPAZIONE_ORTI_SNAPSHOT | E | monthly | daily | canonical | data | [business_unit_id] | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Produzione Consolidata Giornaliera | un file per struttura | xlsx | — |
| POWERBI_ANDAMENTOPRENOTAZIONI_ORTI_SNAPSHOT | E | weekly | snapshot | canonical | snapshot_date | [business_unit_id] | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Andamento Prenotazioni | tutte le strutture, senza filtro tipologia, Anno 2025+2026 | xlsx | — |
| POWERBI_DETTAGLIOPRENOTAZIONI_ORTI_SNAPSHOT | M | adhoc | snapshot | raw | — | — | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Detailed Data Prenotations | un file per struttura | xlsx | — |
| POWERBI_BOOKINGSTIPOLOGIA_ORTI_SNAPSHOT | E | monthly | snapshot | raw | — | — | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Detailed Data for Bookings | mese consuntivo, un file per struttura (le date in tabella arrivano al 2027: si misura il raw) | xlsx | — |
| POWERBI_NUMEROCAMERACLIENTI_ORTI_SNAPSHOT | M | adhoc | snapshot | raw | — | — | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Numero Camera Clienti | un file per struttura e anno | xlsx | — |
| POWERBI_CONSPREV_ORTI_SNAPSHOT | E | monthly | snapshot | canonical | snapshot_date | [business_unit_id] | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Consuntivo + Previsione mensile per classe | un file per struttura | xlsx | — |
| POWERBI_CONSPREVPAX_ORTI_SNAPSHOT | M | adhoc | snapshot | raw | — | — | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Consuntivo + Previsione camere/pax | un file per struttura | xlsx | — |
| PEC_MAILBOX_INTUR_APPEND | R | adhoc | daily | raw | — | — | — | — | AUTO | job | PEC Aruba | IMAP in.tur@pec.it | — | — | pec_fetch |
| PEC_MAILBOX_ORTI_APPEND | R | adhoc | daily | raw | — | — | — | — | AUTO | job | PEC Aruba | IMAP orti@pec.it | — | — | pec_fetch |
| PEC_MAILBOX_VIGNA_APPEND | R | adhoc | daily | raw | — | — | — | — | AUTO | job | PEC Aruba | IMAP vineyardamalficoast@pec.it | — | — | pec_fetch |
| PEC_MAILBOX_PERSONALE_APPEND | M | adhoc | daily | raw | — | — | — | — | MANUAL | Stefano | Webmail PEC MPS | export .eml | — | eml | — |
| RISTOCUBE_ORDERS_ORTI_APPEND | E | monthly | daily | canonical | data | — | — | — | MANUAL | Stefano | RistoCube | Orders Report | mese pieno | xlsx | — |
| POWERBI_CRUSCOTTO_ORTI_APPEND | M | adhoc | snapshot | raw | — | — | — | — | MANUAL | Stefano | Power BI PanoramaGroup | Cruscotto / CruscottoMP | — | xlsx | — |
| SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT | M | adhoc | snapshot | raw | — | — | — | — | MANUAL | Stefano | Spiagge.it | dump JSON prenotazioni | a fine stagione | json | — |
| RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT | R | monthly | daily | canonical | data | — | — | — | AUTO | job | Drive › Registro corrispettivi spiaggia | INTUR_REGISTRO CORRISPETTIVI SPIAGGIA_<anno>.xlsx | compilato da amministrazione, un file per anno | — | drive_fetch:RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT |
| MOOLTY_FBSPIAGGIA_INTUR_APPEND | E | monthly | daily | canonical | data | — | — | — | MANUAL | Stefano | Moolty | Report ordini | mese pieno | xlsx | — |
| SDI_FATTUREXML_ORTI_APPEND | E | quarterly | daily | raw | — | — | — | — | MANUAL | Stefano | Portale Fatture e Corrispettivi (AdE) | Richiesta massiva fatture ricevute | finestra DataRicezione trimestrale, vedi docs/procedures/ade_download_massivo | zip | — |

Note ai valori: PEC su `adhoc` perché la posta arriva quando arriva e conta solo che il job giri; coperti su `daily` va in `DATA_STUCK` nei mesi di chiusura invernale, si gestisce con `dormant` a stagione finita; `coverage_column` con espressione SQL va tra virgolette doppie in YAML perché contiene `'`.

- [ ] **Step 4: Verifica che i test passino e che il loader carichi**

Run: `pytest tests/test_registry_freshness_contracts.py tests/test_source_resolver.py tests/test_source_registry_pilot.py tests/test_pec_multicasella.py tests/test_drive_fetch.py -q && hotelops sources | head -5`
Expected: PASS; `hotelops sources` stampa la tabella senza errori di registry.

- [ ] **Step 5: Commit**

```bash
git add core/source_registry.yaml tests/test_registry_freshness_contracts.py
git commit -m "feat(registry): freshness e acquisition per tutte le 48 sorgenti"
```

---

### Task 5: `hotelops health` — blocco SORGENTI, flag, orfani

**Files:**
- Modify: `verticals/condges/cli_commands.py:112-190` (`_staleness_flag` + blocchi BANCHE/MOVIMENTI/IMPEGNO/SCHEDA di `cmd_health`)
- Modify: `cli.py:1022` (parser `health`)
- Modify: `core/pipeline_run.py` (rimuovere `IMPEGNO_STALENESS_DAYS`, `check_impegno_freshness`)
- Modify: `tests/test_health_checks.py` (rimuovere i test di `check_impegno_freshness`)
- Test: `tests/test_health_sorgenti_cli.py`

**Interfaces:**
- Consumes: `core.freshness.compute/render_text/to_json` (Task 3), `core.lineage.source_resolver.load_registry`.
- Produces: `hotelops health [--json] [--source NOME] [--all]`.

- [ ] **Step 1: Scrivi il test che fallisce**

```python
# tests/test_health_sorgenti_cli.py
"""cmd_health --json stampa il blocco SORGENTI e si ferma (spec 2026-09-09 §7)."""

import json
from argparse import Namespace
from datetime import date
from unittest.mock import patch

from core.freshness import SourceFreshness


def _item(name, status):
    return SourceFreshness(
        source_name=name, tier="E", mode="SEMI", owner="Stefano", status=status,
        covered_through=date(2026, 6, 30), expected_through=date(2026, 8, 31), age_days=71,
        last_raw_at=None, per_dim=[], blocks=["cash_control"], action="→ x\n  poi: y",
    )


def test_health_json_stampa_solo_sorgenti(capsys):
    from verticals.condges.cli_commands import cmd_health

    with patch("core.freshness.compute", return_value=[_item("MPS_BANCA_ORTI_APPEND", "STALE")]) as comp, \
         patch("core.lineage.source_resolver.load_registry") as lr, \
         patch("cli.query") as q:
        cmd_health(Namespace(json=True, source=None, all=False))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data[0]["source_name"] == "MPS_BANCA_ORTI_APPEND"
    assert data[0]["status"] == "STALE"
    assert comp.called and lr.called
    assert not q.called            # con --json nessun altro blocco viene eseguito


def test_health_source_filtra_una_riga(capsys):
    from verticals.condges.cli_commands import cmd_health

    items = [_item("MPS_BANCA_ORTI_APPEND", "STALE"), _item("SELLA_BANCA_INTUR_APPEND", "OK")]
    with patch("core.freshness.compute", return_value=items), \
         patch("core.lineage.source_resolver.load_registry"), \
         patch("cli.query"):
        cmd_health(Namespace(json=True, source="SELLA_BANCA_INTUR_APPEND", all=False))
    data = json.loads(capsys.readouterr().out)
    assert [d["source_name"] for d in data] == ["SELLA_BANCA_INTUR_APPEND"]
```

- [ ] **Step 2: Verifica che fallisca**

Run: `pytest tests/test_health_sorgenti_cli.py -q`
Expected: FAIL (`AttributeError: 'Namespace' object has no attribute 'json'` oppure output non JSON).

- [ ] **Step 3: Parser in `cli.py`**

Sostituire la riga `sub.add_parser("health", help="Health check dati")` con:

```python
    p_health = sub.add_parser("health", help="Health check dati")
    p_health.add_argument("--json", action="store_true",
                          help="Solo il blocco SORGENTI, in JSON (per hub e nudge)")
    p_health.add_argument("--source", default=None, help="Una sola sorgente, con tutte le dims")
    p_health.add_argument("--all", action="store_true", help="Mostra anche le RAW_ONLY")
```

- [ ] **Step 4: `cmd_health` in `verticals/condges/cli_commands.py`**

Cancellare `_staleness_flag` (righe 112-119) e, dentro `cmd_health`, tutto ciò che sta tra `print("\n  ═══ HEALTH CHECK ═══\n")` e il commento `# Budget loaded` (i quattro blocchi BANCHE, MOVIMENTI CONTABILI, IMPEGNO, SCHEDA CONTABILE). Al loro posto:

```python
def cmd_health(args):
    """Health check: freshness dati, gap, alert."""
    import json as _json
    from datetime import date as _date

    from cli import query, fmt_eur, bq

    # ── SORGENTI: freshness contract dal registry (core/freshness.py) ──────
    from core.freshness import compute, render_text, to_json
    from core.lineage.source_resolver import load_registry

    items = compute(load_registry(), query)
    only = getattr(args, "source", None)
    if only:
        items = [i for i in items if i.source_name == only]
    if getattr(args, "json", False):
        print(_json.dumps(to_json(items), ensure_ascii=False, indent=2))
        return

    print("\n  ═══ HEALTH CHECK ═══\n")
    print(render_text(items, today=_date.today(), show_all=bool(only or getattr(args, "all", False))))
    print()

    # Budget loaded
    ...   # da qui in poi il codice esistente resta identico
```

`fmt_eur` e `bq` restano importati perché i blocchi successivi li usano.

- [ ] **Step 5: Rimuovi gli orfani**

```bash
grep -rn "check_impegno_freshness\|IMPEGNO_STALENESS_DAYS\|_staleness_flag" --include="*.py" . | grep -v __pycache__
```

Expected: solo `core/pipeline_run.py` (definizione) e `tests/test_health_checks.py`. Se compare altro, fermarsi e segnalare. Poi:
- in `core/pipeline_run.py` cancellare la costante `IMPEGNO_STALENESS_DAYS` e la funzione `check_impegno_freshness` (righe ~217-248) e la loro riga nel docstring di modulo;
- in `tests/test_health_checks.py` cancellare i test che le usano (grep `impegno`).

- [ ] **Step 6: Verifica**

Run: `pytest tests/test_health_sorgenti_cli.py tests/test_health_checks.py -q && ruff check cli.py verticals/condges/cli_commands.py core/pipeline_run.py && pytest -q 2>&1 | tail -2`
Expected: PASS, suite intera verde.

- [ ] **Step 7: Commit**

```bash
git add cli.py verticals/condges/cli_commands.py core/pipeline_run.py tests/test_health_checks.py tests/test_health_sorgenti_cli.py
git commit -m "feat(health): blocco SORGENTI dal registry, --json/--source/--all; via i blocchi hardcoded"
```

---

### Task 6: `PipelineRun` nei fetcher automatici

**Files:**
- Modify: `ingest/drive_fetch.py:96-119` (`main`, blocco `with tempfile...`)
- Modify: `ingest/pec_fetch.py:236-240` (`main`, chiamata a `_giro` dentro il lock)
- Test: `tests/test_drive_fetch.py`, `tests/test_pec_fetch.py` (append)

**Interfaces:**
- Consumes: `core.pipeline_run.PipelineRun(pipeline_name, societa_id=None, file_sorgente=None)`.
- Produces: righe in `f_pipeline_runs` con `pipeline_name = "drive_fetch:<SOURCE>"` e `"pec_fetch"`, i nomi dichiarati in `acquisition.job` (Task 4).

- [ ] **Step 1: Scrivi i test che falliscono**

Append a `tests/test_drive_fetch.py`:

```python
def test_main_apre_un_pipeline_run_col_nome_del_job(monkeypatch, tmp_path):
    """Il job registra `drive_fetch:<SOURCE>` in f_pipeline_runs (spec 2026-09-09 §8)."""
    import sys
    from types import SimpleNamespace

    import ingest.drive_fetch as df

    runs = []

    class FakeRun:
        def __init__(self, pipeline_name, societa_id=None, file_sorgente=None):
            self.pipeline_name = pipeline_name
            self.societa_id = societa_id
            self.rows_new = None

        def __enter__(self):
            runs.append(self)
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("core.pipeline_run.PipelineRun", FakeRun)
    f = tmp_path / "x.xlsx"
    f.write_bytes(b"x")
    monkeypatch.setattr(df, "fetch_drive_file", lambda *a, **k: f)
    monkeypatch.setattr(
        "ingest.intake.intake_file",
        lambda *a, **k: SimpleNamespace(raw_object_id="r1", content_hash="h", deduped=False),
    )
    monkeypatch.setattr(
        "ingest.promotion.promote_raw_object",
        lambda *a, **k: SimpleNamespace(status="PROMOTED", reason=None, noop=False),
    )
    monkeypatch.setattr(sys, "argv", ["drive_fetch", "--source-name",
                                      "RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT"])
    df.main()
    assert [r.pipeline_name for r in runs] == ["drive_fetch:RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT"]
    assert runs[0].societa_id == "INTUR"
    assert runs[0].rows_new == 1
```

Append a `tests/test_pec_fetch.py` (usare gli stessi fixture/patch del file per lock e registry: leggere le righe 15-60 del file prima, e riusare il modo in cui gli altri test evitano GCS):

```python
def test_main_apre_un_pipeline_run_pec_fetch(monkeypatch):
    """Il giro notturno registra `pec_fetch` in f_pipeline_runs (spec 2026-09-09 §8)."""
    import sys
    from contextlib import nullcontext

    import ingest.pec_fetch as pf

    runs = []

    class FakeRun:
        def __init__(self, pipeline_name, societa_id=None, file_sorgente=None):
            self.pipeline_name = pipeline_name

        def __enter__(self):
            runs.append(self)
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("core.pipeline_run.PipelineRun", FakeRun)
    monkeypatch.setattr(pf, "pec_lock_held", lambda: nullcontext())
    monkeypatch.setattr(pf, "_giro", lambda names, since_days, promote: None)
    monkeypatch.setattr(pf.signal, "signal", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["pec_fetch", "--source-name", "PEC_MAILBOX_INTUR_APPEND"])
    pf.main()
    assert [r.pipeline_name for r in runs] == ["pec_fetch"]
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_drive_fetch.py::test_main_apre_un_pipeline_run_col_nome_del_job tests/test_pec_fetch.py::test_main_apre_un_pipeline_run_pec_fetch -q`
Expected: FAIL con `assert [] == [...]`.

- [ ] **Step 3: `ingest/drive_fetch.py`**

Sostituire il blocco `with tempfile.TemporaryDirectory() as tmp:` con:

```python
    from core.pipeline_run import PipelineRun

    with PipelineRun(f"drive_fetch:{args.source_name}", societa_id=source_def.societa) as run, \
         tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        log.info("Fetching Drive file_id=%s for source %s", file_id, args.source_name)
        local_file = fetch_drive_file(file_id, dest_dir=tmp_path, key_path=args.key)

        from ingest.intake import intake_file

        result = intake_file(local_file, source_name=args.source_name, actor="drive_sync")
        run.rows_new = 0 if result.deduped else 1
        print(f"raw_object_id={result.raw_object_id}")
        print(f"content_hash={result.content_hash}")
        print(f"deduped={result.deduped}")

        if not args.no_promote:
            from ingest.promotion import promote_raw_object

            if not result.raw_object_id:
                print(
                    "ERROR: intake returned no raw_object_id (lineage gate disabled?) — promote skipped",
                    file=sys.stderr,
                )
                sys.exit(1)
            pr = promote_raw_object(result.raw_object_id, actor="drive_sync")
            print(f"promote_status={pr.status} reason={pr.reason or '-'} noop={pr.noop}")
```

L'import va **dentro** `main()` (come gli altri import lazy del file), così il test può sostituire `core.pipeline_run.PipelineRun` prima della chiamata.

- [ ] **Step 4: `ingest/pec_fetch.py`**

Sostituire

```python
        with pec_lock_held():
            _giro(names, since_days=args.since_days, promote=not args.no_promote)
```

con

```python
        from core.pipeline_run import PipelineRun

        with pec_lock_held(), PipelineRun("pec_fetch"):
            _giro(names, since_days=args.since_days, promote=not args.no_promote)
```

Un `SystemExit` alzato da `_giro` per caselle guaste attraversa `PipelineRun.__exit__` e marca il run `FAIL`: è il comportamento voluto (il job rosso resta rosso in `f_pipeline_runs`).

- [ ] **Step 5: Verifica**

Run: `pytest tests/test_drive_fetch.py tests/test_pec_fetch.py -q && ruff check ingest/drive_fetch.py ingest/pec_fetch.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ingest/drive_fetch.py ingest/pec_fetch.py tests/test_drive_fetch.py tests/test_pec_fetch.py
git commit -m "feat(ingest): drive_fetch e pec_fetch aprono un PipelineRun col nome del job"
```

---

### Task 7: Smoke reale, documentazione, PR

**Files:**
- Modify: `STATUS.md` (voce di diario in testa), `CLAUDE.md` (riga cheat-sheet `hotelops health`)

- [ ] **Step 1: Smoke su BigQuery**

```bash
hotelops health 2>&1 | head -80
hotelops health --json | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d), 'sorgenti'); [print(x['status'], x['source_name']) for x in d[:12]]"
hotelops health --source MPS_BANCA_ORTI_APPEND
```

Expected (al 2026-09-10, prima degli export arretrati): blocco SORGENTI in testa; `ESOLVER_PARTITE_ORTI_SNAPSHOT` 🔴 con frase "Esolver › Situazione partite…"; banche `!` in scadenza (grazia fino al 10) o 🔴 dall'11; `ORTI_COPERTI_ORTI_APPEND` ✓ con "job ingest_coperti OK Nh fa"; `RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT` ✓; PEC ×3 con job `pec_fetch` — **JOB_DOWN finché il job cloud non gira con l'immagine nuova** (Task 6 non è deployato): atteso e da scrivere in STATUS come handoff; INTESA ×2 ⏸; nessuna riga `NO_CONTRACT`. Il resto di health (BUDGET, PF, drift, watermark, pipeline stale, docs) invariato.

Se una riga non torna (colonna inesistente, espressione SQL errata), l'errore BigQuery indica il gruppo: correggere `coverage_column` nel registry, non il motore.

- [ ] **Step 2: STATUS.md**

Inserire in testa a `STATUS.md` (sopra la voce del 2026-09-08) una voce datata 2026-09-10 con: cosa è entrato (contratto nel registry, `core/freshness.py`, `hotelops health` SORGENTI + flag, PipelineRun nei fetcher), l'output reale del blocco SORGENTI incollato (prime 15 righe), e tre HANDOFF: (a) rebuild immagine `jobs` + redeploy dei job `spiaggia-corrispettivi` e `pec-fetch` con `scripts/cloud/10_build_image.sh` e gli script 40/70, altrimenti restano `JOB_DOWN`; (b) export arretrati elencati dal nuovo health; (c) slice successive: pagina Ingest hub sullo stesso motore, `period_from/to` sui raw object, nudge settimanale.

- [ ] **Step 3: CLAUDE.md**

Nel cheat-sheet §Commands sostituire la riga `hotelops health                             # Freshness, gaps, alerts` con:

```
hotelops health [--json] [--source X] [--all]   # SORGENTI dal registry (freshness contract) + gap, drift, alert
```

- [ ] **Step 4: Suite completa, lint, commit, PR**

```bash
pytest -q 2>&1 | tail -2 && ruff check . && ruff format --check .
git add STATUS.md CLAUDE.md
git commit -m "docs(status): freshness contract — SORGENTI in health, handoff redeploy job"
git push -u origin feat/freshness-contract
gh pr create --title "feat(health): freshness contract — SORGENTI dal registry" --body "$(cat <<'EOF'
Implementa docs/superpowers/specs/2026-09-09-freshness-contract-design.md.

- contratti `freshness`/`acquisition` in SourceDefinition, popolati per 48 sorgenti
- `core/freshness.py`: stato per sorgente (calendario mensile, grazia 10/20), frase azione, 3 query
- `hotelops health`: blocco SORGENTI al posto di BANCHE/MOVIMENTI/IMPEGNO/SCHEDA; `--json`, `--source`, `--all`
- `drive_fetch`/`pec_fetch` aprono un PipelineRun col nome del job

Handoff: rebuild immagine jobs + redeploy `spiaggia-corrispettivi` e `pec-fetch`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01RCMjMUnPuwqnLYrJULLtTf
EOF
)"
```

Expected: suite verde, ruff pulito, PR aperta. Il merge lo decide Stefano.
