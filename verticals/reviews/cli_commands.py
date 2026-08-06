"""CLI handlers for hotelops reviews subcommand."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def cmd_reviews(args):
    """Main reviews CLI handler — dispatches to sub-actions."""
    if getattr(args, "rispondi", False):
        _cmd_rispondi(args)
    elif args.scrape:
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
    from core.bq.client import get_client
    from core.config import F_REVIEWS

    client = get_client()

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
    print(
        f"  {'Data':<12s} {'Piatt.':<14s} {'BU':<10s} {'Score':>6s} {'Categoria':<12s} {'Riassunto'}"
    )
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
    """Trigger manual scrape. Watermark-gated pipeline."""
    from core.pipeline_run import PipelineRun
    from verticals.reviews.scrape import scrape_platform, scrape_all, MAX_REVIEWS_PER_PROPERTY
    from verticals.reviews.ingest import (
        normalize_items,
        dedup_reviews,
        load_to_bq,
        read_watermarks,
        filter_by_watermark,
    )
    from verticals.reviews.classify import classify_reviews
    from verticals.reviews.alert import (
        send_alerts,
        mark_alerts_sent,
        send_gap_alert,
        flush_pending_alert_flags,
    )

    platform = args.only.upper() if args.only else None

    print(f"\n  Scraping {'all platforms' if not platform else platform}...")

    with PipelineRun("reviews_scrape") as run:
        # 0. Reconcile any pending alert flags from a previous run that crashed
        #    on the streaming buffer. Best-effort, never raises.
        if not args.dry_run:
            flushed = flush_pending_alert_flags()
            if flushed:
                print(f"  Reconciled {flushed} pending alert flags from previous run")

        # 1. Read watermarks BEFORE scraping. In dry_run we still exercise the
        #    read path to catch BQ auth/connectivity issues early, but we degrade
        #    to an empty dict on failure instead of aborting.
        try:
            watermarks = read_watermarks()
            if args.dry_run:
                print(f"  [DRY RUN] Watermarks loaded: {len(watermarks)} keys")
        except Exception as e:
            if args.dry_run:
                print(f"  [DRY RUN] WARNING: read_watermarks failed: {e}")
                watermarks = {}
            else:
                print(f"  ABORT: read_watermarks failed: {e}")
                raise

        # 2. Scrape
        if platform:
            raw, total_cost = scrape_platform(platform, dry_run=args.dry_run)
        else:
            raw, total_cost = scrape_all(dry_run=args.dry_run)

        # Set observability fields as early as possible so any early return
        # (or crash) records accurate metrics via __exit__.
        run.rows_found = len(raw)
        run.usage_total_usd = total_cost if total_cost else None

        if args.dry_run:
            print(f"  [DRY RUN] Would process {len(raw)} raw items")
            run.rows_new = 0
            run.meta = {
                "watermarks": {f"{k[0]}|{k[1]}": v for k, v in watermarks.items()},
                "platform": platform or "ALL",
                "dry_run": True,
            }
            return

        print(f"  Collected {len(raw)} raw items")

        # 3. Normalize
        rows = normalize_items(raw)
        rows = dedup_reviews(rows)
        print(f"  Normalized: {len(rows)} unique reviews")

        # 4. Watermark filter — drop already-seen, detect gaps
        #    Track which keys were first-run (watermark was None) BEFORE filtering.
        present_keys = {(r["piattaforma"], r["business_unit_id"]) for r in rows}
        first_run_keys = {k for k in present_keys if k not in watermarks}

        new_rows, gap_keys = filter_by_watermark(
            watermarks, rows, cap=MAX_REVIEWS_PER_PROPERTY
        )
        print(
            f"  Watermark filter: {len(new_rows)} new (dropped {len(rows) - len(new_rows)})"
        )
        if gap_keys:
            print(f"  ⚠️  Gap suspected on: {gap_keys}")

        run.rows_new = len(new_rows)
        run.meta = {
            "watermarks": {f"{k[0]}|{k[1]}": v for k, v in watermarks.items()},
            "gap_keys": [f"{k[0]}|{k[1]}" for k in gap_keys] if gap_keys else [],
            "first_run_keys": [f"{k[0]}|{k[1]}" for k in first_run_keys]
            if first_run_keys
            else [],
            "platform": platform or "ALL",
        }

        if not new_rows:
            print("  No new reviews; skipping classify/load/alert.")
            run.alerts_sent = 0
            if gap_keys:
                send_gap_alert(gap_keys)
            return

        # 5. Classify (only new)
        new_rows = classify_reviews(new_rows)
        print(f"  Classified: {len(new_rows)} reviews")

        # 6. Load to BQ
        inserted = load_to_bq(new_rows)
        print(f"  Loaded to BQ: {inserted} new reviews")

        # 7. Send alerts (only on new, with grace window for first-run keys)
        alerted = send_alerts(new_rows, first_run_keys=first_run_keys)
        print(f"  Alerts sent: {len(alerted)}")
        run.alerts_sent = len(alerted)

        # 8. Persist alert flag
        if alerted:
            mark_alerts_sent([r["review_hash"] for r in alerted])
            print(f"  alert_inviato flagged on {len(alerted)} rows")

        # 9. Gap mail (if any)
        if gap_keys:
            send_gap_alert(gap_keys)


def _cmd_alert(args):
    """Show reviews that triggered alerts."""
    from core.bq.client import get_client
    from core.config import F_REVIEWS

    client = get_client()

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
    from core.bq.client import get_client
    from core.config import F_REVIEWS

    client = get_client()
    anno = args.anno or 2026
    mese_filter = (
        f"AND EXTRACT(MONTH FROM data_review) = {args.mese}" if args.mese else ""
    )

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

    print(
        f"\n  Review Stats — {anno}" + (f" mese {args.mese}" if args.mese else " YTD")
    )
    print(f"  Totale: {total_n} | Media: {overall_avg:.1f}/10 | Negative: {total_neg}")
    print(f"  {'Piattaforma':<14s} {'#':>5s} {'Media':>7s} {'Neg':>5s}")
    print(f"  {'─' * 14} {'─' * 5} {'─' * 7} {'─' * 5}")
    for r in rows:
        print(
            f"  {r['piattaforma']:<14s} {r['n']:>5d} {r['media']:>6.1f} {r['negative']:>5d}"
        )


def _cmd_report(args):
    """Manually trigger weekly report.

    Default window: ultima settimana ISO completa chiusa (Lun-Dom precedenti).
    Questo è il contratto col cron settimanale (lanciato il lunedì mattina)
    e non va cambiato senza rompere la coerenza storica dei run.

    Override manuale: --start / --end (YYYY-MM-DD) per ispezioni ad hoc —
    es. recap della settimana in corso, o drill-down su un range specifico.
    """
    from datetime import date, timedelta
    from core.bq.client import get_client
    from core.config import F_REVIEWS
    from verticals.reviews.email import send_weekly_report

    if args.start and args.end:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    elif args.start or args.end:
        raise SystemExit("--start e --end vanno forniti insieme")
    else:
        today = date.today()
        end = today - timedelta(days=today.weekday() + 1)  # last Sunday
        start = end - timedelta(days=6)  # last Monday

    client = get_client()
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


def _cmd_rispondi(args):
    """Genera una bozza di risposta (draft-only, stdout). Testo da stdin o --file."""
    import sys
    from pathlib import Path

    from verticals.reviews import respond

    if not args.bu:
        raise SystemExit("--rispondi richiede --bu (HOTEL|RESIDENCE|CVM)")

    if args.file:
        try:
            testo = Path(args.file).read_text(encoding="utf-8")
        except OSError as e:
            raise SystemExit(f"Errore lettura file: {e}")
    else:
        testo = sys.stdin.read()

    try:
        bozza = respond.generate_response(testo, args.bu, nota=args.nota)
    except ValueError as e:
        raise SystemExit(f"Errore: {e}")
    except Exception as e:
        raise SystemExit(f"Errore generazione bozza: {e}")

    print(bozza)
