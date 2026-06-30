"""BigQuery-backed pending alert flag state for reviews pipeline."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from google.cloud import bigquery

from core.bq.client import get_client
from core.config import F_PENDING_ALERT_FLAGS

log = logging.getLogger(__name__)


def _ensure_table(client: bigquery.Client) -> None:
    sql = f"""
    CREATE TABLE IF NOT EXISTS `{F_PENDING_ALERT_FLAGS}` (
        review_hash STRING NOT NULL,
        created_at TIMESTAMP NOT NULL,
        run_id STRING
    )
    """
    client.query(sql).result()


def read_pending_flags() -> list[str]:
    """Return distinct pending review hashes. Best-effort: never raises."""
    try:
        client = get_client()
        _ensure_table(client)
        sql = f"""
        SELECT DISTINCT review_hash
        FROM `{F_PENDING_ALERT_FLAGS}`
        WHERE review_hash IS NOT NULL
        ORDER BY review_hash
        """
        return [str(r["review_hash"]) for r in client.query(sql).result()]
    except Exception:
        log.exception("read_pending_flags failed (non-fatal)")
        return []


def append_pending_flags(review_hashes: list[str], run_id: str | None = None) -> int:
    """Append pending hashes to BQ state. Best-effort: never raises."""
    hashes = sorted({h for h in review_hashes if h})
    if not hashes:
        return 0
    try:
        client = get_client()
        _ensure_table(client)
        now = datetime.now(timezone.utc).isoformat()
        rows = [{"review_hash": h, "created_at": now, "run_id": run_id} for h in hashes]
        errors = client.insert_rows_json(F_PENDING_ALERT_FLAGS, rows)
        if errors:
            log.warning("append_pending_flags INSERT errors: %s", errors)
            return 0
        return len(rows)
    except Exception:
        log.exception("append_pending_flags failed (non-fatal)")
        return 0


def clear_pending_flags(review_hashes: list[str]) -> int:
    """Delete hashes from BQ pending-state table. Best-effort: never raises."""
    hashes = sorted({h for h in review_hashes if h})
    if not hashes:
        return 0
    try:
        client = get_client()
        _ensure_table(client)
        sql = f"""
        DELETE FROM `{F_PENDING_ALERT_FLAGS}`
        WHERE review_hash IN UNNEST(@hashes)
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("hashes", "STRING", hashes),
            ]
        )
        client.query(sql, job_config=job_config).result()
        return len(hashes)
    except Exception:
        log.exception("clear_pending_flags failed (non-fatal)")
        return 0
