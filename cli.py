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
    hotelops manifest    Genera catalogo tabelle BigQuery
    hotelops classifica  Classifica, smista e ingerisci file dati
    hotelops drop        Stesso flusso smooth: smista + ingest (audit su Drive)
    hotelops ingest      Pipeline ingestione da datahub
    hotelops app         Dashboard Streamlit condges
    hotelops tesoreria   App Streamlit tesoreria (cashflow, PF, fornitori)
    hotelops reviews     Reviews ospiti: scrape, alert, report, dashboard
    hotelops docs        Check/verify documentazione tecnica
    hotelops accodamenti Accodamenti HotelCube → cassa giornaliera Excel
    hotelops reconcile   Riconciliazione banca e report Excel

Installazione:
    pip install -e .    (poi: hotelops pf)
    oppure: python -m cli pf

Richiede: gcloud auth (stefano@panoramagroup.it)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load .env from repo root into os.environ (idempotent, no deps).

    Manual loader invece di `python-dotenv` o `export $(... | xargs)` perché
    quest'ultimo splitta su spazi i valori (es. Gmail App Password formato
    'xxxx xxxx xxxx xxxx') — bug reale che ci ha fatto perdere un'ora.
    Formato: KEY=VALUE per riga, `#` per commenti, quote opzionali.
    Non sovrascrive var già presenti (shell vince).
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


# noqa: E402 — import after _load_dotenv() è intenzionale: i submodule possono
# leggere env var al toplevel, quindi .env va caricato prima.
from verticals.condges.cli_commands import (  # noqa: E402
    cmd_accodamenti,
    cmd_chiudi,
    cmd_docs,
    cmd_health,
    cmd_help,
    cmd_pf,
    cmd_saldo,
)
from core.bq.client import get_client  # noqa: E402
from core.config import PROJECT  # noqa: E402
from core.datahub_sync import DATAHUB_ROOT  # noqa: E402
from verticals.reviews.cli_commands import cmd_reviews  # noqa: E402
from workspace.cli_commands import cmd_workspace  # noqa: E402

# ── Lazy BQ client ──────────────────────────────────────────────────────────


def bq():
    return get_client()


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
    FROM `{PROJECT}.hotelops.v_budget_vs_consuntivo`
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
    from verticals.condges.update_previsione import update_previsione, resolve_voce

    voce_id = resolve_voce(args.voce) or args.voce.upper()
    societa = args.societa or "ORTI"
    anno = args.anno or 2026

    if "-" in args.mesi:
        parts = args.mesi.split("-")
        from verticals.condges.update_previsione import resolve_mese

        mese_start = resolve_mese(parts[0]) or int(parts[0])
        mese_end = resolve_mese(parts[1]) or int(parts[1])
    else:
        from verticals.condges.update_previsione import resolve_mese

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
            dest = route_file(
                r,
                datahub,
                dry_run=args.dry_run,
                use_rclone=not getattr(args, "locale", False),
            )
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


