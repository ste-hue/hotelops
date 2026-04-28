"""Centralized BigQuery write gate (I1).

Every BigQuery write from a hotelops pipeline goes through bq_write_validated.
The function provides Pydantic validation, batch loads (no streaming buffer),
ambient lineage from PipelineRun, and a single observable log line per write.

See: docs/superpowers/specs/2026-04-28-bq-write-validated-design.md
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel

# Module-level so tests can @patch("core.bq.write.get_client").
# core.bq.client is a leaf module (no cycle risk).
from core.bq.client import get_client

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
                (
                    idx,
                    row,
                    f"Not a Pydantic BaseModel instance (got {type(row).__name__})",
                )
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


def _snapshot(
    client, table: str, rows_dict: list[dict], natural_key: list[str]
) -> None:
    """DELETE rows whose natural_key tuple is in the batch, then INSERT.

    The DELETE is chirurgico: it only touches keys present in the batch.
    Other rows in the table (e.g. a different societa or a different
    snapshot date) are untouched. The caller is responsible for picking
    a natural_key that matches their notion of "this snapshot's identity"
    — a too-narrow key over-deletes neighbouring partitions.

    If ``rows_dict`` contains two rows with the same ``natural_key`` tuple,
    both are inserted and the DELETE phase removes only the prior snapshot's
    matching tuple — the duplicate goes through. Treated as caller error:
    natural_key is by definition unique within a batch.
    """
    from google.cloud import bigquery

    if len(natural_key) == 1:
        col = natural_key[0]
        # Build (val1, val2, ...) parameter via UNNEST of the value list
        values = [r[col] for r in rows_dict]
        delete_sql = f"DELETE FROM `{table}` WHERE ({col}) IN UNNEST(@vals)"
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
        delete_sql = f"DELETE FROM `{table}` WHERE ({cols}) IN (\n  {in_list}\n)"
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
    # FIXME: extend to date/datetime/Decimal when migrating non-string-keyed
    # pipelines (e.g. ingest_movimenti_contabili has datetime fields).
    return "STRING"


def _sql_literal(value: Any) -> str:
    """Render a Python value as a safe SQL literal for use inside an IN list.

    Strings are escaped (single quotes doubled). Numbers and booleans are
    rendered directly. None becomes NULL. **WARNING:** in BigQuery,
    ``NULL IN (... NULL ...)`` evaluates to NULL (not TRUE), so a row whose
    natural_key tuple contains NULL will silently *not* be deleted by the
    DELETE phase, then be re-inserted by the INSERT phase — producing a
    duplicate. The caller MUST coalesce nullable natural_key columns to a
    sentinel value upstream (e.g. ``''`` or ``'N/A'``) before calling the
    gate. Backslashes are not escaped — values containing ``\\n``, ``\\t``,
    ``\\\\`` etc. will be re-interpreted by BigQuery's lexer; for natural
    keys that may contain backslashes (none today, but flag for future
    migrations) the helper must be hardened.
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
