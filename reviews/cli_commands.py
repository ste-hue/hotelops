"""CLI handlers for hotelops reviews subcommand."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def cmd_reviews(args):
    """Main reviews CLI handler — dispatches to sub-actions."""
    if args.scrape:
        _cmd_scrape(args)
    elif args.alert:
        _cmd_alert(args)
    elif args.report:
        _cmd_report(args)
    elif args.stats:
        _cmd_stats(args)
    else:
        _cmd_summary(args)


def _cmd_summary(args):
    """Show latest reviews summary."""
    from google.cloud import bigquery
    from core.config import F_REVIEWS, PROJECT

    client = bigquery.Client(project=PROJECT)

    sql = f"""
    SELECT piattaforma, business_unit_id, punteggio_norm, punteggio_raw,
           categoria_nlp, sentiment_nlp, riassunto_nlp, data_review
    FROM `{F_REVIEWS}`
    ORDER BY data_ingest DESC
    LIMIT 30
    """
    rows = [dict(r) for r in client.query(sql).result()]

    if not rows:
        print("  Nessuna review trovata.")
        return

    avg = sum(r["punteggio_norm"] for r in rows) / len(rows)
    neg = sum(1 for r in rows if r["punteggio_norm"] <= 6.0)

    print(f"\n  Ultime {len(rows)} reviews — Media: {avg:.1f}/10 — Negative: {neg}")
    print(f"  {'Data':<12s} {'Piatt.':<14s} {'BU':<10s} {'Score':>6s} {'Categoria':<12s} {'Riassunto'}")
    print(f"  {'─' * 12} {'─' * 14} {'─' * 10} {'─' * 6} {'─' * 12} {'─' * 30}")

    for r in rows:
        score = f"{r['punteggio_norm']:.0f}/10"
        cat = r.get("categoria_nlp") or "—"
        riassunto = (r.get("riassunto_nlp") or "")[:40]
        print(
            f"  {r['data_review']!s:<12s} {r['piattaforma']:<14s} "
            f"{r['business_unit_id']:<10s} {score:>6s} {cat:<12s} {riassunto}"
        )


def _cmd_scrape(args):
    """Trigger manual scrape."""
    from reviews.scrape import scrape_platform, scrape_all
    from reviews.ingest import normalize_items, dedup_reviews, load_to_bq
    from reviews.classify import classify_reviews
    from reviews.alert import send_alerts

    platform = args.only.upper() if args.only else None

    print(f"\n  Scraping {'all platforms' if not platform else platform}...")

    if platform:
        raw = scrape_platform(platform, dry_run=args.dry_run)
    else:
        raw = scrape_all(dry_run=args.dry_run)

    if args.dry_run:
        print(f"  [DRY RUN] Would process {len(raw)} raw items")
        return

    print(f"  Collected {len(raw)} raw items")

    rows = normalize_items(raw)
    rows = dedup_reviews(rows)
    print(f"  Normalized: {len(rows)} unique reviews")

    rows = classify_reviews(rows)
    print(f"  Classified: {len(rows)} reviews")

    inserted = load_to_bq(rows)
    print(f"  Loaded to BQ: {inserted} new reviews")

    alerted = send_alerts(rows)
    print(f"  Alerts sent: {len(alerted)}")


def _cmd_alert(args):
    """Show reviews that triggered alerts."""
    from google.cloud import bigquery
    from core.config import F_REVIEWS, PROJECT

    client = bigquery.Client(project=PROJECT)

    sql = f"""
    SELECT piattaforma, business_unit_id, punteggio_norm, punteggio_raw,
           categoria_nlp, riassunto_nlp, data_review, url_review
    FROM `{F_REVIEWS}`
    WHERE alert_inviato = TRUE
    ORDER BY data_ingest DESC
    LIMIT 20
    """
    rows = [dict(r) for r in client.query(sql).result()]

    if not rows:
        print("  Nessun alert inviato.")
        return

    print(f"\n  Ultimi {len(rows)} alert:")
    for r in rows:
        print(
            f"  {r['data_review']!s} | {r['piattaforma']} | "
            f"{r['punteggio_norm']:.0f}/10 | {r.get('categoria_nlp') or '—'} | "
            f"{(r.get('riassunto_nlp') or '')[:50]}"
        )


def _cmd_stats(args):
    """Show review statistics for a month."""
    from google.cloud import bigquery
    from core.config import F_REVIEWS, PROJECT

    client = bigquery.Client(project=PROJECT)
    anno = args.anno or 2026
    mese_filter = f"AND EXTRACT(MONTH FROM data_review) = {args.mese}" if args.mese else ""

    sql = f"""
    SELECT
      piattaforma,
      COUNT(*) AS n,
      ROUND(AVG(punteggio_norm), 1) AS media,
      COUNTIF(punteggio_norm <= 6) AS negative
    FROM `{F_REVIEWS}`
    WHERE EXTRACT(YEAR FROM PARSE_DATE('%Y-%m-%d', data_review)) = {anno}
    {mese_filter}
    GROUP BY piattaforma
    ORDER BY piattaforma
    """
    rows = [dict(r) for r in client.query(sql).result()]

    if not rows:
        print(f"  Nessun dato per {anno}" + (f" mese {args.mese}" if args.mese else ""))
        return

    total_n = sum(r["n"] for r in rows)
    total_neg = sum(r["negative"] for r in rows)
    overall_avg = sum(r["media"] * r["n"] for r in rows) / total_n

    print(f"\n  Review Stats — {anno}" + (f" mese {args.mese}" if args.mese else " YTD"))
    print(f"  Totale: {total_n} | Media: {overall_avg:.1f}/10 | Negative: {total_neg}")
    print(f"  {'Piattaforma':<14s} {'#':>5s} {'Media':>7s} {'Neg':>5s}")
    print(f"  {'─' * 14} {'─' * 5} {'─' * 7} {'─' * 5}")
    for r in rows:
        print(f"  {r['piattaforma']:<14s} {r['n']:>5d} {r['media']:>6.1f} {r['negative']:>5d}")


def _cmd_report(args):
    """Manually trigger weekly report."""
    from datetime import date, timedelta
    from google.cloud import bigquery
    from core.config import F_REVIEWS, PROJECT
    from reviews.email import send_weekly_report

    today = date.today()
    end = today - timedelta(days=today.weekday() + 1)  # last Sunday
    start = end - timedelta(days=6)  # last Monday

    client = bigquery.Client(project=PROJECT)
    sql = f"""
    SELECT *
    FROM `{F_REVIEWS}`
    WHERE data_review BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
    ORDER BY data_review
    """
    rows = [dict(r) for r in client.query(sql).result()]

    print(f"  Report {start.isoformat()} — {end.isoformat()}: {len(rows)} reviews")
    send_weekly_report(rows, start.isoformat(), end.isoformat(), dry_run=args.dry_run)
    if not args.dry_run:
        print("  Email inviata.")
    else:
        print("  [DRY RUN] Email non inviata.")
