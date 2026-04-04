"""Extracted CLI command handlers — large commands moved from cli.py to reduce file size."""

from __future__ import annotations

from core.schemas import ChiusuraMensileRow, validate_batch


# ── PF: Piano Finanziario mensile ───────────────────────────────────────────


def cmd_pf(args):
    """Piano Finanziario budget vs consuntivo."""
    from cli import query, fmt_eur

    societa = args.societa or "ORTI"
    anno = args.anno or 2026
    mese_filter = f"AND mese = {args.mese}" if args.mese else ""

    sql = f"""
    SELECT voce_id, voce_label, sezione, mese, tipo_periodo,
      ROUND(importo_consuntivo, 0) AS consuntivo,
      ROUND(importo_budget, 0) AS budget,
      ROUND(scostamento, 0) AS delta,
      scostamento_pct
    FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile`
    WHERE anno = {anno} AND societa_id = '{societa}'
      AND (importo_consuntivo != 0 OR importo_budget != 0)
      {mese_filter}
    ORDER BY mese, ord
    """
    rows = query(sql)

    if not rows:
        print(f"Nessun dato per {societa} {anno}")
        return

    current_mese = None
    tot_consuntivo_e = tot_budget_e = 0
    tot_consuntivo_u = tot_budget_u = 0

    for r in rows:
        mese = r["mese"]
        if mese != current_mese:
            if current_mese is not None:
                _print_subtotals(
                    fmt_eur,
                    tot_consuntivo_e, tot_budget_e, tot_consuntivo_u, tot_budget_u
                )
                tot_consuntivo_e = tot_budget_e = tot_consuntivo_u = tot_budget_u = 0
            current_mese = mese
            tipo = r["tipo_periodo"]
            print(f"\n{'─' * 75}")
            print(f"  MESE {mese:02d}/{anno}  ({tipo})")
            print(f"{'─' * 75}")
            print(f"  {'Voce':<35s} {'Consuntivo':>12s} {'Budget':>12s} {'Delta':>12s}")
            print(f"  {'─' * 35} {'─' * 12} {'─' * 12} {'─' * 12}")

        consuntivo = r["consuntivo"] or 0
        budget = r["budget"] or 0
        delta = r["delta"] or 0
        pct = r["scostamento_pct"]
        pct_str = f"{pct:+.0f}%" if pct is not None else ""

        # Color: red if over budget (uscite) or under budget (entrate)
        flag = ""
        if r["sezione"] == "USCITE" and delta > 0 and abs(delta) > 500:
            flag = " ⚠"
        elif r["sezione"] == "ENTRATE" and delta < 0 and abs(delta) > 500:
            flag = " ⚠"

        voce = r["voce_label"][:35]
        print(
            f"  {voce:<35s} {fmt_eur(consuntivo)} {fmt_eur(budget)} {fmt_eur(delta)} {pct_str}{flag}"
        )

        if r["sezione"] == "ENTRATE":
            tot_consuntivo_e += consuntivo
            tot_budget_e += budget
        else:
            tot_consuntivo_u += consuntivo
            tot_budget_u += budget

    _print_subtotals(
        fmt_eur, tot_consuntivo_e, tot_budget_e, tot_consuntivo_u, tot_budget_u
    )


def _print_subtotals(fmt_eur, ce, be, cu, bu):
    print(f"  {'─' * 35} {'─' * 12} {'─' * 12} {'─' * 12}")
    print(f"  {'ENTRATE TOTALI':<35s} {fmt_eur(ce)} {fmt_eur(be)} {fmt_eur(ce - be)}")
    print(f"  {'USCITE TOTALI':<35s} {fmt_eur(cu)} {fmt_eur(bu)} {fmt_eur(cu - bu)}")
    netto_c = ce - cu
    netto_b = be - bu
    print(
        f"  {'CASH FLOW NETTO':<35s} {fmt_eur(netto_c)} {fmt_eur(netto_b)} {fmt_eur(netto_c - netto_b)}"
    )


# ── Health check ───────────────────────────────────────────────────────────


