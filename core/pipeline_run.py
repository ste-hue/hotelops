"""Pipeline run tracking — observability Layer 2.

Records one row per pipeline execution in f_pipeline_runs. Complementary
to f_apify_runs: the latter tracks per-actor-call cost, this one tracks
per-invocation lifecycle (started, ended, status, totals).

Usage:
    with PipelineRun("reviews_scrape") as run:
        run.rows_found = 42
        run.rows_new = 3
        run.alerts_sent = 1
        run.usage_total_usd = 0.12
        run.meta = {"watermarks": {...}}
        # status auto-set to OK on clean exit, FAIL on exception.

Design principles:
    - Never raise on BQ failure. Observability must not break the pipeline.
    - Single INSERT on __exit__ with the final state (OK / FAIL / PARTIAL).
      An earlier version INSERTed RUNNING on __enter__ and UPDATEd on __exit__,
      but the UPDATE always hit BigQuery's streaming buffer (the INSERT was
      seconds earlier) and orphaned every successful run as stuck-RUNNING.
      One write, no buffer collision — crashed processes are detected by
      `check_pipeline_staleness` (last OK > 36h for a 2x/day cron).

Plus two health-check functions used by `hotelops health`:
    - check_watermark_staleness  -- detects Type 2 (silent platform death)
    - check_pipeline_staleness   -- detects Type 1 (cron failed / process died)
"""

from __future__ import annotations

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from types import TracebackType
from typing import Optional

log = logging.getLogger(__name__)


STALENESS_THRESHOLD_DAYS = 21
PIPELINE_STALENESS_HOURS = 36

_current_run: ContextVar[Optional["PipelineRun"]] = ContextVar(
    "_current_run", default=None
)


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

    def _to_row(self) -> dict:
        return {
            "run_id": self.run_id,
            "pipeline_name": self.pipeline_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "status": self.status,
            "societa_id": self.societa_id,
            "rows_found": self.rows_found,
            "rows_new": self.rows_new,
            "alerts_sent": self.alerts_sent,
            "usage_total_usd": self.usage_total_usd,
            "error_message": self.error_message,
            "meta_json": json.dumps(self.meta) if self.meta else None,
        }

    def _insert_final(self) -> None:
        """Insert the single terminal row. Best-effort — never raises."""
        try:
            from core.bq.client import get_client
            from core.config import F_PIPELINE_RUNS

            client = get_client()
            errors = client.insert_rows_json(F_PIPELINE_RUNS, [self._to_row()])
            if errors:
                log.warning("f_pipeline_runs INSERT errors: %s", errors)
        except Exception:
            log.exception("PipelineRun._insert_final failed (non-fatal)")


# ── Health checks ────────────────────────────────────────────────────────────


def check_watermark_staleness(
    threshold_days: int = STALENESS_THRESHOLD_DAYS,
) -> list[dict]:
    """Check if any (piattaforma, bu) watermark is older than threshold.

    Catches the "Type 2" failure mode: everything runs OK but a platform
    silently stops returning data (e.g. Google gap of 5+ weeks pre-2026-04-09).

    Returns a list of stale entries:
        [{"piattaforma": str, "business_unit_id": str,
          "watermark": str, "days_stale": int}]
    """
    from core.bq.client import get_client
    from core.config import F_REVIEWS
    from google.cloud import bigquery

    client = get_client()
    sql = f"""
    SELECT
        piattaforma,
        business_unit_id,
        MAX(data_review) AS watermark,
        DATE_DIFF(CURRENT_DATE(), PARSE_DATE('%Y-%m-%d', MAX(data_review)), DAY) AS days_stale
    FROM `{F_REVIEWS}`
    WHERE LENGTH(data_review) = 10
    GROUP BY piattaforma, business_unit_id
    HAVING days_stale > @threshold
    ORDER BY days_stale DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("threshold", "INT64", threshold_days),
        ]
    )
    return [dict(r) for r in client.query(sql, job_config=job_config).result()]


def check_pipeline_staleness(
    threshold_hours: int = PIPELINE_STALENESS_HOURS,
) -> list[dict]:
    """Check if any pipeline hasn't had a successful run in threshold_hours.

    Catches the "Type 1" failure mode: cron crashed, BQ was down, etc.

    Returns a list of stale pipelines:
        [{"pipeline_name": str, "last_ok": str, "hours_since": int}]
    """
    from core.bq.client import get_client
    from core.config import F_PIPELINE_RUNS
    from google.cloud import bigquery

    client = get_client()
    sql = f"""
    SELECT
        pipeline_name,
        MAX(ended_at) AS last_ok,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(ended_at), HOUR) AS hours_since
    FROM `{F_PIPELINE_RUNS}`
    WHERE status = 'OK'
    GROUP BY pipeline_name
    HAVING hours_since > @threshold
    ORDER BY hours_since DESC
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("threshold", "INT64", threshold_hours),
        ]
    )
    return [dict(r) for r in client.query(sql, job_config=job_config).result()]


# Freshness threshold for IMPEGNO snapshots (partite aperte are manual exports —
# monthly is normal, > 30 days is worth flagging).
IMPEGNO_STALENESS_DAYS = 30


def check_impegno_freshness() -> list[dict]:
    """Return freshness info for f_partite_aperte_fornitori per societa_id.

    These snapshots are the IMPEGNO dimension of v_previsione_cassa and
    cash_control: they represent committed but unpaid invoices. Stale data
    here means the scadenzario column in v_previsione_cassa reflects old
    payment obligations.

    Returns:
        [{"societa_id": str, "ultimo_snapshot": str, "giorni": int,
          "n_partite": int, "totale_eur": float}]
    A societa_id will not appear in the result list if it has no snapshot data.
    """
    from core.bq.client import get_client
    from core.config import F_PARTITE_APERTE_FORNITORI

    client = get_client()
    sql = f"""
    SELECT
        societa_id,
        MAX(data_snapshot)                                           AS ultimo_snapshot,
        DATE_DIFF(CURRENT_DATE('Europe/Rome'), MAX(data_snapshot), DAY) AS giorni,
        COUNT(*)                                                     AS n_partite,
        ROUND(SUM(importo_abs), 0)                                   AS totale_eur
    FROM `{F_PARTITE_APERTE_FORNITORI}`
    GROUP BY societa_id
    ORDER BY societa_id
    """
    return [dict(r) for r in client.query(sql).result()]
