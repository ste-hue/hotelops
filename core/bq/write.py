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