def cmd_health(args):
    """Health check: freshness dati, gap, alert."""
    from cli import query, fmt_eur, bq

    print("\n  ═══ HEALTH CHECK ═══\n")

    # Banche freshness
    rows = query("""
    SELECT banca_id, societa_id, MAX(data_operazione) AS ultima,
      DATE_DIFF(CURRENT_DATE('Europe/Rome'), MAX(data_operazione), DAY) AS giorni
    FROM hotelops.f_banche_movimenti
    GROUP BY 1, 2 ORDER BY giorni DESC
    """)
    print("  BANCHE:")
    for r in rows:
        flag = "⚠" if r["giorni"] > 7 else "✓"
        print(
            f"    {flag} {r['societa_id']}/{r['banca_id']}: ultima {r['ultima']} ({r['giorni']}gg fa)"
        )

    # Movimenti freshness
    rows = query("""
    SELECT societa_id, MAX(data_registrazione) AS ultima,
      DATE_DIFF(CURRENT_DATE('Europe/Rome'), MAX(data_registrazione), DAY) AS giorni
    FROM hotelops.f_movimenti_contabili GROUP BY 1
    """)
    print("\n  MOVIMENTI CONTABILI:")
    for r in rows:
        flag = "⚠" if r["giorni"] > 14 else "✓"
        print(
            f"    {flag} {r['societa_id']}: ultima {r['ultima']} ({r['giorni']}gg fa)"
        )

    # Budget loaded
    rows = query("""
    SELECT fonte, COUNT(*) AS righe, COUNT(DISTINCT codice_conto) AS conti,
      ROUND(SUM(importo), 0) AS totale
    FROM hotelops.f_budget_mensile WHERE anno = 2026 GROUP BY 1
    """)
    print("\n  BUDGET 2026:")
    for r in rows:
        print(
            f"    ✓ {r['fonte']}: {r['righe']} righe, {r['conti']} conti, {fmt_eur(r['totale'])}/anno"
        )

    # PF input
    rows = query("""
    SELECT fonte, societa_id, COUNT(*) AS righe, COUNT(DISTINCT voce_id) AS voci
    FROM hotelops.f_piano_finanziario_input WHERE anno = 2026
    GROUP BY 1, 2
    """)
    print("\n  PIANO FINANZIARIO INPUT:")
    for r in rows:
        print(
            f"    ✓ {r['fonte']} {r['societa_id']}: {r['righe']} righe, {r['voci']} voci"
        )

    # Dimension tables
    for table, label in [
        ("d_voci_piano_finanziario", "Voci PF"),
        ("d_piano_conti", "Piano dei Conti"),
        ("d_categorie_conti", "Categorie"),
    ]:
        rows = query(f"SELECT COUNT(*) AS n FROM hotelops.{table}")
        n = rows[0]["n"] if rows else 0
        print(f"\n  {label}: {n} righe")

    # Schema drift check: BQ columns vs Pydantic models
    from core.schemas import (
        BancaMovimentoRow,
        BudgetMensileRow,
        ChiusuraMensileRow,
        MovimentoContabileRow,
        PartitaApertaFornitoreRow,
        PianoFinanziarioInputRow,
    )
    from core import config as cfg

    drift_checks = [
        (cfg.F_BANCHE_MOVIMENTI, BancaMovimentoRow),
        (cfg.F_MOVIMENTI_CONTABILI, MovimentoContabileRow),
        (cfg.F_BUDGET_MENSILE, BudgetMensileRow),
        (cfg.F_PIANO_FINANZIARIO_INPUT, PianoFinanziarioInputRow),
        (cfg.F_CHIUSURA_MENSILE, ChiusuraMensileRow),
        (cfg.F_PARTITE_APERTE_FORNITORI, PartitaApertaFornitoreRow),
    ]
    print("\n  SCHEMA DRIFT:")
    for table_id, model in drift_checks:
        try:
            bq_cols = {f.name for f in bq().get_table(table_id).schema}
            py_cols = set(model.model_fields.keys())
            extra_bq = bq_cols - py_cols
            extra_py = py_cols - bq_cols
            name = table_id.split(".")[-1]
            if extra_bq or extra_py:
                print(
                    f"    ⚠ {name}: BQ+{sorted(extra_bq)} / Pydantic+{sorted(extra_py)}"
                )
            else:
                print(f"    ✓ {name}")
        except Exception as e:
            print(f"    ? {table_id.split('.')[-1]}: {e}")


# ── Saldo banca helper ────────────────────────────────────────────────────


