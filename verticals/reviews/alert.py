"""Email alerts for negative reviews."""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

from google.api_core.exceptions import BadRequest
from google.cloud import bigquery

from core.bq.pending_flags import (
    append_pending_flags,
    clear_pending_flags,
    read_pending_flags,
)
from core.bq.client import get_client

from verticals.reviews.config import ALERT_THRESHOLD, ALERT_RECIPIENTS

log = logging.getLogger(__name__)

GRACE_WINDOW_DAYS = 7

# Retry backoff for mark_alerts_sent when UPDATE hits the streaming buffer.
# Tests monkeypatch this to [0, 0, 0] to skip sleeps.
# Total wait ~3.5 min — catches fast buffer flushes + transient BQ flakiness.
# Slow flushes (30-90 min) are handled by BigQuery-backed pending state.
_MARK_ALERTS_RETRY_DELAYS = [30, 60, 120]


def should_alert(row: dict) -> bool:
    """Return True if this review should trigger an alert."""
    if row.get("alert_inviato"):
        return False
    return row.get("punteggio_norm", 10.0) <= ALERT_THRESHOLD


def _within_grace_window(row: dict, today: date | None = None) -> bool:
    today = today or date.today()
    cutoff = (today - timedelta(days=GRACE_WINDOW_DAYS)).isoformat()
    return (row.get("data_review") or "") >= cutoff


def render_alert_body(row: dict) -> str:
    """Render plain-text email body for a negative review alert."""
    scala = 10 if row["piattaforma"] in ("BOOKING", "EXPEDIA") else 5
    return f"""Review negativa ricevuta

Piattaforma: {row["piattaforma"]}
Struttura: {row["business_unit_id"]}
Punteggio: {row["punteggio_raw"]}/{scala}
Data review: {row["data_review"]}
Categoria: {row.get("categoria_nlp") or "N/A"}
Reviewer: {row.get("reviewer_nome") or "Anonimo"} ({row.get("reviewer_paese") or "?"})

Riassunto: {row.get("riassunto_nlp") or "N/A"}

Testo completo:
{row.get("testo", "")}

Link: {row.get("url_review") or "N/A"}
"""


def render_alert_subject(row: dict) -> str:
    """Render email subject line for a negative review alert."""
    scala = 10 if row["piattaforma"] in ("BOOKING", "EXPEDIA") else 5
    return (
        f"Review negativa — {row['business_unit_id']} — "
        f"{row['piattaforma']} — {row['punteggio_raw']}/{scala}"
    )


def send_alerts(
    rows: list[dict],
    first_run_keys: set[tuple[str, str]] | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Send email alerts for negative reviews.

    Args:
        rows: reviews to consider (should already be filtered to "new" by
              the watermark gate — this function does NOT re-filter by hash).
        first_run_keys: set of (piattaforma, business_unit_id) that had no
              pre-existing watermark. For these keys, a 7-day grace window
              is applied to avoid spamming historical reviews at seed time.
        dry_run: don't actually send.

    Returns: list of alerted rows. Caller is responsible for calling
    mark_alerts_sent() with the hashes of the returned rows.
    """
    from verticals.reviews.email import send_email

    first_run_keys = first_run_keys or set()

    alerted = []
    for row in rows:
        if not should_alert(row):
            continue

        key = (row.get("piattaforma"), row.get("business_unit_id"))
        if key in first_run_keys and not _within_grace_window(row):
            log.info(
                "Grace window: skipping alert for %s %s (first-run, data_review=%s)",
                key[0],
                key[1],
                row.get("data_review"),
            )
            continue

        subject = render_alert_subject(row)
        body = render_alert_body(row)

        if dry_run:
            log.info("[DRY RUN] Would send alert: %s", subject)
        else:
            send_email(to=ALERT_RECIPIENTS, subject=subject, body=body)
            log.info("Alert sent: %s", subject)

        alerted.append(row)

    return alerted


def _is_streaming_buffer_error(exc: BaseException) -> bool:
    """True if exc is a BQ error about the streaming buffer blocking UPDATE.

    BigQuery raises BadRequest 400 with message containing "streaming buffer"
    when UPDATE/DELETE touches rows inserted via insert_rows_json() within
    the last ~30-90 min. This is the specific failure mode we want to retry.
    """
    return isinstance(exc, BadRequest) and "streaming buffer" in str(exc).lower()


def _run_update_flag(client: bigquery.Client, review_hashes: list[str]) -> None:
    """Run the parameterized UPDATE. Extracted so retry + flush share it."""
    from core.config import F_REVIEWS

    sql = f"""
    UPDATE `{F_REVIEWS}`
    SET alert_inviato = TRUE
    WHERE review_hash IN UNNEST(@hashes)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("hashes", "STRING", review_hashes),
        ]
    )
    client.query(sql, job_config=job_config).result()