def cmd_drop(args):
    """Un solo passaggio: classifica → smista → ingest + audit JSONL (dedup resta in BQ)."""
    from pathlib import Path

    from ingest.classify import (
        DEFAULT_DATAHUB,
        append_drop_audit,
        classify_batch,
        file_md5_hex,
        route_file,
        run_ingest,
    )

    datahub = Path(args.datahub) if args.datahub else DEFAULT_DATAHUB
    use_rclone = not args.locale
    lineage_enabled = bool(getattr(args, "lineage", False))

    files = [Path(f) for f in args.files]
    expanded: list[Path] = []
    for f in files:
        if "*" in str(f) or "?" in str(f):
            import glob

            expanded.extend(Path(p) for p in glob.glob(str(f)))
        else:
            expanded.append(f)

    if not expanded:
        print("Nessun file trovato.")
        return

    print(f"\n{'═' * 70}")
    print("  DROP → classifica + smista + ingest  (BQ: APPEND dedup / SNAPSHOT)")
    if lineage_enabled:
        print("  Lineage: shadow ON (--lineage) — best-effort, non blocca")
    print(
        f"  Datahub: {datahub}  |  rclone: {'no (--locale)' if args.locale else 'sì'}"
    )
    print(f"{'═' * 70}\n")

    results = classify_batch(expanded)
    ok = unk = routed = ingested = 0

    for r in results:
        md5 = None
        if r.file_path.is_file():
            try:
                md5 = file_md5_hex(r.file_path)
            except OSError:
                pass

        if r.category in ("unknown", "error"):
            unk += 1
            print(f"❓ {r.file_path.name} — non riconosciuto")
            unk_record = {
                "file": str(r.file_path),
                "file_type": r.file_type,
                "status": "UNKNOWN",
                "md5": md5,
                "dry_run": args.dry_run,
            }
            if lineage_enabled:
                unk_record["lineage_enabled"] = True
                unk_record["lineage_raw_object_id"] = None
                unk_record["lineage_error"] = None
            append_drop_audit(datahub, unk_record)
            print()
            continue

        ok += 1
        emoji = "✅" if r.confidence >= 0.8 else "⚠️"
        print(f"{emoji} {r.file_path.name}  →  {r.file_type} / {r.category}")
        print(f"    {r.summary().strip()}")

        dest = route_file(r, datahub, dry_run=args.dry_run, use_rclone=use_rclone)
        route_ok = dest is not None
        ingest_ok = False
        lineage_raw_object_id: str | None = None
        lineage_error: str | None = None

        if route_ok:
            routed += 1
            prefix = "[DRY-RUN] " if args.dry_run else ""
            print(f"    {prefix}smistato → {dest}")

            # Phase 2 shadow lineage — best-effort, runs BEFORE legacy ingest.
            # Failures here NEVER block run_ingest; they're logged into audit only.
            if lineage_enabled and not args.dry_run:
                try:
                    from ingest.intake import intake_file
                    from core.lineage.source_resolver import load_registry

                    source_name: str | None = None
                    try:
                        reg = load_registry()
                        if r.societa:
                            match = reg.resolve(r.category, r.societa)
                            if match is not None:
                                source_name = match.source_name
                    except Exception:
                        # Resolver failure → fall back to source_name=None (RAW_ONLY).
                        source_name = None

                    intake_result = intake_file(
                        r.file_path,
                        source_name=source_name,
                        actor="drop_shadow",
                    )
                    lineage_raw_object_id = intake_result.raw_object_id
                    print(f"    lineage: ✓ raw_object_id={lineage_raw_object_id[:8]}…")
                except Exception as e:
                    lineage_error = str(e)[:300]
                    print(f"    lineage: ⚠ failed (best-effort): {lineage_error[:120]}")

            if not args.dry_run:
                ingest_ok = run_ingest(r, dest, datahub, dry_run=False)
                if ingest_ok:
                    ingested += 1
                print(f"    ingest: {'✅ OK' if ingest_ok else '❌ ERRORE'}")
            else:
                ingest_ok = run_ingest(r, dest, datahub, dry_run=True)
                print("    ingest: [DRY-RUN]")
        else:
            print("    ❌ smistamento fallito")

        if not route_ok:
            drop_status = "FAIL_ROUTE"
        elif args.dry_run:
            drop_status = "DRY_RUN"
        elif ingest_ok:
            drop_status = "OK"
        else:
            drop_status = "FAIL_INGEST"

        audit_record = {
            "file": str(r.file_path),
            "file_type": r.file_type,
            "category": r.category,
            "canonical": r.canonical_name,
            "dest_folder": r.dest_folder,
            "status": drop_status,
            "route_ok": route_ok,
            "ingest_ok": ingest_ok if route_ok else False,
            "md5": md5,
            "dry_run": args.dry_run,
        }
        if lineage_enabled:
            audit_record["lineage_enabled"] = True
            audit_record["lineage_raw_object_id"] = lineage_raw_object_id
            audit_record["lineage_error"] = lineage_error
        append_drop_audit(datahub, audit_record)
        print()

    print(f"{'─' * 70}")
    print(
        f"  Riconosciuti {ok}/{len(results)}  |  sconosciuti {unk}  |  "
        f"smistati {routed}  |  ingest OK {ingested}"
    )
    print(f"  Audit: {datahub / 'ingresso' / '_audit' / 'drops.jsonl'}")
    print(f"{'─' * 70}\n")


