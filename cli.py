#!/usr/bin/env python3
"""
hotelops CLI — control plane per il financial model.

Subcomandi:
    hotelops pf          Piano Finanziario mensile (budget vs consuntivo)
    hotelops bva         Budget vs Consuntivo per codice conto
    hotelops chiudi      Chiusura mese: consuntivo vs previsione + saldo banca
    hotelops saldo       Saldo banca corrente e proiezione cash forward
    hotelops health      Health check: freshness dati, gaps, alert
    hotelops previsione  Inserisci/aggiorna previsione budget
    hotelops voci        Lista voci piano finanziario disponibili
    hotelops classifica  Classifica, smista e ingerisci file dati

Installazione:
    pip install -e .    (poi: hotelops pf)
    oppure: python -m cli pf

Richiede: gcloud auth (stefano@panoramagroup.it)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from condges.cli_commands import (
    cmd_chiudi,
    cmd_health,
    cmd_help,
    cmd_pf,
    cmd_saldo,
    cmd_scadenzario,
)

BQ_PROJECT = "hotelops-suite"

# ── Lazy BQ client ──────────────────────────────────────────────────────────

_bq_client = None


def bq():
    global _bq_client
    if _bq_client is None:
        from google.cloud import bigquery

        _bq_client = bigquery.Client(project=BQ_PROJECT)
    return _bq_client


def query(sql: str) -> list[dict]:
    rows = bq().query(sql).result()
    return [dict(r) for r in rows]


def fmt_eur(v) -> str:
    if v is None:
        return "-"
    return f"€{v:>10,.0f}"


# ── BVA: Budget vs Consuntivo per conto ─────────────────────────────────────


def cmd_bva(args):
    """Budget vs Consuntivo per codice conto."""
    societa = args.societa or "ORTI"
    anno = args.anno or 2026
    mese = args.mese

    mese_filter = (
        f"AND mese = {mese}"
        if mese
        else "AND mese <= EXTRACT(MONTH FROM CURRENT_DATE('Europe/Rome'))"
    )

    sql = f"""
    SELECT codice_conto_display, descrizione, categoria_ce, mese,
      ROUND(budget, 0) AS budget, ROUND(consuntivo, 0) AS consuntivo,
      ROUND(delta, 0) AS delta, status
    FROM `hotelops-suite.hotelops.v_budget_vs_consuntivo`
    WHERE societa_id = '{societa}' AND anno = {anno} {mese_filter}
    ORDER BY ABS(delta) DESC
    LIMIT {args.limit or 30}
    """
    rows = query(sql)

    if not rows:
        print(f"Nessun dato BvA per {societa} {anno}")
        return

    print(f"\n  Budget vs Consuntivo — {societa} {anno}")
    print(f"  Top {len(rows)} per |delta| (mese {'YTD' if not mese else mese})")
    print(
        f"  {'Codice':<12s} {'Descrizione':<30s} {'Budget':>10s} {'Actual':>10s} {'Delta':>10s} {'Status'}"
    )
    print(f"  {'─' * 12} {'─' * 30} {'─' * 10} {'─' * 10} {'─' * 10} {'─' * 12}")

    for r in rows:
        codice = (r["codice_conto_display"] or "???")[:12]
        desc = (r["descrizione"] or "")[:30]
        print(
            f"  {codice:<12s} {desc:<30s} {fmt_eur(r['budget'])} {fmt_eur(r['consuntivo'])} {fmt_eur(r['delta'])} {r['status']}"
        )


# ── Previsione ──────────────────────────────────────────────────────────────


def cmd_previsione(args):
    """Inserisci/aggiorna previsione budget."""
    from condges.update_previsione import update_previsione, resolve_voce

    voce_id = resolve_voce(args.voce) or args.voce.upper()
    societa = args.societa or "ORTI"
    anno = args.anno or 2026

    if "-" in args.mesi:
        parts = args.mesi.split("-")
        from condges.update_previsione import resolve_mese

        mese_start = resolve_mese(parts[0]) or int(parts[0])
        mese_end = resolve_mese(parts[1]) or int(parts[1])
    else:
        from condges.update_previsione import resolve_mese

        mese_start = resolve_mese(args.mesi) or int(args.mesi)
        mese_end = mese_start

    result = update_previsione(
        voce_id=voce_id,
        societa_id=societa,
        anno=anno,
        mese_start=mese_start,
        mese_end=mese_end,
        importo_mensile=args.importo,
        fonte=args.fonte or "CLI",
        note=args.note,
        dry_run=args.dry_run,
    )

    if result["status"] == "error":
        print(f"✗ {result['message']}")
        if "suggerimenti" in result:
            print(f"  Voci simili: {', '.join(result['suggerimenti'][:5])}")
        sys.exit(1)

    label = result.get("voce_label", voce_id)
    totale = result.get("totale_periodo", 0)
    n_mesi = mese_end - mese_start + 1
    prefix = "DRY RUN" if args.dry_run else "✓"

    print(f"\n  {prefix}: {label} ({societa})")
    print(
        f"  €{args.importo:,.0f}/mese × {n_mesi} mesi (mesi {mese_start}-{mese_end}) = €{totale:,.0f}"
    )

    if not args.dry_run:
        deleted = result.get("rows_deleted", 0)
        inserted = result.get("rows_inserted", 0)
        print(
            f"  BQ: {deleted} righe sostituite, {inserted} inserite (fonte={result.get('fonte')})"
        )


# ── Voci ────────────────────────────────────────────────────────────────────


def cmd_voci(args):
    """Lista voci piano finanziario."""
    rows = query("""
    SELECT voce_id, voce_label, sezione, categoria, societa_id
    FROM hotelops.d_voci_piano_finanziario
    ORDER BY ord
    """)

    current_sezione = None
    for r in rows:
        if r["sezione"] != current_sezione:
            current_sezione = r["sezione"]
            print(f"\n  ═══ {current_sezione} ═══")
        soc = f" ({r['societa_id']})" if r["societa_id"] else ""
        print(f"    {r['voce_id']:<30s} {r['voce_label']}{soc}")


# ── Manifest: catalogo tabelle BQ ──────────────────────────────────────────


def cmd_manifest(args):
    """Genera manifest.yaml — catalogo di tutte le tabelle BQ."""
    from core.bq.manifest import generate_manifest, TABLES

    output = args.output or "core/bq/manifest.yaml"
    tables = [args.table] if args.table else None

    print(f"\n  Generating manifest for {len(tables or TABLES)} tables → {output}")
    manifest = generate_manifest(output_path=output, tables=tables)

    n_tables = len(manifest["tables"])
    total_rows = sum(t.get("rows", 0) for t in manifest["tables"].values())
    print(f"  ✓ {n_tables} tables cataloged, {total_rows:,} total rows")
    print(f"  ✓ Written to {output}")


# ── Classifica: classify + route + ingest files ──────────────────────────────


def cmd_classifica(args):
    """Classifica file, smista nel datahub e (opzionalmente) ingerisci."""
    from pathlib import Path
    from ingest.classify import classify_batch, route_file, run_ingest, DEFAULT_DATAHUB

    datahub = Path(args.datahub) if args.datahub else DEFAULT_DATAHUB
    files = [Path(f) for f in args.files]

    # Expand globs
    expanded = []
    for f in files:
        if "*" in str(f) or "?" in str(f):
            import glob

            expanded.extend(Path(p) for p in glob.glob(str(f)))
        else:
            expanded.append(f)

    if not expanded:
        print("Nessun file trovato.")
        return

    results = classify_batch(expanded)

    print(f"\n{'=' * 70}")
    print(f"  CLASSIFICAZIONE FILE — {len(results)} file analizzati")
    print(f"{'=' * 70}\n")

    ok = 0
    for r in results:
        if r.category in ("unknown", "error"):
            print(f"❓ {r.file_path.name}")
            if r.details:
                for k, v in r.details.items():
                    print(f"     {k}: {v}")
            print()
            continue

        ok += 1
        emoji = "✅" if r.confidence >= 0.8 else "⚠️"
        print(f"{emoji} {r.file_path.name}")
        print(r.summary())

        if args.route or args.ingest:
            dest = route_file(r, datahub, dry_run=args.dry_run)
            if dest:
                prefix = "[DRY-RUN] " if args.dry_run else ""
                print(f"  {prefix}→ {dest}")

                if args.ingest and not args.dry_run:
                    success = run_ingest(r, dest, datahub, dry_run=args.dry_run)
                    print(f"  Pipeline: {'✅ OK' if success else '❌ ERRORE'}")

        print()

    print(f"{'─' * 70}")
    print(f"  Riconosciuti: {ok}/{len(results)}")
    print(f"{'─' * 70}\n")


# ── Ingest ─────────────────────────────────────────────────────────────────


def cmd_ingest(args):
    """Ingest pipeline: wraps orchestrate.py or single pipelines."""
    # Special case: hotelops ingest coperti --gsheet
    if args.pipeline == "coperti" and args.gsheet:
        from ingest.flussi.ingest_coperti import (
            fetch_gsheet, parse_xlsx_file, load_to_bq, quality_summary,
            GSHEET_ID_DEFAULT,
        )
        from datetime import datetime, timezone

        sheet_id = args.gsheet if args.gsheet is not True else GSHEET_ID_DEFAULT
        xlsx_path = fetch_gsheet(sheet_id)
        ts_now = datetime.now(timezone.utc)
        societa = args.societa or "ORTI"
        rows = parse_xlsx_file(xlsx_path, societa, ts_now)

        if not rows:
            print("  Nessuna riga da caricare.")
            return

        load_to_bq(rows, dry_run=args.dry_run, replace=args.replace)
        quality_summary(rows)
        return

    # General case: delegate to orchestrate
    sys_argv_backup = sys.argv
    argv = ["orchestrate"]
    if args.dry_run:
        argv.append("--dry-run")
    if args.no_sync:
        argv.append("--no-sync")
    if args.only:
        argv.extend(["--only", args.only])
    if args.pipeline:
        argv.extend(["--pipeline", args.pipeline])

    sys.argv = argv
    try:
        from ingest.orchestrate import main as orchestrate_main
        orchestrate_main()
    except SystemExit as e:
        if e.code and e.code != 0:
            sys.exit(e.code)
    finally:
        sys.argv = sys_argv_backup


# ── App ────────────────────────────────────────────────────────────────────


def cmd_app(args):
    """Launch Streamlit apps."""
    import subprocess

    apps = {
        "pf": "condges/app.py",
        "scadenzario": "condges/app_scadenzario.py",
    }
    app_key = args.app_name or "pf"
    app_path = apps.get(app_key)
    if not app_path:
        print(f"  App sconosciuta: '{app_key}'")
        print(f"  Disponibili: {', '.join(apps.keys())}")
        sys.exit(1)

    full_path = Path(__file__).parent / app_path
    print(f"  Lancio: streamlit run {app_path}")
    subprocess.run(["streamlit", "run", str(full_path)], check=True)


# ── Reconcile ──────────────────────────────────────────────────────────────


def cmd_reconcile(args):
    """Bank reconciliation."""
    from condges.reconcile_banca import run_reconciliation

    print(f"\n{'═' * 60}")
    print(f"  RICONCILIAZIONE BANCA  {args.societa} / {args.conto}")
    print(f"  Periodo: {args.date_from} → {args.date_to}")
    print(f"{'═' * 60}\n")

    try:
        metrics = run_reconciliation(
            args.datahub, args.societa, args.conto,
            args.date_from, args.date_to,
            min_score=args.min_score,
        )
    except Exception as e:
        print(f"  ❌ Errore: {e}")
        sys.exit(1)

    print(f"  Run {metrics['run_id']} {metrics['status']}")
    print(f"  Transazioni banca:  {metrics['bank_transactions']}")
    print(f"  Transazioni libro:  {metrics['ledger_transactions']}")
    print(f"  Match auto:         {metrics['auto_matches']}")
    print(f"  Da verificare:      {metrics['review_matches']}")
    print(f"  Senza match:        {metrics['no_matches']}")
    print(f"  Auto rate:          {metrics['auto_rate']:.1%}")
    print(f"  Output:             {metrics['output_dir']}")
    print(f"\n{'═' * 60}\n")


# ── Main ────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        prog="hotelops",
        description="Control plane per il financial model Gruppo Panorama",
    )
    sub = parser.add_subparsers(dest="command")

    # pf
    p_pf = sub.add_parser("pf", help="Piano Finanziario mensile")
    p_pf.add_argument("--societa", choices=["ORTI", "INTUR"])
    p_pf.add_argument("--anno", type=int, default=2026)
    p_pf.add_argument("--mese", type=int, help="Singolo mese (default: tutti)")

    # bva
    p_bva = sub.add_parser("bva", help="Budget vs Consuntivo per conto")
    p_bva.add_argument("--societa", choices=["ORTI", "INTUR"])
    p_bva.add_argument("--anno", type=int, default=2026)
    p_bva.add_argument("--mese", type=int, help="Singolo mese (default: YTD)")
    p_bva.add_argument("--limit", type=int, default=30)

    # chiudi
    p_chiudi = sub.add_parser("chiudi", help="Chiusura mese: consuntivo vs previsione")
    p_chiudi.add_argument(
        "--mese", type=int, help="Mese da chiudere (default: mese precedente)"
    )
    p_chiudi.add_argument("--societa", choices=["ORTI", "INTUR"])
    p_chiudi.add_argument("--anno", type=int, default=2026)
    p_chiudi.add_argument(
        "--dry-run", action="store_true", help="Mostra senza salvare snapshot in BQ"
    )

    # saldo
    p_saldo = sub.add_parser("saldo", help="Saldo banca + proiezione cash forward")
    p_saldo.add_argument("--societa", choices=["ORTI", "INTUR"])
    p_saldo.add_argument("--anno", type=int, default=2026)

    # health
    sub.add_parser("health", help="Health check dati")

    # previsione
    p_prev = sub.add_parser(
        "previsione", aliases=["prev"], help="Aggiorna previsione budget"
    )
    p_prev.add_argument(
        "voce", help="Voce (alias o voce_id, es. 'utenze' o 'USCITE_UTENZE')"
    )
    p_prev.add_argument(
        "mesi", help="Range mesi: '4-12' o 'aprile-dicembre' o '6' (singolo)"
    )
    p_prev.add_argument("importo", type=float, help="Importo mensile in €")
    p_prev.add_argument("--societa", choices=["ORTI", "INTUR"], default="ORTI")
    p_prev.add_argument("--anno", type=int, default=2026)
    p_prev.add_argument("--fonte", default="CLI")
    p_prev.add_argument("--note", default=None)
    p_prev.add_argument("--dry-run", action="store_true")

    # voci
    sub.add_parser("voci", help="Lista voci piano finanziario")

    # manifest
    p_manifest = sub.add_parser("manifest", help="Genera catalogo tabelle BQ")
    p_manifest.add_argument("--table", help="Singola tabella (default: tutte)")
    p_manifest.add_argument(
        "--output", help="Output path (default: core/bq/manifest.yaml)"
    )

    # help
    sub.add_parser("help", help="Guida completa con esempi")

    # classifica
    p_class = sub.add_parser(
        "classifica", aliases=["cls"], help="Classifica, smista e ingerisci file"
    )
    p_class.add_argument("files", nargs="+", help="File da classificare")
    p_class.add_argument(
        "--route",
        action="store_true",
        help="Copia i file nella cartella datahub corretta",
    )
    p_class.add_argument(
        "--ingest",
        action="store_true",
        help="Esegui il pipeline di ingestione dopo lo smistamento",
    )
    p_class.add_argument("--datahub", help="Root del datahub (default: Google Drive)")
    p_class.add_argument(
        "--dry-run", action="store_true", help="Mostra il piano senza eseguire"
    )

    # scadenzario
    p_scad = sub.add_parser(
        "scadenzario", aliases=["scad"], help="Genera Excel ponte fornitori → voci PF"
    )
    p_scad.add_argument(
        "--file", type=Path, help="Sintetica scadenze Excel (default: BQ)"
    )
    p_scad.add_argument("--pf", type=Path, help="PF Excel di Rosa per gap analysis")
    p_scad.add_argument("--societa", choices=["ORTI", "INTUR"], default="ORTI")
    p_scad.add_argument(
        "--output", type=Path, help="Directory output (default: corrente)"
    )
    p_scad.add_argument(
        "--write-back",
        action="store_true",
        help="Write cascaded amounts back into --pf Excel (requires --pf and --file)",
    )

    # ingest
    p_ingest = sub.add_parser("ingest", help="Pipeline di ingestione dati")
    p_ingest.add_argument("--only", choices=["banca", "flussi", "dimensioni"],
                          help="Solo questo gruppo di pipeline")
    p_ingest.add_argument("--pipeline", type=str,
                          help="Solo questo pipeline specifico")
    p_ingest.add_argument("--dry-run", action="store_true",
                          help="Parse senza scrivere su BQ")
    p_ingest.add_argument("--no-sync", action="store_true",
                          help="Salta sync da Google Drive")
    p_ingest.add_argument("--gsheet", nargs="?", const=True, default=None,
                          help="Scarica da Google Sheet (per coperti)")
    p_ingest.add_argument("--replace", action="store_true",
                          help="DELETE-INSERT (sostituisce dati esistenti)")
    p_ingest.add_argument("--societa", choices=["ORTI", "INTUR"])

    # app
    p_app = sub.add_parser("app", help="Lancia app Streamlit")
    p_app.add_argument("app_name", nargs="?", default=None,
                       help="App da lanciare: pf (default), scadenzario")

    # reconcile
    p_rec = sub.add_parser("reconcile", help="Riconciliazione banca vs libro")
    p_rec.add_argument("--societa", required=True, choices=["ORTI", "INTUR"])
    p_rec.add_argument("--conto", required=True,
                       help="Conto banca (MPS, SELLA, INTESA, BCP, MPS_KROSS)")
    p_rec.add_argument("--from", dest="date_from", required=True,
                       help="Data inizio (YYYY-MM-DD)")
    p_rec.add_argument("--to", dest="date_to", required=True,
                       help="Data fine (YYYY-MM-DD)")
    p_rec.add_argument("--datahub", default=str(Path(
        "/Users/stefanodellapietra/Library/CloudStorage/"
        "GoogleDrive-stefano@panoramagroup.it/My Drive/hotelops_datahub"
    )), help="Path datahub root")
    p_rec.add_argument("--min-score", type=float, default=0.0,
                       help="Score minimo per match (0.0–1.0)")

    args = parser.parse_args()

    if not args.command:
        cmd_help(args)
        sys.exit(0)

    handlers = {
        "pf": cmd_pf,
        "bva": cmd_bva,
        "chiudi": cmd_chiudi,
        "saldo": cmd_saldo,
        "health": cmd_health,
        "previsione": cmd_previsione,
        "prev": cmd_previsione,
        "voci": cmd_voci,
        "manifest": cmd_manifest,
        "classifica": cmd_classifica,
        "cls": cmd_classifica,
        "scadenzario": cmd_scadenzario,
        "scad": cmd_scadenzario,
        "ingest": cmd_ingest,
        "app": cmd_app,
        "reconcile": cmd_reconcile,
        "help": cmd_help,
    }

    handlers[args.command](args)


if __name__ == "__main__":
    main()
