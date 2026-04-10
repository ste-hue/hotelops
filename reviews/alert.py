"""Email alerts for negative reviews."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from google.cloud import bigquery

from reviews.config import ALERT_THRESHOLD, ALERT_RECIPIENTS

log = logging.getLogger(__name__)

GRACE_WINDOW_DAYS = 7


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
    from reviews.email import send_email

    first_run_keys = first_run_keys or set()

    alerted = []
    for row in rows:
        if not should_alert(row):
            continue

        key = (row.get("piattaforma"), row.get("business_unit_id"))
        if key in first_run_keys and not _within_grace_window(row):
            log.info(
                "Grace window: skipping alert for %s %s (first-run, data_review=%s)",
                key[0], key[1], row.get("data_review"),
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


def mark_alerts_sent(review_hashes: list[str]) -> None:
    """UPDATE f_reviews SET alert_inviato=TRUE for the given hashes.

    Uses a parameterized ARRAY query (never string interpolation).
    No-op if the list is empty.
    """
    if not review_hashes:
        return

    from core.config import F_REVIEWS, PROJECT

    client = bigquery.Client(project=PROJECT)
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
    log.info("mark_alerts_sent: flagged %d reviews", len(review_hashes))


def send_gap_alert(gap_keys: list[tuple[str, str]], dry_run: bool = False) -> None:
    """Send a single summary email when one or more (piattaforma, bu) pairs
    returned a full cap of new reviews (possible gap beyond the 16th item).
    """
    if not gap_keys:
        return

    from reviews.email import send_email

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
