"""Helper for APPEND pipelines that dedupe by hash before writing.

Lives separately from core/bq/write.py to keep the write gate focused on
validation + lineage. Pipelines that need MD5/key-based dedup compose:

    rows_new = filter_new_rows_by_hash(table, rows, "hash_riga")
    bq_write_validated(table, rows_new, mode="append")
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar, Union

from pydantic import BaseModel

# Module-level so tests can @patch("core.bq.dedup.get_client").
from core.bq.client import get_client

log = logging.getLogger(__name__)

T = TypeVar("T", bound=Union[BaseModel, dict])


def _hash_of(row: Any, col: str) -> Any:
    """Read hash_column from a row that may be a dict or a Pydantic model."""
    if isinstance(row, dict):
        return row[col]
    return getattr(row, col)


def filter_new_rows_by_hash(
    table: str,
    rows: list[T],
    hash_column: str,
) -> list[T]:
    """Return rows whose hash_column is not yet present in the BQ table.

    Accepts both ``list[dict]`` (pre-validation) and ``list[BaseModel]``
    (post-validation). The natural callsite is dict-in / dict-out, with the
    gate performing validation downstream — avoids paying Pydantic cost for
    rows that will be discarded as duplicates.

    Reads existing hashes once via a single SELECT, then filters in-memory.
    Empty input is a no-op (no query). Race conditions: if two pipelines
    run in parallel they may both insert the same hash; today the codebase
    is single-process per pipeline (cron + lockfile) so this is acceptable.
    """
    if not rows:
        return []

    client = get_client()
    sql = f"SELECT {hash_column} FROM `{table}`"
    existing = {getattr(r, hash_column) for r in client.query(sql).result()}

    new_rows = [r for r in rows if _hash_of(r, hash_column) not in existing]
    log.info(
        "filter_new_rows_by_hash: %s — %d input, %d existing in table, "
        "%d already-present, %d new",
        table,
        len(rows),
        len(existing),
        len(rows) - len(new_rows),
        len(new_rows),
    )
    return new_rows
