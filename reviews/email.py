"""Email sending (Gmail SMTP) and weekly report rendering."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from reviews.config import REPORT_RECIPIENTS

log = logging.getLogger(__name__)


def send_email(
    to: list[str],
    subject: str,
    body: str,
    html: str | None = None,
) -> None:
    """Send email via Gmail SMTP with app password."""
    user = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not user or not password:
        raise RuntimeError("GMAIL_USER / GMAIL_APP_PASSWORD env vars not set")

    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html, "html"))
    else:
        msg = MIMEText(body, "plain")

    msg["From"] = user
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)

    log.info("Email sent to %s: %s", to, subject)


def _fetch_apify_costs(date_start: str, date_end: str) -> list[dict]:
    """Query f_apify_runs for runs between date_start and date_end (inclusive).

    Returns list of dicts with (piattaforma, n_runs, n_items, cost_usd).
    On BQ failure, returns empty list — cost section just won't render.
    """
    try:
        from google.cloud import bigquery

        from core.bq.client import get_client
        from core.config import F_APIFY_RUNS

        client = get_client()
        sql = f"""
        SELECT
          piattaforma,
          COUNT(*) AS n_runs,
          SUM(n_items) AS n_items,
          SUM(cost_usd) AS cost_usd,
          COUNTIF(cap_violated) AS n_cap_violated
        FROM `{F_APIFY_RUNS}`
        WHERE DATE(ts_run) BETWEEN @start AND @end
        GROUP BY piattaforma
        ORDER BY piattaforma
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start", "DATE", date_start),
                bigquery.ScalarQueryParameter("end", "DATE", date_end),
            ]
        )
        return [dict(r) for r in client.query(sql, job_config=job_config).result()]
    except Exception:
        log.exception("_fetch_apify_costs failed (non-fatal)")
        return []


def _render_cost_section(cost_rows: list[dict]) -> str:
    """Render the 'Costi Apify' block. Empty string if no data."""
    if not cost_rows:
        return ""
    total_cost = sum((r.get("cost_usd") or 0.0) for r in cost_rows)
    total_items = sum((r.get("n_items") or 0) for r in cost_rows)
    total_runs = sum((r.get("n_runs") or 0) for r in cost_rows)
    total_violations = sum((r.get("n_cap_violated") or 0) for r in cost_rows)

    cost_body = ""
    for r in cost_rows:
        cost = r.get("cost_usd") or 0.0
        cost_body += (
            f"<tr>"
            f"<td>{r.get('piattaforma')}</td>"
            f"<td>{r.get('n_runs', 0)}</td>"
            f"<td>{r.get('n_items', 0)}</td>"
            f"<td>${cost:.4f}</td>"
            f"<td>{r.get('n_cap_violated', 0)}</td>"
            f"</tr>"
        )
    violations_color = "#C0392B" if total_violations > 0 else "#2C3E50"
    return f"""
<h3>Costi Apify (scraping)</h3>
<table style="margin-bottom: 10px;">
<tr><td><strong>Spesa totale:</strong></td><td>${total_cost:.4f}</td></tr>
<tr><td><strong>Run totali:</strong></td><td>{total_runs}</td></tr>
<tr><td><strong>Review scaricate:</strong></td><td>{total_items}</td></tr>
<tr><td><strong>Cap violati:</strong></td><td style="color:{violations_color};font-weight:bold;">{total_violations}</td></tr>
</table>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">
<tr style="background: #1F4E79; color: white;">
<th>Piattaforma</th><th># Run</th><th># Item</th><th>Cost USD</th><th>Cap viol.</th>
</tr>
{cost_body}
</table>
"""


