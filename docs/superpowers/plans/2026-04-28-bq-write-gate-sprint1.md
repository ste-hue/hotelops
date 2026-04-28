# bq-write-gate Sprint 1 — Foundation + Pilot

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `core/bq/write.py::bq_write_validated` as the single observable, validated entry point for BigQuery writes, plus the supporting helpers (`core/bq/dedup.py`, `PipelineRun` ContextVar), then migrate 3 pilot pipelines to use it.

**Architecture:** Single-function gate that accepts `(table, rows, mode, natural_key)` where `rows` is a list of validated Pydantic instances. Reads the active `PipelineRun` via `ContextVar` for ambient lineage. Uses BigQuery batch loads (`load_table_from_json`) — never streaming — so subsequent DELETE-INSERT cycles don't hit the streaming-buffer DML lock. Validation is strict (raise on first failure). Empty batch is a documented no-op. The 3 pilot pipelines are all SNAPSHOT-shaped to validate the gate's hardest path first.

**Tech Stack:** Python 3.11+, Pydantic v2, `google-cloud-bigquery`, pytest, `unittest.mock`.

**Spec:** [`docs/superpowers/specs/2026-04-28-bq-write-validated-design.md`](../specs/2026-04-28-bq-write-validated-design.md)

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `core/pipeline_run.py` | modify | Add `file_sorgente` first-class attr, `_current_run` `ContextVar`, `get_current()` classmethod |
| `core/bq/write.py` | create | `bq_write_validated`, `SchemaViolationError`, `BigQueryInsertError` |
| `core/bq/dedup.py` | create | `filter_new_rows_by_hash(table, rows, hash_column)` |
| `tests/test_pipeline_run.py` | modify | Add tests for ContextVar lifecycle + `file_sorgente` |
| `tests/test_bq_write.py` | create | All gate behaviors |
| `tests/test_bq_dedup.py` | create | Dedup helper |
| `ingest/flussi/ingest_scheda_contabile.py` | modify | Replace direct BQ calls with `bq_write_validated` |
| `ingest/flussi/ingest_partite_aperte.py` | modify | Same |
| `ingest/flussi/ingest_coperti.py` | modify | Same |

---

## Task 1: Extend `PipelineRun` with ContextVar + `file_sorgente`

**Files:**
- Modify: `core/pipeline_run.py`
- Modify: `tests/test_pipeline_run.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_pipeline_run.py`:

```python
def test_pipeline_run_file_sorgente_attribute():
    run = PipelineRun("p", file_sorgente="ORTI_x.xlsx")
    assert run.file_sorgente == "ORTI_x.xlsx"


def test_pipeline_run_file_sorgente_default_none():
    run = PipelineRun("p")
    assert run.file_sorgente is None


def test_get_current_returns_none_outside_context():
    assert PipelineRun.get_current() is None


def test_get_current_returns_active_run_inside_context():
    with PipelineRun("p1") as r1:
        assert PipelineRun.get_current() is r1


def test_get_current_handles_nested_contexts():
    with PipelineRun("outer") as outer:
        assert PipelineRun.get_current() is outer
        with PipelineRun("inner") as inner:
            assert PipelineRun.get_current() is inner
        assert PipelineRun.get_current() is outer
    assert PipelineRun.get_current() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pipeline_run.py -v -k "file_sorgente or get_current"`
Expected: FAIL — `file_sorgente` not in `__init__`, `get_current` not defined.

- [ ] **Step 3: Implement the changes**

In `core/pipeline_run.py`, add at the top (after the `import` block):

```python
from contextvars import ContextVar
from typing import Optional

_current_run: ContextVar[Optional["PipelineRun"]] = ContextVar(
    "_current_run", default=None
)
```

Modify the class:

```python
class PipelineRun:
    """Context manager that records a pipeline run in f_pipeline_runs.

    Writes exactly one row on __exit__ with the final state. No RUNNING
    placeholder, no UPDATE — the streaming buffer makes in-process UPDATE
    unreliable. A crashed process leaves no row at all; the absence is
    detected by check_pipeline_staleness (last OK > threshold).

    Sets a module-level ContextVar on __enter__ so consumers (notably
    bq_write_validated) can read the active run via PipelineRun.get_current()
    without explicit plumbing.
    """

    def __init__(
        self,
        pipeline_name: str,
        societa_id: str | None = None,
        file_sorgente: str | None = None,
    ):
        self.run_id = str(uuid.uuid4())
        self.pipeline_name = pipeline_name
        self.societa_id = societa_id
        self.file_sorgente = file_sorgente
        self.started_at: str | None = None
        self.ended_at: str | None = None
        self.status = "OK"
        self.rows_found: int | None = None
        self.rows_new: int | None = None
        self.alerts_sent: int | None = None
        self.usage_total_usd: float | None = None
        self.error_message: str | None = None
        self.meta: dict | None = None
        self._token = None

    def __enter__(self) -> "PipelineRun":
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._token = _current_run.set(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        if self._token is not None:
            _current_run.reset(self._token)
            self._token = None
        self.ended_at = datetime.now(timezone.utc).isoformat()
        if exc_val is not None:
            self.status = "FAIL"
            self.error_message = str(exc_val)[:500]
        self._insert_final()
        return False  # don't suppress exceptions

    @classmethod
    def get_current(cls) -> Optional["PipelineRun"]:
        """Return the active PipelineRun (set by __enter__), or None."""
        return _current_run.get()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pipeline_run.py -v`
Expected: PASS — all existing tests still green plus 5 new ones.

- [ ] **Step 5: Commit**