def _compute_saldo_banca(societa: str, as_of_date: str) -> tuple[float, list[dict]]:
    """Real bank balance at end of as_of_date via nearest snapshot + movement delta.

    For each bank with a snapshot >= as_of_date: saldo = anchor_saldo - sum(movements
    between as_of_date+1 and anchor_date).  Falls back to cumulative sum if no snapshots.

    Returns (total, [{banca_id, saldo, anchor_date, note}]).
    """
    from cli import query, BQ_PROJECT

    try:
        rows = query(f"""
        WITH anchors AS (
          SELECT banca_id, data_snapshot AS anchor_date, saldo_finale AS anchor_saldo
          FROM (
            SELECT banca_id, data_snapshot, saldo_finale,
              ROW_NUMBER() OVER (PARTITION BY banca_id ORDER BY data_snapshot ASC) AS rn
            FROM `{BQ_PROJECT}.hotelops.f_saldi_banca_snapshot`
            WHERE societa_id = '{societa}'
              AND data_snapshot >= DATE('{as_of_date}')
          )
          WHERE rn = 1
        ),
        deltas AS (
          SELECT m.banca_id,
            ROUND(SUM(m.importo_netto), 2) AS delta
          FROM `{BQ_PROJECT}.hotelops.f_banche_movimenti` m
          JOIN anchors a USING (banca_id)
          WHERE m.societa_id = '{societa}'
            AND m.data_operazione > DATE('{as_of_date}')
            AND m.data_operazione <= a.anchor_date
          GROUP BY m.banca_id
        )
        SELECT a.banca_id, a.anchor_date,
          ROUND(a.anchor_saldo - COALESCE(d.delta, 0), 0) AS saldo,
          'ANCHOR' AS note
        FROM anchors a
        LEFT JOIN deltas d USING (banca_id)
        """)
        if rows:
            return sum(r["saldo"] for r in rows), rows
    except Exception:
        pass
    # Fallback: cumulative sum (no opening balance -- inaccurate)
    rows = query(f"""
    SELECT banca_id,
      ROUND(SUM(importo_netto), 0) AS saldo,
      MAX(data_operazione) AS anchor_date,
      'CUMSUM' AS note
    FROM `{BQ_PROJECT}.hotelops.f_banche_movimenti`
    WHERE societa_id = '{societa}'
      AND data_operazione <= DATE('{as_of_date}')
    GROUP BY banca_id
    """)
    return sum(r["saldo"] for r in rows), rows


# ── Chiudi: chiusura mensile ────────────────────────────────────────────────