# ── Lineage subcommands (Phase 1 — additive) ──────────────────────────────────


def cmd_intake(args):
    """Register a file in the lineage layer (no canonical write)."""
    from pathlib import Path

    from ingest.intake import intake_file

    result = intake_file(
        Path(args.file),
        source_name=args.source_name,
        actor="cli",
    )
    print(f"raw_object_id: {result.raw_object_id}")
    print(f"content_hash:  {result.content_hash}")
    print(f"source_name:   {result.source_name or '(none)'}")


def cmd_promote(args):
    """Promote a PROMOTABLE raw_object to canonical via its source policy."""
    from ingest.promotion import promote_raw_object

    if args.raw_object_id:
        r = promote_raw_object(args.raw_object_id, actor="cli")
        print(
            f"status={r.status} reason={r.reason or '-'} rows={r.rows_written} noop={r.noop}"
        )
        if r.status == "REJECTED":
            sys.exit(2)
        return

    print("--all-promotable not yet implemented in Phase 1 (use --raw-object-id)")
    sys.exit(1)


def cmd_lineage(args):
    """Inspect a raw_object: identity + event history + current status."""
    from core.bq.client import get_client
    from core.lineage.raw_manifest import (
        F_LINEAGE_EVENTS,
        F_RAW_OBJECTS,
        V_RAW_OBJECTS_CURRENT,
    )
    from google.cloud import bigquery

    client = get_client()
    p = bigquery.ScalarQueryParameter("id", "STRING", args.raw_object_id)
    qc = bigquery.QueryJobConfig(query_parameters=[p])

    print("\n  Identity:")
    rows = list(
        client.query(
            f"SELECT * FROM `{F_RAW_OBJECTS}` WHERE raw_object_id = @id",
            job_config=qc,
        ).result()
    )
    if not rows:
        print(f"  ❌ raw_object_id not found: {args.raw_object_id}")
        sys.exit(1)
    r = rows[0]
    for k in (
        "source_name",
        "societa_id",
        "file_name_original",
        "intake_at",
        "raw_uri",
    ):
        print(f"    {k}: {getattr(r, k, '-')}")

    print("\n  Current status:")
    cur = list(
        client.query(
            f"SELECT current_status, last_event_at FROM `{V_RAW_OBJECTS_CURRENT}` "
            f"WHERE raw_object_id = @id",
            job_config=qc,
        ).result()
    )
    if cur:
        print(f"    {cur[0].current_status}  (last event: {cur[0].last_event_at})")

    print("\n  Event history:")
    events = list(
        client.query(
            f"SELECT event_type, event_at, actor, from_status, to_status, reason "
            f"FROM `{F_LINEAGE_EVENTS}` WHERE raw_object_id = @id ORDER BY event_at",
            job_config=qc,
        ).result()
    )
    for ev in events:
        transition = (
            f"{ev.from_status or '∅'} → {ev.to_status}"
            if ev.to_status
            else "(no transition)"
        )
        reason = f"  [{ev.reason}]" if ev.reason else ""
        print(f"    {ev.event_at}  {ev.event_type:<22s} {transition}{reason}")
    print()