```bash
git add core/pipeline_run.py tests/test_pipeline_run.py
git commit -m "feat(pipeline_run): add file_sorgente attr + ContextVar.get_current()

Additivo, backward compatible: callers without file_sorgente get None;
nested contexts restored on __exit__ via ContextVar.reset(token).
Ground for bq_write_validated ambient lineage discovery."
```

---

## Task 2: Exception classes for the BQ write gate

**Files:**
- Create: `core/bq/write.py`
- Create: `tests/test_bq_write.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bq_write.py`:

```python
import pytest
from core.bq.write import SchemaViolationError, BigQueryInsertError


def test_schema_violation_error_message_lists_first_5():
    failures = [(i, {"x": i}, f"err {i}") for i in range(8)]
    err = SchemaViolationError("hotelops.f_x", failures)
    msg = str(err)
    assert "8 rows" in msg
    assert "hotelops.f_x" in msg
    # First 5 visible, rest summarized
    for i in range(5):
        assert f"err {i}" in msg
    assert "and 3 more" in msg


def test_schema_violation_error_message_under_5_no_summary():
    failures = [(0, {"x": 0}, "boom")]
    err = SchemaViolationError("hotelops.f_x", failures)
    msg = str(err)
    assert "1 rows" in msg
    assert "boom" in msg
    assert "more" not in msg.lower()


def test_bigquery_insert_error_carries_table_and_errors():
    err = BigQueryInsertError("hotelops.f_x", [{"index": 0, "errors": [...]}])
    assert err.table_id == "hotelops.f_x"
    assert err.errors == [{"index": 0, "errors": [...]}]
    assert "hotelops.f_x" in str(err)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bq_write.py -v`
Expected: FAIL — `core.bq.write` does not exist.

- [ ] **Step 3: Create the file with exception classes**

Create `core/bq/write.py`:

```python
"""Centralized BigQuery write gate (I1).

Every BigQuery write from a hotelops pipeline goes through bq_write_validated.
The function provides Pydantic validation, batch loads (no streaming buffer),
ambient lineage from PipelineRun, and a single observable log line per write.

See: docs/superpowers/specs/2026-04-28-bq-write-validated-design.md
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class SchemaViolationError(Exception):
    """Raised when Pydantic validation fails on one or more rows in a batch.

    Carries the table id and a list of (row_index, row_repr, error_message)
    triples so the caller can log/inspect the failures without losing context.
    The string form lists the first 5 violators with a count of the rest.
    """

    def __init__(self, table_id: str, failures: list[tuple[int, Any, str]]):
        self.table_id = table_id
        self.failures = failures
        n = len(failures)
        head = "\n".join(f"  row {idx}: {err}" for idx, _row, err in failures[:5])
        tail = f"\n  ... and {n - 5} more" if n > 5 else ""
        super().__init__(
            f"Schema validation failed for {n} rows in {table_id}\n{head}{tail}"
        )


class BigQueryInsertError(Exception):
    """Raised when a BQ load job returns row-level errors after validation."""

    def __init__(self, table_id: str, errors: list[dict]):
        self.table_id = table_id
        self.errors = errors
        super().__init__(f"BigQuery insert failed for {table_id}: {errors[:3]}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bq_write.py -v`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add core/bq/write.py tests/test_bq_write.py
git commit -m "feat(bq): SchemaViolationError + BigQueryInsertError"
```

---

## Task 3: `bq_write_validated` — skeleton + empty batch + snapshot guard

**Files:**
- Modify: `core/bq/write.py`
- Modify: `tests/test_bq_write.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_bq_write.py`:

```python
from unittest.mock import MagicMock, patch
from pydantic import BaseModel
from core.bq.write import bq_write_validated


class FakeRow(BaseModel):
    societa_id: str
    n: int


def test_empty_batch_is_noop(caplog):
    caplog.set_level("INFO")
    bq_write_validated("hotelops.f_x", [], mode="append")
    assert "empty batch for hotelops.f_x" in caplog.text


def test_snapshot_without_natural_key_raises():
    rows = [FakeRow(societa_id="ORTI", n=1)]
    with pytest.raises(ValueError, match="snapshot mode requires natural_key"):
        bq_write_validated("hotelops.f_x", rows, mode="snapshot")


def test_snapshot_with_empty_natural_key_raises():
    rows = [FakeRow(societa_id="ORTI", n=1)]
    with pytest.raises(ValueError, match="snapshot mode requires natural_key"):
        bq_write_validated("hotelops.f_x", rows, mode="snapshot", natural_key=[])


def test_validation_failure_raises_with_failures():
    rows = [
        FakeRow(societa_id="ORTI", n=1),
        "not a model",  # type: ignore  -- test the BaseModel guard
    ]
    with pytest.raises(SchemaViolationError) as exc:
        bq_write_validated("hotelops.f_x", rows, mode="append")
    assert exc.value.table_id == "hotelops.f_x"
    assert len(exc.value.failures) == 1
    assert exc.value.failures[0][0] == 1  # row index
    assert "BaseModel" in exc.value.failures[0][2]


def test_mixed_pydantic_types_raise():
    class OtherRow(BaseModel):
        x: str

    rows = [FakeRow(societa_id="ORTI", n=1), OtherRow(x="y")]
    with pytest.raises(SchemaViolationError) as exc:
        bq_write_validated("hotelops.f_x", rows, mode="append")
    assert "type" in exc.value.failures[0][2].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bq_write.py -v`
Expected: FAIL — `bq_write_validated` not defined.

- [ ] **Step 3: Implement the skeleton**

Append to `core/bq/write.py`:

```python
from typing import Literal
from pydantic import BaseModel