def cmd_chiudi(args):
    """Chiusura mese: confronta previsione vs consuntivo + saldo banca + salva snapshot."""
    from cli import query, fmt_eur
    from datetime import date

    today = date.today()
    mese_chiuso = args.mese or (today.month - 1 if today.month > 1 else 12)
    anno = args.anno or (today.year if today.month > 1 else today.year - 1)
    societa = args.societa or "ORTI"
    save = not args.dry_run

    print(f"\n  ═══ CHIUSURA MESE {mese_chiuso:02d}/{anno} — {societa} ═══\n")

    # 1. Forecast vs Actual per voce
    sql = f"""
    SELECT voce_id, voce_label, sezione,
      ROUND(importo_consuntivo, 0) AS consuntivo,
      ROUND(importo_budget, 0) AS budget,
      ROUND(scostamento, 0) AS delta,
      scostamento_pct
    FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile`
    WHERE anno = {anno} AND mese = {mese_chiuso} AND societa_id = '{societa}'
      AND (importo_consuntivo != 0 OR importo_budget != 0)
    ORDER BY ord
    """
    rows = query(sql)

    if not rows:
        print(f"  Nessun dato per mese {mese_chiuso}/{anno}")
        return

    current_sez = None
    tot_c_e = tot_b_e = tot_c_u = tot_b_u = 0
    snapshot_rows = []

    print(
        f"  {'Voce':<32s} {'Consuntivo':>11s} {'Previsione':>11s} {'Delta':>11s}  {'%':>6s}"
    )
    print(f"  {'─' * 32} {'─' * 11} {'─' * 11} {'─' * 11}  {'─' * 6}")

    for r in rows:
        sez = r["sezione"]
        if sez != current_sez:
            current_sez = sez
            print(f"\n  ── {sez} ──")

        c = r["consuntivo"] or 0
        b = r["budget"] or 0
        d = r["delta"] or 0
        pct = r["scostamento_pct"]
        pct_s = f"{pct:+.0f}%" if pct is not None else ""

        # Flag: ⚠ if actual > budget (uscite) or actual < budget (entrate)
        flag = ""
        if sez == "USCITE" and d > 2000:
            flag = " ⚠ SFORATO"
        elif sez == "ENTRATE" and d < -2000:
            flag = " ⚠ MANCATO"

        voce = r["voce_label"][:32]
        print(
            f"  {voce:<32s} {fmt_eur(c)} {fmt_eur(b)} {fmt_eur(d)}  {pct_s:>6s}{flag}"
        )

        if sez == "ENTRATE":
            tot_c_e += c
            tot_b_e += b
        else:
            tot_c_u += c
            tot_b_u += b

        # Collect for snapshot
        snapshot_rows.append(
            {
                "societa_id": societa,
                "anno": anno,
                "mese": mese_chiuso,
                "voce_id": r["voce_id"],
                "voce_label": r["voce_label"],
                "sezione": sez,
                "importo_consuntivo": float(c),
                "importo_previsione": float(b),
                "delta": float(d),
                "delta_pct": float(pct) if pct is not None else None,
                "data_chiusura": today.isoformat(),
            }
        )

    print(f"\n  {'─' * 80}")
    print(
        f"  {'ENTRATE TOTALI':<32s} {fmt_eur(tot_c_e)} {fmt_eur(tot_b_e)} {fmt_eur(tot_c_e - tot_b_e)}"
    )
    print(
        f"  {'USCITE TOTALI':<32s} {fmt_eur(tot_c_u)} {fmt_eur(tot_b_u)} {fmt_eur(tot_c_u - tot_b_u)}"
    )
    cf_c = tot_c_e - tot_c_u
    cf_b = tot_b_e - tot_b_u
    print(
        f"  {'CASH FLOW NETTO':<32s} {fmt_eur(cf_c)} {fmt_eur(cf_b)} {fmt_eur(cf_c - cf_b)}"
    )

    # 2. Saldo banca (anchor-based)
    import calendar

    last_day = calendar.monthrange(anno, mese_chiuso)[1]
    as_of_date = f"{anno}-{mese_chiuso:02d}-{last_day:02d}"
    print(f"\n  ── SALDO BANCA al {last_day:02d}/{mese_chiuso:02d}/{anno} ──")
    totale_banca, saldo_detail = _compute_saldo_banca(societa, as_of_date)
    for r in saldo_detail:
        method = "" if r.get("note") == "ANCHOR" else " (stima)"
        print(f"    {r['banca_id']:<12s} {fmt_eur(r['saldo'])}{method}")
    print(f"    {'TOTALE':<12s} {fmt_eur(totale_banca)}")

    # Add saldo_banca to snapshot rows
    for sr in snapshot_rows:
        sr["saldo_banca_fine_mese"] = float(totale_banca)

    # 3. Quick forward look
    print("\n  ── PROIEZIONE PROSSIMI 3 MESI ──")
    # Handle December: look into next year
    if mese_chiuso >= 10:
        fwd_sql = f"""
        SELECT mese, anno AS fwd_anno,
          ROUND(SUM(CASE WHEN sezione = 'ENTRATE' THEN importo_budget ELSE 0 END), 0) AS entrate_prev,
          ROUND(SUM(CASE WHEN sezione = 'USCITE' THEN importo_budget ELSE 0 END), 0) AS uscite_prev
        FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile`
        WHERE societa_id = '{societa}'
          AND ((anno = {anno} AND mese > {mese_chiuso})
               OR (anno = {anno + 1} AND mese <= {(mese_chiuso + 3) % 12 or 12}))
        GROUP BY mese, anno ORDER BY anno, mese
        """
    else:
        fwd_sql = f"""
        SELECT mese, {anno} AS fwd_anno,
          ROUND(SUM(CASE WHEN sezione = 'ENTRATE' THEN importo_budget ELSE 0 END), 0) AS entrate_prev,
          ROUND(SUM(CASE WHEN sezione = 'USCITE' THEN importo_budget ELSE 0 END), 0) AS uscite_prev
        FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile`
        WHERE anno = {anno} AND societa_id = '{societa}'
          AND mese BETWEEN {mese_chiuso + 1} AND {min(mese_chiuso + 3, 12)}
        GROUP BY mese ORDER BY mese
        """
    fwd_rows = query(fwd_sql)
    saldo_running = totale_banca
    for r in fwd_rows:
        netto = (r["entrate_prev"] or 0) - (r["uscite_prev"] or 0)
        saldo_running += netto
        fwd_anno = r.get("fwd_anno", anno)
        danger = (
            " ⛔ PERICOLO"
            if saldo_running < 0
            else (" ⚠ ATTENZIONE" if saldo_running < 50000 else "")
        )
        print(
            f"    Mese {r['mese']:02d}/{fwd_anno}: entrate {fmt_eur(r['entrate_prev'])} - uscite {fmt_eur(r['uscite_prev'])} = netto {fmt_eur(netto)} → saldo {fmt_eur(saldo_running)}{danger}"
        )

    if not fwd_rows:
        print("    (nessuna previsione disponibile per i prossimi mesi)")

    # 4. Save snapshot to BQ
    if save and snapshot_rows:
        _save_chiusura_snapshot(societa, anno, mese_chiuso, snapshot_rows)
    elif not save:
        print("\n  ℹ DRY RUN — snapshot NON salvato. Usa senza --dry-run per salvare.")