def cmd_lineage_list(args):
    """List raw_objects filtered by status / source / age."""
    from core.bq.client import get_client
    from core.lineage.raw_manifest import F_RAW_OBJECTS, V_RAW_OBJECTS_CURRENT
    from google.cloud import bigquery

    where = ["1 = 1"]
    params = []
    status = getattr(args, "status", None)
    if status is not None and status != "":
        where.append("COALESCE(c.current_status, 'RAW_ONLY') = @status")
        params.append(bigquery.ScalarQueryParameter("status", "STRING", args.status))
    source = getattr(args, "source", None)
    if source is not None and source != "":
        where.append("r.source_name = @source")
        params.append(bigquery.ScalarQueryParameter("source", "STRING", args.source))
    days = getattr(args, "days", None)
    if days is not None:
        where.append(
            "r.intake_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)"
        )
        params.append(bigquery.ScalarQueryParameter("days", "INT64", args.days))

    limit = int(getattr(args, "limit", None) or 20)
    sql = f"""
    SELECT
      r.raw_object_id,
      r.source_name,
      COALESCE(c.current_status, 'RAW_ONLY') AS current_status,
      r.intake_at,
      r.file_name_original
    FROM `{F_RAW_OBJECTS}` r
    LEFT JOIN `{V_RAW_OBJECTS_CURRENT}` c USING (raw_object_id)
    WHERE {' AND '.join(where)}
    ORDER BY r.intake_at DESC
    LIMIT {limit}
    """
    client = get_client()
    qc = bigquery.QueryJobConfig(query_parameters=params)
    rows = list(client.query(sql, job_config=qc).result())

    if not rows:
        print("(no raw_objects match filters)")
        return

    print(
        f"{'raw_object_id':<38} {'status':<12} {'source':<32} {'intake_at':<25} file"
    )
    print("-" * 130)
    for row in rows:
        print(
            f"{row.raw_object_id:<38} "
            f"{str(row.current_status or '?'):<12} "
            f"{str(row.source_name or '-'):<32} "
            f"{str(row.intake_at):<25} "
            f"{row.file_name_original or '-'}"
        )


def cmd_lineage_dispatch(args):
    """Route --list vs single-id lineage inspection."""
    if getattr(args, "lineage_list", False):
        cmd_lineage_list(args)
        return
    if not args.raw_object_id:
        print(
            "ERROR: provide raw_object_id or use --list",
            file=sys.stderr,
        )
        sys.exit(2)
    cmd_lineage(args)


# ── Ingest ─────────────────────────────────────────────────────────────────


