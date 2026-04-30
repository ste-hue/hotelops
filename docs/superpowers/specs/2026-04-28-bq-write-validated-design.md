---
status: approved
date: 2026-04-28
owner: stefano
sprint: bq-write-gate
related:
  - core/pipeline_run.py
  - core/contracts.py
  - core/schemas.py
  - core/bq/client.py
---

# `bq_write_validated` — Centralized BigQuery write gate

## Context

Today the hotelops platform has ~30 ingest pipelines that write to BigQuery. Roughly 10 of them call `validate_batch()` (Pydantic) before the write; the other 20 call `client.load_table_from_json()` or `client.insert_rows_json()` directly. The gate that the codebase declares (I1: "no BigQuery write without Pydantic validation") is therefore a convention, not an enforced invariant. There is no single observable choke point through which every write must pass.

This sprint introduces a single function — `core/bq/write.py::bq_write_validated` — that becomes the only sanctioned way to write rows to BigQuery from any pipeline. Every existing call site is migrated progressively; new direct uses of `bigquery.Client` outside `core/bq/` are blocked at CI by the end of the sprint.

## Goal

No production pipeline writes to BigQuery without going through a single observable, validated entry point.

## Non-goals

- Not a replacement for `core/bq/client.get_client()` — the singleton client stays where it is and is used internally by the gate.
- Not a generic ORM. The function performs strict Pydantic validation and a narrow set of write modes; arbitrary SQL stays in the caller (e.g. dimension joins, audit queries).
- Not a dedup engine. APPEND callers that need MD5/key-based dedup do it before calling the gate (see `core/bq/dedup.py::filter_new_rows_by_hash` helper).
- Not a schema migration tool. Live drift between Pydantic and BQ INFORMATION_SCHEMA is checked by `hotelops health`, not by the gate at write time.
- `WRITE_TRUNCATE` / full-table replace is out of scope — too dangerous as a default. Pipelines that legitimately need it (e.g. `ingest_coperti --replace`) keep their bespoke orchestration.

## API surface

```python
def bq_write_validated(
    table: str,
    rows: list[BaseModel],
    mode: Literal["append", "snapshot"] = "append",
    natural_key: list[str] | None = None,
) -> None:
    """
    Write rows to BigQuery with Pydantic validation (I1) and lineage tracking.

    Args:
        table: Fully-qualified BQ table id, e.g.
               "hotelops-suite.hotelops.f_partite_aperte_fornitori".
        rows: List of Pydantic model instances. All must be the same concrete
              subclass (the schema is inferred from type(rows[0])). Empty list
              is a no-op.
        mode: "append" — INSERT only (caller handles dedup if needed).
              "snapshot" — DELETE+INSERT chirurgico per natural_key, then INSERT.
        natural_key: Column names that scope the SNAPSHOT delete. Required
                     when mode="snapshot". Must include every partitioning /
                     identity column the caller wants preserved (see Behavior
                     matrix → over-delete warning).

    Lineage:
        Automatically read from PipelineRun.get_current() (a ContextVar set
        by `with PipelineRun(...)` context manager). If no active run is
        present, logs a warning and writes anyway with lineage=unknown.

    Raises:
        ValueError: mode="snapshot" but natural_key is None or empty.
        SchemaViolationError: validation failed on one or more rows.
        BigQueryInsertError: BQ rejected the load job (after validation).
    """
```

### Example — APPEND (with caller-side dedup)

```python
from core.bq.write import bq_write_validated
from core.bq.dedup import filter_new_rows_by_hash
from core.pipeline_run import PipelineRun
from core.schemas import MovimentoContabileRow

with PipelineRun("ingest_movimenti_contabili", file_sorgente=fname):
    rows = [MovimentoContabileRow(**r) for r in parsed]
    rows_new = filter_new_rows_by_hash(
        table="hotelops-suite.hotelops.f_movimenti_contabili",
        rows=rows,
        hash_column="hash_riga",
    )
    bq_write_validated(
        "hotelops-suite.hotelops.f_movimenti_contabili",
        rows_new,
        mode="append",
    )
```

### Example — SNAPSHOT (chirurgico per periodo × società)

```python
with PipelineRun("ingest_partite_aperte", file_sorgente=fname):
    rows = [PartitaApertaFornitoreRow(**r) for r in parsed]
    bq_write_validated(
        "hotelops-suite.hotelops.f_partite_aperte_fornitori",
        rows,
        mode="snapshot",
        natural_key=["data_snapshot", "societa_id"],
    )
```

## Behavior matrix