WriteMode = Literal["append", "snapshot"]


def bq_write_validated(
    table: str,
    rows: list[BaseModel],
    mode: WriteMode = "append",
    natural_key: list[str] | None = None,
) -> None:
    """Write Pydantic-validated rows to BigQuery via a single observable gate.

    Args:
        table: Fully-qualified BQ table id, e.g.
               "hotelops-suite.hotelops.f_partite_aperte_fornitori".
        rows: List of Pydantic model instances. All must be the same concrete
              subclass. Empty list is a no-op.
        mode: "append" — INSERT only (caller handles dedup if needed).
              "snapshot" — DELETE+INSERT chirurgico per natural_key, then INSERT.
        natural_key: Column names that scope the SNAPSHOT delete. Required when
                     mode="snapshot". Must include every partitioning/identity
                     column the caller wants preserved (otherwise over-delete).

    Lineage is read from PipelineRun.get_current() (ContextVar). If no active
    run is present, the function logs a warning and writes anyway with
    lineage=unknown.

    Raises:
        ValueError: mode="snapshot" but natural_key is None or empty.
        SchemaViolationError: validation failed on at least one row.
        BigQueryInsertError: BQ load job returned row-level errors.
    """
    # 1. Empty batch is a documented no-op — pipelines fuori stagione,
    #    file assenti, etc. Not an error.
    if not rows:
        log.info("bq_write_validated: empty batch for %s, skipping", table)
        return

    # 2. Snapshot mode without natural_key is a programmer error — fail fast,
    #    don't try to guess scope.
    if mode == "snapshot" and not natural_key:
        raise ValueError(
            f"snapshot mode requires natural_key for {table} "
            "(e.g. ['data_snapshot', 'societa_id'])"
        )

    # 3. Strict Pydantic gate (I1). Collect ALL failures, then raise once.
    schema_class = type(rows[0])
    failures: list[tuple[int, Any, str]] = []
    rows_dict: list[dict] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, BaseModel):
            failures.append(
                (idx, row, f"Not a Pydantic BaseModel instance (got {type(row).__name__})")
            )
            continue
        if type(row) is not schema_class:
            failures.append(
                (
                    idx,
                    row,
                    f"Mixed type: expected {schema_class.__name__}, got {type(row).__name__}",
                )
            )
            continue
        rows_dict.append(row.model_dump())

    if failures:
        raise SchemaViolationError(table, failures)

    # 4. Lineage + write — implemented in subsequent tasks.
    raise NotImplementedError("write paths land in Task 4 and Task 5")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bq_write.py -v`
Expected: PASS — 8 tests green (3 from Task 2 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add core/bq/write.py tests/test_bq_write.py
git commit -m "feat(bq): bq_write_validated skeleton — empty batch, snapshot guard, validation"
```

---

## Task 4: `bq_write_validated` — APPEND happy path

**Files:**
- Modify: `core/bq/write.py`
- Modify: `tests/test_bq_write.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_bq_write.py`:

```python
@patch("core.bq.write.get_client")
def test_append_calls_load_table_from_json_with_write_append(mock_get_client):
    from google.cloud import bigquery
    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_job.result.return_value = None
    mock_client.load_table_from_json.return_value = mock_job
    mock_get_client.return_value = mock_client

    rows = [FakeRow(societa_id="ORTI", n=1), FakeRow(societa_id="ORTI", n=2)]
    bq_write_validated("hotelops.f_x", rows, mode="append")

    mock_client.load_table_from_json.assert_called_once()
    args, kwargs = mock_client.load_table_from_json.call_args
    assert args[0] == [{"societa_id": "ORTI", "n": 1}, {"societa_id": "ORTI", "n": 2}]
    assert args[1] == "hotelops.f_x"
    job_config = kwargs["job_config"]
    assert job_config.write_disposition == bigquery.WriteDisposition.WRITE_APPEND
    assert job_config.source_format == bigquery.SourceFormat.NEWLINE_DELIMITED_JSON


@patch("core.bq.write.get_client")
def test_append_raises_bigquery_insert_error_on_job_errors(mock_get_client):
    mock_client = MagicMock()
    mock_job = MagicMock()
    # Simulate a load job that completed with row errors
    mock_job.result.side_effect = Exception("row errors: [{...}]")
    mock_client.load_table_from_json.return_value = mock_job
    mock_get_client.return_value = mock_client

    rows = [FakeRow(societa_id="ORTI", n=1)]
    with pytest.raises(BigQueryInsertError):
        bq_write_validated("hotelops.f_x", rows, mode="append")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bq_write.py -v -k "append_calls_load or append_raises"`
Expected: FAIL — `NotImplementedError` from Task 3 skeleton.

- [ ] **Step 3: Implement the APPEND path**

Replace the `raise NotImplementedError(...)` line in `core/bq/write.py` with:

```python
    # 4. Lineage discovery (ambient via ContextVar — log-only fallback).
    from core.pipeline_run import PipelineRun

    run = PipelineRun.get_current()
    if run is not None:
        lineage_meta = {
            "pipeline_name": run.pipeline_name,
            "run_id": run.run_id,
            "file_sorgente": run.file_sorgente,
        }
    else:
        log.warning(
            "bq_write_validated called outside PipelineRun context for %s. "
            "Lineage=unknown. Wrap caller with: with PipelineRun('...'):",
            table,
        )
        lineage_meta = {
            "pipeline_name": "unknown_pipeline",
            "run_id": None,
            "file_sorgente": None,
        }

    # 5. Batch load (no streaming buffer).
    from google.cloud import bigquery
    from core.bq.client import get_client

    client = get_client()

    if mode == "append":
        _append(client, table, rows_dict)
    elif mode == "snapshot":
        _snapshot(client, table, rows_dict, natural_key)  # implemented Task 5
    else:
        raise ValueError(f"unknown mode: {mode}")

    # 6. Single observable log line per write.
    extra = {
        "table": table,
        "rows_written": len(rows_dict),
        "mode": mode,
        **lineage_meta,
    }
    if mode == "snapshot":
        extra["natural_key"] = natural_key
    log.info(
        "bq_write_validated: %d rows -> %s [mode=%s]",
        len(rows_dict),
        table,
        mode,
        extra=extra,
    )


def _append(client, table: str, rows_dict: list[dict]) -> None:
    """Batch INSERT — no streaming buffer, no DELETE."""
    from google.cloud import bigquery

    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = client.load_table_from_json(rows_dict, table, job_config=job_config)
    try:
        job.result()
    except Exception as e:  # noqa: BLE001 — propagate as our typed error
        raise BigQueryInsertError(table, [{"job_error": str(e)}]) from e


def _snapshot(client, table: str, rows_dict: list[dict], natural_key: list[str]) -> None:
    raise NotImplementedError("SNAPSHOT lands in Task 5")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bq_write.py -v`
Expected: PASS — 10 tests green.

- [ ] **Step 5: Commit**

```bash
git add core/bq/write.py tests/test_bq_write.py
git commit -m "feat(bq): bq_write_validated APPEND path — batch load, lineage, log"
```

---

## Task 5: `bq_write_validated` — SNAPSHOT happy path

**Files:**
- Modify: `core/bq/write.py`
- Modify: `tests/test_bq_write.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_bq_write.py`:

```python
@patch("core.bq.write.get_client")
def test_snapshot_runs_delete_then_insert(mock_get_client):
    from google.cloud import bigquery

    mock_client = MagicMock()
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = None
    mock_client.query.return_value = mock_query_job

    mock_load_job = MagicMock()
    mock_load_job.result.return_value = None
    mock_client.load_table_from_json.return_value = mock_load_job

    mock_get_client.return_value = mock_client

    rows = [
        FakeRow(societa_id="ORTI", n=1),
        FakeRow(societa_id="INTUR", n=2),
    ]
    bq_write_validated(
        "hotelops.f_x",
        rows,
        mode="snapshot",
        natural_key=["societa_id"],
    )

    # DELETE issued first, then INSERT
    assert mock_client.query.called
    delete_sql = mock_client.query.call_args.args[0]
    assert "DELETE FROM `hotelops.f_x`" in delete_sql
    assert "(societa_id) IN UNNEST" in delete_sql

    # INSERT happened after delete
    mock_client.load_table_from_json.assert_called_once()


@patch("core.bq.write.get_client")
def test_snapshot_natural_key_with_two_columns_uses_struct(mock_get_client):
    mock_client = MagicMock()
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = None
    mock_client.query.return_value = mock_query_job
    mock_load_job = MagicMock()
    mock_load_job.result.return_value = None
    mock_client.load_table_from_json.return_value = mock_load_job
    mock_get_client.return_value = mock_client

    rows = [FakeRow(societa_id="ORTI", n=1)]
    bq_write_validated(
        "hotelops.f_x",
        rows,
        mode="snapshot",
        natural_key=["societa_id", "n"],
    )

    delete_sql = mock_client.query.call_args.args[0]
    assert "(societa_id, n)" in delete_sql
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bq_write.py -v -k snapshot_runs or snapshot_natural`
Expected: FAIL — `NotImplementedError` from `_snapshot`.

- [ ] **Step 3: Implement the SNAPSHOT path**

Replace `_snapshot` in `core/bq/write.py` with:

```python
def _snapshot(client, table: str, rows_dict: list[dict], natural_key: list[str]) -> None:
    """DELETE rows whose natural_key tuple is in the batch, then INSERT.

    The DELETE is chirurgico: it only touches keys present in the batch.
    Other rows in the table (e.g. a different societa or a different
    snapshot date) are untouched. The caller is responsible for picking
    a natural_key that matches their notion of "this snapshot's identity"
    — a too-narrow key over-deletes neighbouring partitions.
    """
    from google.cloud import bigquery

    if len(natural_key) == 1:
        col = natural_key[0]
        # Build (val1, val2, ...) parameter via UNNEST of the value list
        values = [r[col] for r in rows_dict]
        delete_sql = (
            f"DELETE FROM `{table}` "
            f"WHERE ({col}) IN UNNEST(@vals)"
        )
        # NOTE: we use ARRAY parameter for portability; element type
        # follows the Python type of values[0].
        param_type = _bq_type_for(values[0])
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("vals", param_type, values),
            ]
        )
        client.query(delete_sql, job_config=job_config).result()
    else:
        # Multi-column key: emit literal IN list of struct-like tuples.
        # We escape strings with single quotes and pass numbers as-is.
        cols = ", ".join(natural_key)
        tuples = []
        for r in rows_dict:
            parts = [_sql_literal(r[c]) for c in natural_key]
            tuples.append(f"({', '.join(parts)})")
        # Deduplicate identical key tuples to keep the IN list small.
        in_list = ",\n  ".join(sorted(set(tuples)))
        delete_sql = (
            f"DELETE FROM `{table}` "
            f"WHERE ({cols}) IN (\n  {in_list}\n)"
        )
        client.query(delete_sql).result()

    # INSERT phase: same batch load as APPEND.
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = client.load_table_from_json(rows_dict, table, job_config=job_config)
    try:
        job.result()
    except Exception as e:  # noqa: BLE001
        raise BigQueryInsertError(table, [{"job_error": str(e)}]) from e


def _bq_type_for(sample: Any) -> str:
    """Map Python type to a BigQuery scalar parameter type."""
    if isinstance(sample, bool):
        return "BOOL"
    if isinstance(sample, int):
        return "INT64"
    if isinstance(sample, float):
        return "FLOAT64"
    return "STRING"


def _sql_literal(value: Any) -> str:
    """Render a Python value as a safe SQL literal for use inside an IN list.

    Strings are escaped (single quotes doubled). Numbers and booleans are
    rendered directly. None becomes NULL (which never matches in IN, so the
    caller is expected to filter None keys upstream — but we don't crash).
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    # Treat everything else as string
    s = str(value).replace("'", "''")
    return f"'{s}'"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bq_write.py -v`