def render_weekly_report(
    rows: list[dict],
    date_start: str,
    date_end: str,
) -> str:
    """Render weekly review report as HTML."""
    total = len(rows)
    cost_section = _render_cost_section(_fetch_apify_costs(date_start, date_end))
    if total == 0:
        return f"""<html><body style="font-family: Arial, sans-serif; max-width: 800px; margin: auto;">
<h2>Reviews settimanali — {date_start} / {date_end}</h2>
<p>Nessuna review ricevuta questa settimana.</p>
{cost_section}
</body></html>"""

    avg_score = sum(r.get("punteggio_norm", 0) for r in rows) / total
    negatives = [r for r in rows if r.get("punteggio_norm", 10) <= 6.0]

    by_platform = {}
    for r in rows:
        p = r.get("piattaforma", "?")
        by_platform.setdefault(p, []).append(r)

    by_cat = {}
    for r in rows:
        cat = r.get("categoria_nlp") or "N/A"
        by_cat[cat] = by_cat.get(cat, 0) + 1
    top_cats = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[:5]

    platform_rows = ""
    for p, rev_list in sorted(by_platform.items()):
        p_avg = sum(r.get("punteggio_norm", 0) for r in rev_list) / len(rev_list)
        platform_rows += (
            f"<tr><td>{p}</td><td>{len(rev_list)}</td><td>{p_avg:.1f}</td></tr>"
        )

    cat_rows = ""
    for cat, count in top_cats:
        cat_rows += f"<tr><td>{cat}</td><td>{count}</td></tr>"

    # All reviews detail rows
    all_rows_html = ""
    for r in sorted(rows, key=lambda x: x.get("punteggio_norm", 10)):
        score = r.get("punteggio_norm", 0)
        color = "#C0392B" if score <= 6 else "#2C3E50"
        all_rows_html += (
            f"<tr>"
            f"<td>{r.get('data_review', '')!s:.10s}</td>"
            f"<td>{r.get('piattaforma')}</td>"
            f"<td>{r.get('business_unit_id')}</td>"
            f"<td style='color:{color};font-weight:bold;'>{score:.0f}/10</td>"
            f"<td>{r.get('categoria_nlp') or 'N/A'}</td>"
            f"<td>{r.get('riassunto_nlp') or r.get('testo', '')[:100]}</td>"
            f"</tr>"
        )

    return f"""<html><body style="font-family: Arial, sans-serif; max-width: 800px; margin: auto;">
<h2>Reviews settimanali — {date_start} / {date_end}</h2>

<table style="margin-bottom: 20px;">
<tr><td><strong>Totale review:</strong></td><td>{total}</td></tr>
<tr><td><strong>Punteggio medio:</strong></td><td>{avg_score:.1f}/10</td></tr>
<tr><td><strong>Review negative (<=6):</strong></td><td style="color:#C0392B;font-weight:bold;">{len(negatives)}</td></tr>
</table>

<h3>Per piattaforma</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">
<tr style="background: #1F4E79; color: white;">
<th>Piattaforma</th><th># Review</th><th>Media</th>
</tr>
{platform_rows}
</table>

<h3>Top categorie</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">
<tr style="background: #1F4E79; color: white;">
<th>Categoria</th><th># Menzioni</th>
</tr>
{cat_rows}
</table>

<h3>Tutte le review</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse; font-size: 13px;">
<tr style="background: #1F4E79; color: white;">
<th>Data</th><th>Piattaforma</th><th>BU</th><th>Score</th><th>Categoria</th><th>Riassunto</th>
</tr>
{all_rows_html}
</table>

{cost_section}

</body></html>"""


def send_weekly_report(
    rows: list[dict],
    date_start: str,
    date_end: str,
    dry_run: bool = False,
) -> None:
    """Generate and send the weekly review report."""
    html = render_weekly_report(rows, date_start, date_end)
    subject = f"Reviews settimanali — {date_start} / {date_end}"
    plain = f"Reviews settimanali: {len(rows)} review, vedi HTML per dettagli."

    if dry_run:
        log.info("[DRY RUN] Would send weekly report: %s", subject)
        return

    send_email(
        to=REPORT_RECIPIENTS,
        subject=subject,
        body=plain,
        html=html,
    )