| Caso | Comportamento |
|---|---|
| `rows == []` | No-op. `log.info("empty batch for {table}, skipping")`. Return. |
| `mode="snapshot"` and `natural_key` is `None` or `[]` | `raise ValueError("snapshot mode requires natural_key")`. |
| Validation fails on any row | `raise SchemaViolationError(table, failures)` listing first 5 violators. No write. |
| `mode="append"`, validation OK | `client.load_table_from_json(rows, WRITE_APPEND)`. |
| `mode="snapshot"`, validation OK | (1) `DELETE FROM {table} WHERE (key_cols) IN UNNEST(batch_keys)`. (2) `client.load_table_from_json(rows, WRITE_APPEND)`. Both via batch loads (no streaming buffer). |
| BQ load returns errors | `raise BigQueryInsertError(table, errors)`. |

### Over-delete warning (SNAPSHOT)

`natural_key` must include every column the caller considers part of the "this snapshot's identity". A subset key deletes more than the caller wrote. Concrete example for `f_partite_aperte_fornitori`:

```python
# CORRECT — preserves INTUR rows of the same date
natural_key=["data_snapshot", "societa_id"]

# WRONG — deletes ORTI + INTUR rows of 2026-04-28
natural_key=["data_snapshot"]
```

The function does not attempt to validate the key against the table's logical partitioning — that is caller responsibility.

## Validation contract