def _persist_pending(review_hashes: list[str]) -> None:
    """Append hashes to durable BigQuery pending state."""
    run_id = None
    try:
        from core.pipeline_run import PipelineRun

        current = PipelineRun.get_current()
        if current:
            run_id = current.run_id
    except Exception:
        # Best-effort metadata only.
        run_id = None

    inserted = append_pending_flags(review_hashes, run_id=run_id)
    pending = read_pending_flags()
    log.error(
        "PENDING ALERT FLAGS: persisted %d hashes (%d currently pending in BQ) "
        "— will retry next run",
        inserted,
        len(pending),
    )


def mark_alerts_sent(review_hashes: list[str]) -> None:
    """UPDATE f_reviews SET alert_inviato=TRUE for the given hashes.

    Uses a parameterized ARRAY query (never string interpolation).
    No-op if the list is empty.

    Streaming buffer handling: if the UPDATE fails because rows are still
    in the buffer (recent insert_rows_json), retry with backoff. If all
    retries fail, persist hashes to the pending state file so the next
    scrape run can reconcile after the buffer has flushed. Emails have
    already been sent at this point — we just need to close the flag
    eventually to prevent duplicate alerts later.
    """
    if not review_hashes:
        return

    client = get_client()

    attempts = len(_MARK_ALERTS_RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            _run_update_flag(client, review_hashes)
            log.info("mark_alerts_sent: flagged %d reviews", len(review_hashes))
            return
        except Exception as e:
            last_attempt = attempt == attempts - 1
            if not _is_streaming_buffer_error(e) or last_attempt:
                if _is_streaming_buffer_error(e):
                    log.warning(
                        "mark_alerts_sent: streaming buffer still blocking after %d attempts",
                        attempts,
                    )
                    _persist_pending(review_hashes)
                    return
                raise
            delay = _MARK_ALERTS_RETRY_DELAYS[attempt]
            log.warning(
                "mark_alerts_sent attempt %d/%d hit streaming buffer, retrying in %ds",
                attempt + 1,
                attempts,
                delay,
            )
            time.sleep(delay)


def flush_pending_alert_flags() -> int:
    """Retry pending alert-flag UPDATEs from a previous run.

    Called at the start of a scrape run — by then the streaming buffer has
    usually flushed. On success, clears pending rows in BQ. On failure, leaves
    them for the next run. Never raises: this is a best-effort reconciliation.

    Returns: number of hashes successfully flagged (0 if no pending).
    """
    hashes = read_pending_flags()
    if not hashes:
        return 0

    log.info("flush_pending_alert_flags: retrying %d pending hashes", len(hashes))
    try:
        client = get_client()
        _run_update_flag(client, hashes)
    except Exception as e:
        if _is_streaming_buffer_error(e):
            log.warning(
                "flush_pending_alert_flags: still blocked by streaming buffer, "
                "leaving pending hashes in BQ for next run"
            )
        else:
            log.exception("flush_pending_alert_flags failed unexpectedly")
        return 0

    cleared = clear_pending_flags(hashes)
    if cleared != len(hashes):
        log.warning(
            "flush_pending_alert_flags: flagged %d hashes but cleared %d pending rows",
            len(hashes),
            cleared,
        )
    log.info(
        "flush_pending_alert_flags: flagged %d hashes, cleared pending state", len(hashes)
    )
    return len(hashes)


def send_gap_alert(gap_keys: list[tuple[str, str]], dry_run: bool = False) -> None:
    """Send a single summary email when one or more (piattaforma, bu) pairs
    returned a full cap of new reviews (possible gap beyond the 16th item).
    """
    if not gap_keys:
        return

    from verticals.reviews.email import send_email

    lines = [f"- {p} / {bu}" for p, bu in gap_keys]
    body = (
        "Gap sospetto nella pipeline reviews: per le seguenti piattaforme/BU "
        "l'actor ha restituito un cap pieno di nuove review, potrebbero "
        "esserci review più vecchie del 16° elemento non catturate.\n\n"
        + "\n".join(lines)
        + "\n\nValutare un rilancio manuale con cap più alto."
    )
    subject = f"[hotelops] GAP SUSPECTED reviews — {len(gap_keys)} chiavi"

    if dry_run:
        log.info("[DRY RUN] Would send gap alert: %s", subject)
    else:
        send_email(to=ALERT_RECIPIENTS, subject=subject, body=body)
        log.warning("Gap alert sent: %s", subject)