def _save_chiusura_snapshot(societa: str, anno: int, mese: int, rows: list[dict]):
    """Save monthly close snapshot to f_chiusura_mensile (DELETE-INSERT)."""
    from cli import bq, BQ_PROJECT
    from google.cloud import bigquery as bq_lib

    table_id = f"{BQ_PROJECT}.hotelops.f_chiusura_mensile"
    client = bq()

    # Ensure table exists
    try:
        client.get_table(table_id)
    except Exception:
        schema = [
            bq_lib.SchemaField("societa_id", "STRING"),
            bq_lib.SchemaField("anno", "INTEGER"),
            bq_lib.SchemaField("mese", "INTEGER"),
            bq_lib.SchemaField("voce_id", "STRING"),
            bq_lib.SchemaField("voce_label", "STRING"),
            bq_lib.SchemaField("sezione", "STRING"),
            bq_lib.SchemaField("importo_consuntivo", "FLOAT"),
            bq_lib.SchemaField("importo_previsione", "FLOAT"),
            bq_lib.SchemaField("delta", "FLOAT"),
            bq_lib.SchemaField("delta_pct", "FLOAT"),
            bq_lib.SchemaField("saldo_banca_fine_mese", "FLOAT"),
            bq_lib.SchemaField("data_chiusura", "DATE"),
        ]
        table = bq_lib.Table(table_id, schema=schema)
        client.create_table(table)
        print(f"\n  ✓ Tabella {table_id} creata")

    # DELETE existing snapshot for this month
    delete_sql = f"""
    DELETE FROM `{table_id}`
    WHERE societa_id = '{societa}' AND anno = {anno} AND mese = {mese}
    """
    client.query(delete_sql).result()

    # INSERT new snapshot
    validate_batch(rows, ChiusuraMensileRow, "f_chiusura_mensile")
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        print(f"\n  ✗ Errori inserimento snapshot: {errors[:3]}")
    else:
        print(
            f"\n  ✓ Snapshot salvato: {len(rows)} righe → f_chiusura_mensile ({societa} {mese:02d}/{anno})"
        )
        print("    Nel tempo: hotelops chiudi mostra se le previsioni migliorano")


# ── Saldo: posizione banca corrente + proiezione ──────────────────────────