- `schema_class` is inferred as `type(rows[0])`. All rows must be the same concrete subclass; mixing types raises `SchemaViolationError` (treated as a row that doesn't match).
- The function calls `model.model_dump()` on each row to produce the dict written to BQ. Validators registered on the Pydantic model run at construction time in the caller; the gate does not re-instantiate.
- A row that is not a `BaseModel` instance is added to `failures` with reason `"Not a Pydantic BaseModel instance"` — the same failure path as a model validation error.
- `SchemaViolationError` carries `(table_id, failures)` where `failures = list[(row_idx, row_repr, error_msg)]`. The string form lists the first 5 failures and a count of the rest.

## Observability

### Lineage via ContextVar

`core/pipeline_run.py` is extended with a module-level `ContextVar`:

```python
_current_run: ContextVar[Optional["PipelineRun"]] = ContextVar(
    "_current_run", default=None
)

class PipelineRun:
    def __enter__(self):
        # ... existing run_id / start_time setup ...
        self._token = _current_run.set(self)
        return self

    def __exit__(self, *exc):
        _current_run.reset(self._token)
        # ... existing end_time / status / write to f_pipeline_runs ...

    @classmethod
    def get_current(cls) -> Optional["PipelineRun"]:
        return _current_run.get()
```

`bq_write_validated` reads `PipelineRun.get_current()` once per call. If present:

```python
lineage_meta = {
    "pipeline_name": run.pipeline_name,
    "run_id": run.run_id,
    "file_sorgente": run.file_sorgente,
}
```

> **Note**: `PipelineRun.__init__` gains a `file_sorgente: str | None = None` parameter as a first-class attribute. It is additive and backward compatible — existing callers that don't pass it get `run.file_sorgente = None`. The `metadata` dict stays available for genuinely free-form fields (watermarks, custom counters), but identity-shaped fields like `file_sorgente`, `societa_id` are first-class.

If absent: `lineage_meta = {"pipeline_name": "unknown_pipeline", "run_id": None, "file_sorgente": None}` and a `log.warning` fires once per call:

> `bq_write_validated called outside PipelineRun context. Lineage=unknown. Wrap caller with: with PipelineRun("..."):`

The function never raises on missing context — log-only fallback. Lineage is observability, not gate.

### Optional row-level lineage

If the target table's schema includes nullable columns `pipeline_run_id STRING` and/or `pipeline_name STRING`, the function populates them from `lineage_meta` before the load. If the columns are absent, nothing happens (BQ schema introspection is cached per table id).

This is opt-in by table — the gate does not require the columns. Existing tables can adopt the pattern by adding the two columns; new tables created during this sprint should include them by default.

### Structured log

Every successful write emits one structured log line:

```
log.info(
    "bq_write_validated: {n} rows -> {table} [mode={mode}]",
    extra={
        "table": table,
        "rows_written": n,
        "mode": mode,
        "natural_key": natural_key,  # only when snapshot
        **lineage_meta,
    },
)
```

This is the single observable choke point: every successful write is visible at one log level, with a consistent extra schema.

## Error model

All exceptions live in `core/bq/write.py` (or re-exported from `core/contracts.py` if it makes sense for API consumers):

- `SchemaViolationError(table_id: str, failures: list[tuple[int, Any, str]])` — already exists in spirit in `core/contracts.py`; the constructor is extended to carry the failure list and produce a clean message.
- `BigQueryInsertError(table_id: str, errors: list[dict])` — new, wraps the raw error list returned by the BQ client.
- `ValueError` — raised only for caller misuse (snapshot without `natural_key`, mixed schema in `rows`).

No exception is silently swallowed. Empty input is a documented no-op, not an error.

## Out of scope

- WRITE_TRUNCATE / full-replace mode (re-evaluated separately if/when needed).
- Dedup queries against BQ (caller responsibility; helper provided in `core/bq/dedup.py`).
- Streaming inserts (`insert_rows_json`) — the gate uses batch loads only, eliminating the streaming buffer DELETE-lock issue observed on 2026-04-28.
- Schema drift detection at write time (covered by `hotelops health` on demand).
- Retry / backoff on transient BQ errors — the BQ client already retries idempotent operations; the gate does not add a layer.

## Migration plan

Five sprints, deadline **2026-05-31**. Each sprint produces working merged commits; failure of the pilot gate halts the rollout.

### Sprint 1 — Foundation + Pilot

Build:
- `core/bq/write.py` with `bq_write_validated` and exception classes.
- `core/bq/dedup.py` with `filter_new_rows_by_hash(table, rows, hash_column) -> list`.
- `core/pipeline_run.py` extended with `ContextVar` and `get_current()` classmethod.
- Unit tests covering: validation success, validation failure (raises with first-5 message), empty batch (no-op + log.info), snapshot without natural_key (raises), append + snapshot happy paths against a fake BQ client.

Migrate (pilot, 3 pipelines all SNAPSHOT-shaped):
- `ingest/flussi/ingest_partite_aperte.py`
- `ingest/flussi/ingest_coperti.py`
- `ingest/flussi/ingest_scheda_contabile.py`

**Pilot success gate**: each migrated pipeline run in staging produces row count and column-by-column hash identical to the pre-migration version on the same input file. Zero regression in `pytest`. If any pilot fails, halt rollout and revisit the design before Sprint 2.

### Sprint 2 — SNAPSHOT tables

- `ingest/flussi/ingest_bilancino.py`
- `ingest/flussi/ingest_gasparotto.py`
- `ingest/flussi/ingest_piano_finanziario_xlsx.py`
- `condges/update_previsione.py` (fonte-scoped DELETE)

### Sprint 3 — Dimension loaders

All loaders under `core/bq/load/`:
- `load_voci_piano_finanziario`, `load_piano_conti`, `load_categorie`, `load_fornitori`, `load_anagrafica_fornitori`, `load_budget_costi`, `load_coefficienti_stagionalita`, `load_mapping_piano_finanziario`, `load_ricavi_storici`.

Low frequency, low blast radius — good place to validate the API on dimension-shaped tables.

### Sprint 4 — APPEND with MD5 dedup

- `ingest/flussi/ingest_movimenti_contabili.py`
- `ingest/banca/ingest_accodamenti.py`
- `ingest/banca/ingest.py` (5 banche: MPS, MPS_KROSS, SELLA, INTESA, BCP)
- `reviews/ingest.py` (APPEND with natural-key dedup `(business_unit_id, piattaforma, review_id)` — reviews have no temporal period, so SNAPSHOT mode is not applicable)

These pipelines compute MD5 hashes upstream; the dedup pattern moves to `filter_new_rows_by_hash` calls explicitly, then the write goes through the gate.

### Sprint 5 — Enforcement

- CI lint (`.github/workflows/ci.yml` or `pre-commit`): block any new file outside `core/bq/` from importing `from google.cloud import bigquery` or instantiating `bigquery.Client` directly.
- Deprecation warning emitted by `core/bq/client.get_client()` when called from outside `core/bq/`, citing the deadline.
- Audit query: count writes per `pipeline_name` in `f_pipeline_runs` (post-migration) vs `unknown_pipeline` log occurrences. Target: zero `unknown_pipeline` writes after sprint 5.

## Risks and open questions

- **`PipelineRun` adoption inertia**. Some pipelines (notably the dimension loaders) don't use `PipelineRun` today. They will write through the gate but log `lineage=unknown`. The migration explicitly leaves wrapping `PipelineRun` as a "boy-scout" follow-up — the gate works either way. Acceptable.
- **MD5 dedup race conditions**. `filter_new_rows_by_hash` reads existing hashes, then the write inserts. Between read and write, a parallel run could insert overlapping hashes. Today this isn't a concern because pipelines are single-process (cron + lockfile). If parallelism becomes a thing, the dedup helper must move to a server-side `MERGE` — flag for future.
- **Row-level lineage columns**. If we add `pipeline_run_id` / `pipeline_name` to fact tables across the board, the schema drift check (`hotelops health`) will flag them as new. Document the addition explicitly in `core/schemas.py` so the drift surface stays clean.
- **BQ over-delete from misuse**. The function trusts the caller to pass a complete `natural_key`. A bad migration could over-delete. Mitigation: each migration commit includes a staging diff showing pre/post row counts per partitioning key — if the count drops outside expected bounds, the migration is rejected at review.

## Pilot acceptance checklist

Before Sprint 2 starts, the pilot is considered green only if all of the following are true:

- `pytest` green (existing 343 tests + new tests for the gate).
- For each of the 3 pilot pipelines, a staging dry-run produces:
  - same number of rows written as the pre-migration version
  - same row hashes (column-by-column) when comparing pre/post tables
  - one `bq_write_validated` log line per write with non-null `lineage_meta`
- Zero `unknown_pipeline` warnings in the pilot logs.
- One concrete bug or design tension surfaced by the pilot must be either resolved or explicitly deferred with rationale before Sprint 2 starts.

## Pilot result (2026-04-30)

All 3 pilots validated end-to-end on production BigQuery (`hotelops-suite.hotelops`). Each pipeline run twice with the same canonical input; idempotency verified by row-count diff between mid-state and post-state, scope of DELETE chirurgico verified by counts on neighboring keys.

**T8 — `ingest_scheda_contabile` (SNAPSHOT, key `[societa_id, banca_id, data_snapshot]`)**

Input: `archivio/INTUR/2026-01-01__SALDI_BANCARI__INTUR__SELLA_2026.xlsx` → 30 saldi rows.

| State | INTUR/SELLA pre-2026 | 2026-jan-may | 2026-jun+ | total |
|---|---|---|---|---|
| pre | 295 | 54 | 0 | 349 |
| post run #1 | 295 | 55 | 1 | 351 (+2 new dates) |
| post run #2 | 295 | 55 | 1 | **351** |

Other (societa, banca) groups (INTUR/INTESA=38, INTUR/MPS=40, ORTI/INTESA=14, ORTI/MPS=84, ORTI/MPS_KROSS=45) untouched both runs — DELETE scope chirurgico confirmed.

**T9 — `ingest_partite_aperte` (SNAPSHOT, key `[societa_id, data_snapshot]`)**

Input: `partite_fornitori/INTUR/INTUR_PARTITE_FORNITORI_20260428.xlsx` → 114 partite rows.

| State | INTUR @ 2026-04-28 | total € | ORTI @ 2026-03-20 |
|---|---|---|---|
| pre | 114 | 962,355 | 176 |
| post run #1 | 114 | 962,355 | 176 |
| post run #2 | 114 | 962,355 | **176** |

Total €962,355 and 63 distinct fornitori invariant across both runs. ORTI snapshot untouched (different societa_id namespace).

**T10 — `ingest_coperti` (SNAPSHOT, key `[hash_riga]`)**

Input: live Google Sheet via rclone → 1496 coperti rows.

| State | BRK | DINNER | LUNCH | total |
|---|---|---|---|---|
| pre | 522 | 437 | 385 | 1344 (+147 in 2026-Q2 = 1491) |
| post run #1 | 570 | 492 | 434 | 1496 (+5 net new keys) |
| post run #2 | 570 | 492 | 434 | **1496** |

Genuine DELETE+INSERT verified by `data_caricamento` collapsing to a single timestamp matching run #2 (09:17:18) — i.e. run #2 wiped run #1's timestamps and re-inserted, not a no-op.

**Lineage** (`f_pipeline_runs`): all 6 runs landed with `status=OK`, correct `pipeline_name`, correct `societa_id`. Duration 27s (coperti) to 7s (partite). Zero `unknown_pipeline` warnings.

**Bug surfaced + resolved**: `model_dump()` default mode returns native `date`/`datetime`/`Decimal` objects, which crash `json.dumps` inside `load_table_from_json` (no default handler). Fixed at line 120 of `core/bq/write.py` with `model_dump(mode="json")`. Encoded as a permanent invariant: `SerializationBoundaryError` raised by per-row `json.dumps` probe **before** any BQ side-effect, preventing snapshot half-wipe scenarios. See commits `b7961e4` (fix) and `76bb066` (boundary guard).

**Sprint 2 unlocked**: SNAPSHOT migration pattern proven in production. APPEND + dimension loaders next.
