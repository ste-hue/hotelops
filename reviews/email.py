"""Email sending (Gmail API) and weekly report rendering."""

from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from reviews.config import REPORT_RECIPIENTS

log = logging.getLogger(__name__)


def _get_gmail_service():
    """Get Gmail API service using gcloud application default credentials."""
    from google.auth import default
    from googleapiclient.discovery import build

    creds, project = default(scopes=["https://www.googleapis.com/auth/gmail.send"])
    return build("gmail", "v1", credentials=creds)


def send_email(
    to: list[str],
    subject: str,
    body: str,
    html: str | None = None,
) -> None:
    """Send email via Gmail API."""
    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html, "html"))
    else:
        msg = MIMEText(body, "plain")

    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    service = _get_gmail_service()
    service.users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()

    log.info("Email sent to %s: %s", to, subject)


def render_weekly_report(
    rows: list[dict],
    date_start: str,
    date_end: str,
) -> str:
    """Render weekly review report as HTML."""
    total = len(rows)
    if total == 0:
        return f"""<html><body>
        <h2>Reviews settimanali — {date_start} / {date_end}</h2>
        <p>Nessuna review ricevuta questa settimana.</p>
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

    neg_rows = ""
    for r in negatives:
        neg_rows += (
            f"<tr>"
            f"<td>{r.get('piattaforma')}</td>"
            f"<td>{r.get('business_unit_id')}</td>"
            f"<td>{r.get('punteggio_norm', 0):.0f}/10</td>"
            f"<td>{r.get('categoria_nlp') or 'N/A'}</td>"
            f"<td>{r.get('riassunto_nlp') or r.get('testo', '')[:80]}</td>"
            f"</tr>"
        )

    return f"""<html><body style="font-family: Arial, sans-serif; max-width: 700px; margin: auto;">
<h2>Reviews settimanali — {date_start} / {date_end}</h2>

<table style="margin-bottom: 20px;">
<tr><td><strong>Totale review:</strong></td><td>{total}</td></tr>
<tr><td><strong>Punteggio medio:</strong></td><td>{avg_score:.1f}/10</td></tr>
<tr><td><strong>Review negative (<=6):</strong></td><td>{len(negatives)}</td></tr>
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

{"<h3>Review negative</h3>" if negatives else ""}
{"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse: collapse;'><tr style='background: #C0392B; color: white;'><th>Piattaforma</th><th>BU</th><th>Score</th><th>Categoria</th><th>Riassunto</th></tr>" + neg_rows + "</table>" if negatives else "<p>Nessuna review negativa questa settimana!</p>"}

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