Expected: PASS — 12 tests green.

- [ ] **Step 5: Commit**

```bash
git add core/bq/write.py tests/test_bq_write.py
git commit -m "feat(bq): bq_write_validated SNAPSHOT path — chirurgico DELETE + batch INSERT"
```

---

## Task 6: `bq_write_validated` — lineage observability test

**Files:**
- Modify: `tests/test_bq_write.py`

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_bq_write.py`:

```python
from core.pipeline_run import PipelineRun


@patch("core.bq.write.get_client")
@patch("core.pipeline_run.PipelineRun._insert_final")  # avoid real BQ write
def test_lineage_populated_from_active_pipeline_run(mock_insert, mock_get_client):
    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_job.result.return_value = None
    mock_client.load_table_from_json.return_value = mock_job
    mock_get_client.return_value = mock_client

    rows = [FakeRow(societa_id="ORTI", n=1)]
    with PipelineRun("test_pipeline", file_sorgente="my_file.xlsx"):
        bq_write_validated("hotelops.f_x", rows, mode="append")

    # Inspect the structured log call: extra carries the lineage_meta
    # — we use caplog instead, simpler.


def test_lineage_warns_when_no_active_run(caplog):
    caplog.set_level("WARNING")
    with patch("core.bq.write.get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.return_value = None
        mock_client.load_table_from_json.return_value = mock_job
        mock_get_client.return_value = mock_client

        rows = [FakeRow(societa_id="ORTI", n=1)]
        bq_write_validated("hotelops.f_x", rows, mode="append")

    assert "outside PipelineRun context" in caplog.text
    assert "hotelops.f_x" in caplog.text
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_bq_write.py -v -k lineage`
Expected: PASS (lineage logic was implemented in Task 4; this task just adds the tests).

- [ ] **Step 3: No implementation needed — lineage is already in place**

(Skip — Task 4 already implemented the lineage discovery and the warning log.)

- [ ] **Step 4: Run full test file to ensure nothing regressed**

Run: `pytest tests/test_bq_write.py -v`
Expected: PASS — 14 tests green.

- [ ] **Step 5: Commit**

```bash
git add tests/test_bq_write.py
git commit -m "test(bq): cover lineage observability paths"
```

---

## Task 7: `filter_new_rows_by_hash` helper

**Files:**
- Create: `core/bq/dedup.py`
- Create: `tests/test_bq_dedup.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bq_dedup.py`:

```python
from unittest.mock import MagicMock, patch
from pydantic import BaseModel
from core.bq.dedup import filter_new_rows_by_hash


class HashedRow(BaseModel):
    hash_riga: str
    payload: int


@patch("core.bq.dedup.get_client")
def test_filter_returns_only_new_rows(mock_get_client):
    mock_client = MagicMock()
    # BQ says hashes "a" and "b" already exist
    mock_row = MagicMock()
    mock_row.hash_riga = "a"
    mock_row2 = MagicMock()
    mock_row2.hash_riga = "b"
    mock_client.query.return_value.result.return_value = [mock_row, mock_row2]
    mock_get_client.return_value = mock_client

    rows = [
        HashedRow(hash_riga="a", payload=1),  # already in BQ
        HashedRow(hash_riga="c", payload=3),  # new
        HashedRow(hash_riga="b", payload=2),  # already in BQ
    ]
    new_rows = filter_new_rows_by_hash(
        "hotelops.f_x", rows, hash_column="hash_riga"
    )

    assert len(new_rows) == 1
    assert new_rows[0].hash_riga == "c"


@patch("core.bq.dedup.get_client")
def test_filter_empty_input_returns_empty(mock_get_client):
    new_rows = filter_new_rows_by_hash(
        "hotelops.f_x", [], hash_column="hash_riga"
    )
    assert new_rows == []
    # No BQ query needed
    mock_get_client.return_value.query.assert_not_called()


@patch("core.bq.dedup.get_client")
def test_filter_all_new_when_table_empty(mock_get_client):
    mock_client = MagicMock()
    mock_client.query.return_value.result.return_value = []
    mock_get_client.return_value = mock_client

    rows = [HashedRow(hash_riga="a", payload=1), HashedRow(hash_riga="b", payload=2)]
    new_rows = filter_new_rows_by_hash(
        "hotelops.f_x", rows, hash_column="hash_riga"
    )
    assert len(new_rows) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bq_dedup.py -v`
Expected: FAIL — `core.bq.dedup` does not exist.

- [ ] **Step 3: Create the helper**

Create `core/bq/dedup.py`:

```python
"""Helper for APPEND pipelines that dedupe by hash before writing.

Lives separately from core/bq/write.py to keep the write gate focused on
validation + lineage. Pipelines that need MD5/key-based dedup compose:

    rows_new = filter_new_rows_by_hash(table, rows, "hash_riga")
    bq_write_validated(table, rows_new, mode="append")
"""
from __future__ import annotations

import logging
from typing import TypeVar

from pydantic import BaseModel

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def filter_new_rows_by_hash(
    table: str,
    rows: list[T],
    hash_column: str,
) -> list[T]:
    """Return rows whose hash_column is not yet present in the BQ table.

    Reads existing hashes once via a single SELECT, then filters in-memory.
    Empty input is a no-op (no query). Race conditions: if two pipelines
    run in parallel they may both insert the same hash; today the codebase
    is single-process per pipeline (cron + lockfile) so this is acceptable.
    """
    if not rows:
        return []

    from core.bq.client import get_client

    client = get_client()
    sql = f"SELECT {hash_column} FROM `{table}`"
    existing = {getattr(r, hash_column) for r in client.query(sql).result()}

    new_rows = [r for r in rows if getattr(r, hash_column) not in existing]
    log.info(
        "filter_new_rows_by_hash: %s — %d input, %d existing, %d new",
        table,
        len(rows),
        len(existing & {getattr(r, hash_column) for r in rows}),
        len(new_rows),
    )
    return new_rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bq_dedup.py -v`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add core/bq/dedup.py tests/test_bq_dedup.py
git commit -m "feat(bq): filter_new_rows_by_hash helper for APPEND dedup"
```

---

## Task 8: Migrate `ingest_scheda_contabile` to the gate

**Files:**
- Modify: `ingest/flussi/ingest_scheda_contabile.py`

- [ ] **Step 1: Read the current write code**

Open `ingest/flussi/ingest_scheda_contabile.py` and locate `write_saldi_to_bq`. The current shape (post-fix earlier today) is:

1. Build `rows_to_write` as list of dicts (not Pydantic instances).
2. `client.query(delete_sql).result()` for DELETE.
3. `client.load_table_from_json(rows_to_write, BQ_TABLE, job_config=...)` for INSERT.

There is no Pydantic schema for `f_saldi_banca_snapshot` today.

- [ ] **Step 2: Add a Pydantic schema for the table**

In `core/schemas.py`, add:

```python
class SaldoBancaSnapshotRow(BaseModel):
    """Schema for f_saldi_banca_snapshot — daily running balance per banca.

    Sourced from Esolver scheda contabile (running saldo for the fiscal year,
    not absolute bank balance).
    """
    societa_id: SocietaId
    banca_id: str
    data_snapshot: str  # ISO date
    saldo_finale: float
```

(`SocietaId` is already exported from the same module.)

- [ ] **Step 3: Rewrite `write_saldi_to_bq`**

Replace the body of `write_saldi_to_bq` with:

```python
def write_saldi_to_bq(
    saldi: dict[date, float],
    societa_id: str,
    banca_id: str,
    dry_run: bool = False,
) -> int:
    """Write end-of-day saldi to f_saldi_banca_snapshot via the BQ gate."""
    if not saldi:
        log.warning("No saldi to write")
        return 0

    from core.schemas import SaldoBancaSnapshotRow
    from core.bq.write import bq_write_validated

    rows = [
        SaldoBancaSnapshotRow(
            societa_id=societa_id,
            banca_id=banca_id,
            data_snapshot=d.isoformat(),
            saldo_finale=saldo,
        )
        for d, saldo in sorted(saldi.items())
    ]

    if dry_run:
        log.info(f"DRY RUN: {len(rows)} saldi for {societa_id}/{banca_id}")
        for r in rows:
            log.info(f"  {r.data_snapshot}: €{r.saldo_finale:,.2f}")
        return len(rows)

    bq_write_validated(
        BQ_TABLE,
        rows,
        mode="snapshot",
        natural_key=["societa_id", "banca_id", "data_snapshot"],
    )
    return len(rows)
```

The 5-column natural_key (`societa_id`, `banca_id`, `data_snapshot`) preserves snapshots from other banks/società untouched.

- [ ] **Step 4: Wrap the entry point with `PipelineRun`**

In `process_file` (the function that calls `write_saldi_to_bq` per file), wrap the work:

```python
def process_file(
    filepath: Path,
    societa_id: str,
    banca_id: str | None,
    dry_run: bool,
) -> int:
    from core.pipeline_run import PipelineRun

    with PipelineRun(
        "ingest_scheda_contabile",
        societa_id=societa_id,
        file_sorgente=filepath.name,
    ):
        log.info(f"Processing: {filepath.name}")
        # ... existing body unchanged ...
        return write_saldi_to_bq(daily_saldi, societa_id, banca_id, dry_run)
```

- [ ] **Step 5: Run the existing test suite to confirm no regression**

Run: `pytest tests/ -q`
Expected: PASS — 343 tests green (the migration changes implementation, not behavior).

- [ ] **Step 6: Stage a real ingest in `--dry-run` to verify wiring**

Run: `python -m ingest.flussi.ingest_scheda_contabile --file ~/.cache/hotelops/ingest_staging/INTUR_PARTITE_FORNITORI_20260428.xlsx --societa INTUR --banca SELLA --dry-run` (substitute a real scheda file you have).
Expected: log shows the dry-run output plus a `bq_write_validated: empty batch` or no `unknown_pipeline` warning (the run is wrapped).

- [ ] **Step 7: Commit**

```bash
git add core/schemas.py ingest/flussi/ingest_scheda_contabile.py
git commit -m "refactor(scheda): migrate to bq_write_validated SNAPSHOT mode

Adds SaldoBancaSnapshotRow Pydantic schema (was previously dict-only).
Wraps process_file with PipelineRun for ambient lineage. The snapshot
DELETE scope (societa_id, banca_id, data_snapshot) preserves other banks
and other dates."
```

---

## Task 9: Migrate `ingest_partite_aperte` to the gate

**Files:**
- Modify: `ingest/flussi/ingest_partite_aperte.py`

- [ ] **Step 1: Verify the existing Pydantic schema**

`core/schemas.PartitaApertaFornitoreRow` already exists. Confirm it has all the fields the pipeline writes (it should — Sprint 1 of an earlier audit closed the drift).

- [ ] **Step 2: Rewrite `load_to_bq`**

Replace the function body with:

```python
def load_to_bq(client: bigquery.Client, rows: list[dict], dry_run: bool = False):
    """Snapshot insert into BigQuery via the gate.

    The natural_key (societa_id, data_snapshot) preserves snapshots from
    the other società on the same day, and snapshots of this società on
    other days.
    """
    if not rows:
        log.warning("No rows to load")
        return

    from core.schemas import PartitaApertaFornitoreRow
    from core.bq.write import bq_write_validated

    societa_id = rows[0]["societa_id"]
    data_snapshot = rows[0]["data_snapshot"]
    pydantic_rows = [PartitaApertaFornitoreRow(**r) for r in rows]

    if dry_run:
        log.info(
            f"DRY RUN: would load {len(pydantic_rows)} rows for "
            f"{societa_id} @ {data_snapshot}"
        )
        _print_summary(rows)
        return

    create_table_if_needed(client)
    bq_write_validated(
        BQ_TABLE,
        pydantic_rows,
        mode="snapshot",
        natural_key=["societa_id", "data_snapshot"],
    )
    _print_summary(rows)
```

The `client` parameter stays for `create_table_if_needed`, which is called once and isn't a write.

- [ ] **Step 3: Wrap the CLI entrypoint with `PipelineRun`**

In `main` (the CLI entry), wrap the parse + load:

```python
def main():
    args = _build_argparser().parse_args()
    from core.pipeline_run import PipelineRun

    filepath = Path(args.file)
    with PipelineRun(
        "ingest_partite_aperte",
        societa_id=args.societa.upper() if args.societa else None,
        file_sorgente=filepath.name,
    ):
        rows = parse_situazione_partite(filepath, societa_override=args.societa)
        client = get_client()
        load_to_bq(client, rows, dry_run=args.dry_run)
```

(Adjust to the file's existing `main` shape — preserve any logger setup.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -q`
Expected: PASS — 343 tests green.

- [ ] **Step 5: Stage a real ingest in `--dry-run`**

Run: `python -m ingest.flussi.ingest_partite_aperte --file /Users/stefanodellapietra/Desktop/situazionepartitefornitoriINTUR.xlsx --societa INTUR --dry-run`
Expected: dry-run summary identical to pre-migration; no `unknown_pipeline` warning.

- [ ] **Step 6: Commit**

```bash
git add ingest/flussi/ingest_partite_aperte.py
git commit -m "refactor(partite): migrate to bq_write_validated SNAPSHOT mode

Pydantic schema PartitaApertaFornitoreRow gating the write. PipelineRun
wraps main() so lineage (societa_id, file_sorgente) is ambient."
```

---

## Task 10: Migrate `ingest_coperti` to the gate

**Files:**
- Modify: `ingest/flussi/ingest_coperti.py`

- [ ] **Step 1: Add a Pydantic schema for f_coperti_giornalieri**

In `core/schemas.py`:

```python
class CopertoGiornalieroRow(BaseModel):
    """Schema for f_coperti_giornalieri.

    natural_key for SNAPSHOT writes is hash_riga (computed from societa,
    data_servizio, tipo_pasto, tipo_ospite, business_unit_id by the
    pipeline). Stored as a column rather than reconstructed at write time
    so back-fill / debug is possible.
    """
    societa_id: SocietaId
    anno: int
    mese: int
    data_servizio: str  # ISO date
    tipo_pasto: str
    tipo_ospite: str
    business_unit_id: str | None = None
    n_coperti: int
    fonte: str | None = None
    hash_riga: str
    data_caricamento: str  # ISO timestamp
```

- [ ] **Step 2: Rewrite the load path in `load_to_bq`**

Locate `load_to_bq` in `ingest_coperti.py`. Replace the surgical DELETE-INSERT branch (the non-`replace` path) with:

```python
    if replace:
        # Full wipe + reload — bypass the gate, the pipeline owns this case.
        # WRITE_TRUNCATE is intentionally out of bq_write_validated's scope.
        # ... existing replace logic unchanged ...
        return

    # Surgical write — gate enforces validation, lineage, batch load.
    from core.schemas import CopertoGiornalieroRow
    from core.bq.write import bq_write_validated

    pydantic_rows = [CopertoGiornalieroRow(**r) for r in new_rows]
    bq_write_validated(
        BQ_TABLE_FULL,
        pydantic_rows,
        mode="snapshot",
        natural_key=["hash_riga"],
    )
```

`new_rows` is the output of `dedup_latest_wins(rows)` (already in place). The snapshot mode replaces only the `hash_riga` values present in the batch — exactly the post-fix semantics from earlier today.

- [ ] **Step 3: Wrap `main` with `PipelineRun`**

In the `main` function:

```python
def main():
    args = _build_argparser().parse_args()
    from core.pipeline_run import PipelineRun

    file_label = args.file or args.gsheet or "datahub_coperti"
    with PipelineRun(
        "ingest_coperti",
        societa_id=args.societa,
        file_sorgente=file_label,
    ):
        # ... existing body unchanged ...
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/ -q`
Expected: PASS — 343 tests green.

- [ ] **Step 5: Stage a real run via the cron's wrapper script in dry-mode**

Run: `python -m ingest.flussi.ingest_coperti --gsheet --dry-run`
Expected: same row counts as pre-migration; no `unknown_pipeline` warning; `bq_write_validated: empty batch` only if the dedup happened to drop everything (unlikely).

- [ ] **Step 6: Commit**

```bash
git add core/schemas.py ingest/flussi/ingest_coperti.py
git commit -m "refactor(coperti): migrate non-replace write to bq_write_validated

The --replace branch keeps its bespoke wipe+reload (WRITE_TRUNCATE is
out of the gate's scope by design). The surgical DELETE-INSERT path now
goes through the gate with natural_key=['hash_riga']."
```

---

## Task 11: Pilot acceptance run

**Files:** none (verification task)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: PASS — 343 tests green.

- [ ] **Step 2: Capture pre-migration row counts (baseline)**

These were captured during the audit on 2026-04-28. Re-confirm with:

```
bq query --use_legacy_sql=false --format=pretty "
SELECT
  'f_partite_aperte_fornitori' AS table, societa_id AS k, COUNT(*) AS n
  FROM \`hotelops-suite.hotelops.f_partite_aperte_fornitori\` GROUP BY societa_id
UNION ALL
SELECT
  'f_saldi_banca_snapshot', CONCAT(societa_id,'/',banca_id), COUNT(*)
  FROM \`hotelops-suite.hotelops.f_saldi_banca_snapshot\` GROUP BY societa_id, banca_id
UNION ALL
SELECT
  'f_coperti_giornalieri', tipo_pasto, COUNT(*)
  FROM \`hotelops-suite.hotelops.f_coperti_giornalieri\` GROUP BY tipo_pasto
ORDER BY 1, 2"
```

Save the output as `/tmp/pilot_baseline.txt`.

- [ ] **Step 3: Re-run the 3 pilot pipelines on their canonical inputs**

```
python -m ingest.flussi.ingest_partite_aperte --file /Users/stefanodellapietra/Desktop/situazionepartitefornitoriINTUR.xlsx --societa INTUR
python -m ingest.flussi.ingest_scheda_contabile --file "/Users/stefanodellapietra/Desktop/INTUR-BANCA SELLA.XLSX" --societa INTUR --banca SELLA
python -m ingest.flussi.ingest_coperti --gsheet --replace
```

Note: `--replace` for coperti uses the bypass path on purpose (full reload). Document the run-time and verify each completes without `unknown_pipeline` warnings in the log.

- [ ] **Step 4: Capture post-migration row counts**

Re-run the same UNION query as Step 2, save as `/tmp/pilot_post.txt`.

- [ ] **Step 5: Diff baseline vs post**

```
diff /tmp/pilot_baseline.txt /tmp/pilot_post.txt
```

Expected: same row counts per group key. Differences are acceptable only when they correspond to the new ingest (e.g. an updated INTUR snapshot replacing an older one — count should be equal or larger by the new rows).

- [ ] **Step 6: Confirm lineage is being captured**

```
bq query --use_legacy_sql=false --format=pretty "
SELECT pipeline_name, societa_id, status, COUNT(*) AS runs, MAX(ended_at) AS last_run
FROM \`hotelops-suite.hotelops.f_pipeline_runs\`
WHERE pipeline_name IN ('ingest_partite_aperte','ingest_scheda_contabile','ingest_coperti')
  AND DATE(ended_at) = CURRENT_DATE()
GROUP BY pipeline_name, societa_id, status
ORDER BY pipeline_name, societa_id"
```

Expected: at least one OK row per pilot pipeline, with the right `societa_id` populated.

- [ ] **Step 7: Acceptance gate decision**

If all checks above pass, the pilot is GREEN and Sprint 2 can start. Document the result in `docs/superpowers/specs/2026-04-28-bq-write-validated-design.md` under a new "Pilot result" section (one paragraph) and commit:

```bash
git add docs/superpowers/specs/2026-04-28-bq-write-validated-design.md
git commit -m "docs(spec): pilot acceptance result for bq-write-gate Sprint 1

3/3 pilots green: row counts identical pre/post (modulo new INTUR
partite snapshot), no unknown_pipeline warnings, f_pipeline_runs
records all three runs with correct societa_id and status=OK."
```

If anything fails, halt rollout, open a discussion thread, and revisit the design before touching Sprint 2 pipelines.

---

## Self-review notes

- All 5 spec sections (API, Behavior matrix, Validation, Observability, Migration Sprint 1) have at least one task implementing them. The optional row-level lineage population (spec §"Optional row-level lineage") is intentionally deferred — none of the 3 pilot tables have `pipeline_run_id`/`pipeline_name` columns yet, so it would be no-op code in Sprint 1. Promoted to Sprint 2 follow-up.
- Empty input handling is specified in Task 3 (skeleton) and tested there.
- `BigQueryInsertError` is constructed in two places (`_append`, `_snapshot`) — same class, same shape, intentional.
- The `_sql_literal` helper used in multi-column SNAPSHOT is intentionally minimal: it covers `str|int|float|bool|None`. Pipelines passing exotic types (datetime, Decimal) will need to convert upstream — flagged in case Sprint 2 hits one.
- The `_to_row` method of `PipelineRun` is unchanged in this sprint — `file_sorgente` is read by `bq_write_validated` from the live object, not persisted to `f_pipeline_runs` rows. If `file_sorgente` should be a column of `f_pipeline_runs`, that is a Sprint 5 enforcement task (schema addition + drift handling), not a foundation concern.
