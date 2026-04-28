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