def cmd_saldo(args):
    """Saldo banca reale (da snapshot) + proiezione cash forward via v_previsione_cassa."""
    from cli import query, fmt_eur, BQ_PROJECT

    societa = args.societa or "ORTI"

    rows = query(f"""
    SELECT periodo, tipo_periodo, saldo_ancora, data_ancora,
           entrate, uscite_pf, uscite_scad, n_fatture_scad,
           netto_pf, saldo_proiettato, stato_liquidita
    FROM `{BQ_PROJECT}.hotelops.v_previsione_cassa`
    WHERE societa_id = '{societa}'
    ORDER BY anno, mese
    """)

    if not rows:
        print(
            f"\n  ⚠ Nessun dato per {societa}. Inserisci prima il saldo banca in f_saldi_banca_snapshot."
        )
        return

    ancora = rows[0]
    print(f"\n  ═══ POSIZIONE DI CASSA — {societa} ═══")
    print(f"  Ancora: {fmt_eur(ancora['saldo_ancora'])} al {ancora['data_ancora']}\n")

    print(
        f"  {'Mese':<8} {'Tipo':10} {'Entrate':>11} {'Uscite PF':>11} {'Scad.':>9} {'Netto':>10} {'Saldo':>12} {'Stato'}"
    )
    print(
        f"  {'─' * 8} {'─' * 10} {'─' * 11} {'─' * 11} {'─' * 9} {'─' * 10} {'─' * 12} {'─' * 9}"
    )

    for r in rows:
        tipo_tag = (
            "📊"
            if r["tipo_periodo"] == "CONSUNTIVO"
            else ("🔄" if r["tipo_periodo"] == "CORRENTE" else "🔮")
        )
        stato = {"PERICOLO": "⛔ PERICOLO", "ATTENZIONE": "⚠ BASSO", "OK": ""}.get(
            r["stato_liquidita"], ""
        )
        scad = f"{r['uscite_scad']:>9,.0f}" if r["uscite_scad"] else "         -"
        print(
            f"  {tipo_tag} {r['periodo']:8} "
            f"{r['entrate'] or 0:>11,.0f} "
            f"{r['uscite_pf'] or 0:>11,.0f} "
            f"{scad} "
            f"{r['netto_pf'] or 0:>10,.0f} "
            f"{r['saldo_proiettato']:>12,.0f} "
            f"{stato}"
        )

    print("\n  📊=consuntivo  🔄=mese corrente  🔮=previsione")
    print("  Scad. = uscite certe da scadenzario fornitori (non entra nel saldo)")


# ── Scadenzario ──────────────────────────────────────────────────────────


def cmd_scadenzario(args):
    """Genera Excel ponte: scadenzario fornitori → voci PF."""
    print(f"\n{'═' * 60}")
    print(f"  SCADENZARIO → PIANO FINANZIARIO ({args.societa})")
    print(f"{'═' * 60}\n")

    if args.write_back:
        from condges.scadenzario_excel import (
            cascade_scaduto,
            load_fornitori_map,
            load_fornitori_map_full,
            map_to_voci,
            parse_sintetica_scadenze,
            write_back_to_pf,
            MESI_NOMI,
        )

        if not args.pf:
            print("  ❌ --write-back requires --pf <PF Excel path>")
            return
        if not args.file:
            print("  ❌ --write-back requires --file <sintetica Excel path>")
            return

        print(f"  Sintetica: {args.file}")
        print(f"  PF Excel:  {args.pf}")

        partite, bucket_months = parse_sintetica_scadenze(args.file)
        print(f"  Fornitori trovati: {len(partite)}")

        cascade_scaduto(partite)
        print("  ✓ Scaduto cascaded into current month")

        fornitori_map = load_fornitori_map()
        mapped, unmapped = map_to_voci(partite, fornitori_map)
        print(
            f"  Mappati: {sum(len(v) for v in mapped.values())} | Non mappati: {len(unmapped)}"
        )

        fornitori_full = load_fornitori_map_full()
        out, summary = write_back_to_pf(args.pf, mapped, fornitori_full)

        # Print results
        print(f"\n  {'─' * 56}")
        total_written = 0
        for voce_label, entries in sorted(summary.items()):
            voce_total = sum(sum(e["months"].values()) for e in entries)
            total_written += voce_total
            print(f"  {voce_label}: {len(entries)} fornitori, €{voce_total:,.0f}")
            for e in entries:
                month_detail = ", ".join(
                    f"{MESI_NOMI[m - 1]}=€{v:,.0f}"
                    for m, v in sorted(e["months"].items())
                )
                print(f"    {e['nome']}: {month_detail}")
        print(f"  {'─' * 56}")
        print(f"  Totale scritto: €{total_written:,.0f}")

        print(f"\n  ✅ PF aggiornato: {out}")
        if unmapped:
            print(f"  ⚠️  {len(unmapped)} fornitori non mappati (non scritti):")
            for u in unmapped[:5]:
                print(
                    f"     - {u['codice_fornitore']} {u['nome']}: €{u['totale']:,.0f}"
                )
            if len(unmapped) > 5:
                print(f"     ... e altri {len(unmapped) - 5}")
    else:
        from condges.scadenzario_excel import run

        if args.file:
            print(f"  Input: {args.file}")
        else:
            print("  Input: BigQuery (ultimo snapshot)")
        if args.pf:
            print(f"  PF Rosa: {args.pf}")

        out = run(
            file=args.file,
            pf=args.pf,
            societa=args.societa,
            output=args.output,
        )
        print(f"\n  ✅ Excel generato: {out}")

    print(f"{'═' * 60}\n")


