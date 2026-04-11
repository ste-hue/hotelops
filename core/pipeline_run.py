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
    - INSERT a RUNNING row on enter (so crashed runs stay visible).
    - UPDATE the row with final status/metrics on exit.
    - Streaming-buffer UPDATE failures are logged and swallowed — the
      crashed-run health check picks up any orphans.

Plus three health-check functions used by `hotelops health`:
    - check_watermark_staleness  -- detects Type 2 (silent platform death)
    - check_pipeline_staleness   -- detects Type 1 (cron failed)
    - check_crashed_runs         -- detects stuck RUNNING rows
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from types import TracebackType

log = logging.getLogger(__name__)


STALENESS_THRESHOLD_DAYS = 21
PIPELINE_STALENESS_HOURS = 36
CRASHED_RUN_HOURS = 1


class PipelineRun:
    """Context manager that records a pipeline run in f_pipeline_runs."""

    def __init__(self, pipeline_name: str, societa_id: str | None = None):
        self.run_id = str(uuid.uuid4())
        self.pipeline_name = pipeline_name
        self.societa_id = societa_id
        self.started_at: str | None = None
        self.ended_at: str | None = None
        self.status = "RUNNING"
        self.rows_found: int | None = None
        self.rows_new: int | None = None
        self.alerts_sent: int | None = None
        self.usage_total_usd: float | None = None
        self.error_message: str | None = None
        self.meta: dict | None = None

    def __enter__(self) -> "PipelineRun":
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._insert_running()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        self.ended_at = datetime.now(timezone.utc).isoformat()
        if exc_val is not None:
            self.status = "FAIL"
            self.error_message = str(exc_val)[:500]
        elif self.status == "RUNNING":
            self.status = "OK"
        self._update_final()
        return False  # don't suppress exceptions

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

    def _insert_running(self) -> None:
        """Insert initial RUNNING row. Best-effort — never raises."""
        try:
            from core.config import F_PIPELINE_RUNS, PROJECT
            from google.cloud import bigquery

            client = bigquery.Client(project=PROJECT)
            errors = client.insert_rows_json(F_PIPELINE_RUNS, [self._to_row()])
            if errors:
                log.warning("f_pipeline_runs INSERT errors: %s", errors)
        except Exception:
            log.exception("PipelineRun._insert_running failed (non-fatal)")

    def _update_final(self) -> None:
        """UPDATE the row with final status + metrics. Best-effort.

        The UPDATE typically hits the streaming buffer (same row was inserted
        seconds ago). We catch any BQ error, log it, and return — the
        crashed-run health check will flag any orphaned RUNNING rows.
        """
        try:
            from core.config import F_PIPELINE_RUNS, PROJECT
            from google.cloud import bigquery

            client = bigquery.Client(project=PROJECT)

            sql = f"""
            UPDATE `{F_PIPELINE_RUNS}`
            SET ended_at = @ended_at,
                status = @status,
                rows_found = @rows_found,
                rows_new = @rows_new,
                alerts_sent = @alerts_sent,
                usage_total_usd = @usage_total_usd,
                error_message = @error_message,
                meta_json = @meta_json
            WHERE run_id = @run_id
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("run_id", "STRING", self.run_id),
                    bigquery.ScalarQueryParameter("ended_at", "TIMESTAMP", self.ended_at),
                    bigquery.ScalarQueryParameter("status", "STRING", self.status),
                    bigquery.ScalarQueryParameter("rows_found", "INT64", self.rows_found),
                    bigquery.ScalarQueryParameter("rows_new", "INT64", self.rows_new),
                    bigquery.ScalarQueryParameter("alerts_sent", "INT64", self.alerts_sent),
                    bigquery.ScalarQueryParameter(
                        "usage_total_usd", "FLOAT64", self.usage_total_usd
                    ),
                    bigquery.ScalarQueryParameter(
                        "error_message", "STRING", self.error_message
                    ),
                    bigquery.ScalarQueryParameter(
                        "meta_json",
                        "STRING",
                        json.dumps(self.meta) if self.meta else None,
                    ),
                ]
            )
            client.query(sql, job_config=job_config).result()
        except Exception:
            # Streaming buffer + any transient BQ failure — log and move on.
            # Orphaned RUNNING rows are handled by check_crashed_runs().
            log.exception("PipelineRun._update_final failed (non-fatal)")


# ── Health checks ────────────────────────────────────────────────────────────


def check_watermark_staleness(threshold_days: int = STALENESS_THRESHOLD_DAYS) -> list[dict]:
    """Check if any (piattaforma, bu) watermark is older than threshold.

    Catches the "Type 2" failure mode: everything runs OK but a platform
    silently stops returning data (e.g. Google gap of 5+ weeks pre-2026-04-09).

    Returns a list of stale entries:
        [{"piattaforma": str, "business_unit_id": str,
          "watermark": str, "days_stale": int}]
    """
    from core.config import F_REVIEWS, PROJECT
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJECT)
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


def check_pipeline_staleness(threshold_hours: int = PIPELINE_STALENESS_HOURS) -> list[dict]:
    """Check if any pipeline hasn't had a successful run in threshold_hours.

    Catches the "Type 1" failure mode: cron crashed, BQ was down, etc.

    Returns a list of stale pipelines:
        [{"pipeline_name": str, "last_ok": str, "hours_since": int}]
    """
    from core.config import F_PIPELINE_RUNS, PROJECT
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJECT)
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


def check_crashed_runs(threshold_hours: int = CRASHED_RUN_HOURS) -> list[dict]:
    """Find runs stuck in RUNNING status for too long (probably crashed).

    Returns a list of crashed runs:
        [{"run_id": str, "pipeline_name": str,
          "started_at": str, "hours_running": int}]
    """
    from core.config import F_PIPELINE_RUNS, PROJECT
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJECT)
    sql = f"""
    SELECT
        run_id,
        pipeline_name,
        started_at,
        TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) AS hours_running
    FROM `{F_PIPELINE_RUNS}`
    WHERE status = 'RUNNING'
      AND TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), started_at, HOUR) > @threshold
    ORDER BY started_at
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("threshold", "INT64", threshold_hours),
        ]
    )
    return [dict(r) for r in client.query(sql, job_config=job_config).result()]