def cmd_ingest(args):
    """Ingest pipeline: wraps orchestrate.py or single pipelines."""
    # Special case: hotelops ingest coperti --gsheet
    if args.pipeline == "coperti" and args.gsheet:
        from ingest.flussi.ingest_coperti import (
            fetch_gsheet,
            parse_xlsx_file,
            load_to_bq,
            quality_summary,
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
        "pf": "verticals/condges/app_cdg.py",
        "scadenzario": "verticals/condges/app_scadenzario.py",
        "accodamenti": "verticals/condges/app_accodamenti.py",
        "reviews": "verticals/reviews/app.py",
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


def cmd_tesoreria(args):
    """Launch Streamlit tesoreria app."""
    import subprocess

    app_path = Path(__file__).parent / "verticals" / "condges" / "tesoreria.py"
    print("  Lancio: streamlit run verticals/condges/tesoreria.py")
    subprocess.run(["streamlit", "run", str(app_path)], check=True)


# ── Reconcile ──────────────────────────────────────────────────────────────


def cmd_reconcile(args):
    """Bank reconciliation."""
    from verticals.condges.reconcile_banca import run_reconciliation

    print(f"\n{'═' * 60}")
    print(f"  RICONCILIAZIONE BANCA  {args.societa} / {args.conto}")
    print(f"  Periodo: {args.date_from} → {args.date_to}")
    print(f"{'═' * 60}\n")

    try:
        metrics = run_reconciliation(
            args.datahub,
            args.societa,
            args.conto,
            args.date_from,
            args.date_to,
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
    p_class.add_argument(
        "--locale",
        action="store_true",
        help="Smista sul mount locale del datahub (senza rclone verso Drive remoto)",
    )

    p_drop = sub.add_parser(
        "drop",
        help="Flusso smooth: classifica + smista + ingest (audit in ingresso/_audit/)",
    )
    p_drop.add_argument("files", nargs="+", help="File da elaborare (anche glob)")
    p_drop.add_argument("--datahub", help="Root datahub (default: mount Google Drive)")
    p_drop.add_argument(
        "--locale",
        action="store_true",
        help="Solo copia locale sul datahub mount (niente upload rclone)",
    )
    p_drop.add_argument(
        "--dry-run", action="store_true", help="Piano senza scrittura Drive/BQ"
    )
    p_drop.add_argument(
        "--lineage",
        action="store_true",
        help="Phase 2 shadow: emette lineage in parallelo (best-effort, non blocca drop)",
    )

    # ingest
    p_ingest = sub.add_parser("ingest", help="Pipeline di ingestione dati")
    p_ingest.add_argument(
        "--only",
        choices=["banca", "flussi", "dimensioni"],
        help="Solo questo gruppo di pipeline",
    )
    p_ingest.add_argument("--pipeline", type=str, help="Solo questo pipeline specifico")
    p_ingest.add_argument(
        "--dry-run", action="store_true", help="Parse senza scrivere su BQ"
    )
    p_ingest.add_argument(
        "--no-sync", action="store_true", help="Salta sync da Google Drive"
    )
    p_ingest.add_argument(
        "--gsheet",
        nargs="?",
        const=True,
        default=None,
        help="Scarica da Google Sheet (per coperti)",
    )
    p_ingest.add_argument(
        "--replace",
        action="store_true",
        help="DELETE-INSERT (sostituisce dati esistenti)",
    )
    p_ingest.add_argument("--societa", choices=["ORTI", "INTUR"])

    # app
    p_app = sub.add_parser("app", help="Lancia app Streamlit")
    p_app.add_argument(
        "app_name",
        nargs="?",
        default=None,
        help="App da lanciare: pf (default), scadenzario, accodamenti, reviews",
    )

    # tesoreria
    sub.add_parser(
        "tesoreria", help="App Streamlit tesoreria (cashflow, PF, fornitori)"
    )

    # reviews
    p_reviews = sub.add_parser("reviews", help="Reviews ospiti: scrape, alert, stats")
    p_reviews.add_argument(
        "--scrape", action="store_true", help="Trigger scrape manuale"
    )
    p_reviews.add_argument(
        "--only",
        type=str,
        help="Solo questa piattaforma (booking, tripadvisor, google, expedia)",
    )
    p_reviews.add_argument(
        "--alert", action="store_true", help="Mostra review con alert"
    )
    p_reviews.add_argument("--stats", action="store_true", help="Statistiche review")
    p_reviews.add_argument("--mese", type=int, help="Mese per stats")
    p_reviews.add_argument("--anno", type=int, default=2026)
    p_reviews.add_argument(
        "--report", action="store_true", help="Invia report settimanale"
    )
    p_reviews.add_argument(
        "--start", type=str, help="Override start date report (YYYY-MM-DD)"
    )
    p_reviews.add_argument(
        "--end", type=str, help="Override end date report (YYYY-MM-DD)"
    )
    p_reviews.add_argument(
        "--dry-run", action="store_true", help="Preview senza azioni"
    )

    # docs
    p_docs = sub.add_parser("docs", help="Gestione doc tecniche del repo")
    p_docs.add_argument(
        "docs_action",
        nargs="?",
        default="check",
        choices=["check"],
        help="check: verifica freshness doc vs codice (default)",
    )

    # accodamenti
    p_acc = sub.add_parser(
        "accodamenti",
        aliases=["acc"],
        help="Accodamenti HotelCube → cassa giornaliera Excel",
    )
    p_acc.add_argument(
        "--input",
        help="Cartella TXT accodamenti (default: ~/.cache/hotelops/accodamenti/ORTI)",
    )
    p_acc.add_argument(
        "--output",
        help="Path Excel output (default: ~/Desktop/Riconciliazione_accodamenti.xlsx)",
    )
    p_acc.add_argument(
        "--no-sync", action="store_true", help="Salta rclone sync da Drive"
    )

    # reconcile
    p_rec = sub.add_parser("reconcile", help="Riconciliazione banca vs libro")
    p_rec.add_argument("--societa", required=True, choices=["ORTI", "INTUR"])
    p_rec.add_argument(
        "--conto",
        required=True,
        help="Conto banca (MPS, SELLA, INTESA, BCP, MPS_KROSS)",
    )
    p_rec.add_argument(
        "--from", dest="date_from", required=True, help="Data inizio (YYYY-MM-DD)"
    )
    p_rec.add_argument(
        "--to", dest="date_to", required=True, help="Data fine (YYYY-MM-DD)"
    )
    p_rec.add_argument("--datahub", default=str(DATAHUB_ROOT), help="Path datahub root")
    p_rec.add_argument(
        "--min-score", type=float, default=0.0, help="Score minimo per match (0.0–1.0)"
    )

    # ── Lineage subcommands (Phase 1) ──────────────────────────────────────
    p_intake = sub.add_parser(
        "intake",
        help="Lineage: registra un file (raw blob + RAW_INGESTED event)",
    )
    p_intake.add_argument("file", help="Path al file")
    p_intake.add_argument(
        "--source-name",
        default=None,
        help="source_name del registry (es. ESOLVER_BILANCINO_ORTI_SNAPSHOT)",
    )

    p_promote = sub.add_parser(
        "promote",
        help="Lineage: promuovi raw_object a canonical (parser + bq_write_validated)",
    )
    p_promote.add_argument("--raw-object-id", required=True)

    p_lin = sub.add_parser(
        "lineage", help="Lineage: ispeziona raw_object o lista con filtri"
    )
    p_lin.add_argument(
        "raw_object_id",
        nargs="?",
        default=None,
        help="ID singolo (ometti con --list)",
    )
    p_lin.add_argument(
        "--list",
        dest="lineage_list",
        action="store_true",
        help="Lista raw_objects con filtri",
    )
    p_lin.add_argument(
        "--status",
        choices=["RAW_ONLY", "CLASSIFIED", "PROMOTABLE", "PROMOTED", "REJECTED"],
        default=None,
    )
    p_lin.add_argument("--source", help="Filtra per source_name")
    p_lin.add_argument(
        "--days", type=int, default=None, help="Solo intake negli ultimi N giorni"
    )
    p_lin.add_argument(
        "--limit", type=int, default=20, help="Max righe in --list (default 20)"
    )

    # ── Workspace (Gmail/Drive via DWD service account) ─────────────────────
    p_ws = sub.add_parser(
        "workspace",
        help="Workspace API ops (Gmail/Drive via service account DWD)",
    )
    ws_sub = p_ws.add_subparsers(dest="workspace_action")
    p_mc = ws_sub.add_parser(
        "mine-capex",
        help="Mine email threads + attachments for a CapEx project",
    )
    p_mc.add_argument(
        "--project", required=True, help="Project code (es. HPAN25PIANO1)"
    )
    p_mc.add_argument(
        "--mailboxes",
        required=True,
        help="Comma-separated emails (es. gm@panoramagroup.it,amministrazione@panoramagroup.it)",
    )
    p_mc.add_argument(
        "--output-folder",
        required=True,
        help="Drive folder ID (must be accessible by --write-as user)",
    )
    p_mc.add_argument(
        "--write-as",
        default="stefano@panoramagroup.it",
        help="User to impersonate for Drive writes (needs storage quota). Default: stefano@panoramagroup.it",
    )
    p_mc.add_argument(
        "--keywords",
        help="Comma-separated project keywords (default: project-specific built-in)",
    )
    p_mc.add_argument(
        "--fuzzy",
        help="Comma-separated fuzzy keywords for Pass 3 (es. preventivo,offerta). Off by default.",
    )
    p_mc.add_argument(
        "--extra",
        help="Extra Gmail query filter appended to passes (es. 'after:2024/01/01')",
    )
    p_mc.add_argument(
        "--dry-run", action="store_true", help="Search only, no Drive uploads"
    )

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
        "drop": cmd_drop,
        "ingest": cmd_ingest,
        "app": cmd_app,
        "tesoreria": cmd_tesoreria,
        "docs": cmd_docs,
        "reconcile": cmd_reconcile,
        "accodamenti": cmd_accodamenti,
        "acc": cmd_accodamenti,
        "reviews": cmd_reviews,
        "help": cmd_help,
        "intake": cmd_intake,
        "promote": cmd_promote,
        "lineage": cmd_lineage_dispatch,
        "workspace": cmd_workspace,
    }

    handlers[args.command](args)


if __name__ == "__main__":
    main()