# ── Help ─────────────────────────────────────────────────────────────────


def cmd_help(args):
    """Mostra tutti i comandi disponibili con esempi."""
    text = """
╔══════════════════════════════════════════════════════════════════════════╗
║  hotelops — control plane per il financial model Gruppo Panorama       ║
╚══════════════════════════════════════════════════════════════════════════╝

 ANALISI
 ───────
  pf              Piano Finanziario mensile (budget vs consuntivo, 28 voci)
                    hotelops pf                      tutti i mesi ORTI
                    hotelops pf --mese 4             solo aprile
                    hotelops pf --societa INTUR      INTUR

  bva             Budget vs Consuntivo per codice conto (Gasparotto)
                    hotelops bva                     YTD, top 30 delta
                    hotelops bva --mese 3            solo marzo
                    hotelops bva --limit 50          top 50

  saldo           Saldo banca corrente + proiezione cash forward 12 mesi
                    hotelops saldo                   ORTI
                    hotelops saldo --societa INTUR   INTUR

  health          Health check: freshness dati, gaps, alert
                    hotelops health

 AZIONI
 ──────
  chiudi          Chiusura mese: previsione vs consuntivo + saldo banca
                    hotelops chiudi                  mese precedente
                    hotelops chiudi --mese 2 --dry-run

  previsione      Aggiorna previsione budget per una voce PF
    (alias: prev)   hotelops previsione utenze 4-12 22000
                    hotelops prev "entrate hotel" aprile-ottobre 180000
                    hotelops prev mutui 1-12 45000 --societa INTUR

 INGEST
 ──────
  ingest          Pipeline di ingestione dati
                    hotelops ingest                      tutto (sync + ingest)
                    hotelops ingest --only banca         solo banca
                    hotelops ingest --only flussi        solo flussi contabili
                    hotelops ingest --pipeline coperti   singolo pipeline
                    hotelops ingest --pipeline coperti --gsheet   da Google Sheet
                    hotelops ingest --dry-run            parse senza scrivere BQ

 APP
 ───
  app             App Streamlit
                    hotelops app                         Piano Finanziario
                    hotelops app scadenzario             Scadenzario → PF

  reconcile       Riconciliazione banca vs libro
                    hotelops reconcile --societa INTUR --conto SELLA \\
                      --from 2025-01-01 --to 2025-01-31

 UTILITÀ
 ───────
  voci            Lista voci piano finanziario disponibili (28 voci)
                    hotelops voci

  classifica      Classifica, smista e ingerisci file dati
    (alias: cls)    hotelops classifica file1.xlsx file2.csv
                    hotelops cls *.xlsx --route --ingest
                    hotelops cls report.xlsx --dry-run

  scadenzario     Excel ponte: scadenzario fornitori → voci PF
    (alias: scad)   hotelops scad --file sintetica.xlsx
                    hotelops scad --file sintetica.xlsx --pf PF_aprile.xlsx
                    hotelops scad --output ~/Desktop/

  manifest        Catalogo tabelle BigQuery
                    hotelops manifest
                    hotelops manifest --table f_consumi_economato

  help            Questa guida
                    hotelops help

 OPZIONI GLOBALI
 ───────────────
  --societa       ORTI (default) | INTUR
  --anno          Anno di riferimento (default: 2026)
  --mese          Mese specifico (default: tutti / YTD)
  --dry-run       Mostra senza scrivere in BigQuery

 SETUP
 ─────
  pip install -e .          installa il comando hotelops
  gcloud auth login         autenticazione GCP (stefano@panoramagroup.it)
"""
    print(text)
