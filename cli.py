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

Installazione:
    pip install -e .    (poi: hotelops pf)
    oppure: python -m cli pf

Richiede: gcloud auth (stefano@panoramagroup.it)
"""

from __future__ import annotations

import argparse
import sys

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


# ── PF: Piano Finanziario mensile ───────────────────────────────────────────

def cmd_pf(args):
    """Piano Finanziario budget vs consuntivo."""
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
                _print_subtotals(tot_consuntivo_e, tot_budget_e, tot_consuntivo_u, tot_budget_u)
                tot_consuntivo_e = tot_budget_e = tot_consuntivo_u = tot_budget_u = 0
            current_mese = mese
            tipo = r["tipo_periodo"]
            print(f"\n{'─'*75}")
            print(f"  MESE {mese:02d}/{anno}  ({tipo})")
            print(f"{'─'*75}")
            print(f"  {'Voce':<35s} {'Consuntivo':>12s} {'Budget':>12s} {'Delta':>12s}")
            print(f"  {'─'*35} {'─'*12} {'─'*12} {'─'*12}")

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
        print(f"  {voce:<35s} {fmt_eur(consuntivo)} {fmt_eur(budget)} {fmt_eur(delta)} {pct_str}{flag}")

        if r["sezione"] == "ENTRATE":
            tot_consuntivo_e += consuntivo
            tot_budget_e += budget
        else:
            tot_consuntivo_u += consuntivo
            tot_budget_u += budget

    _print_subtotals(tot_consuntivo_e, tot_budget_e, tot_consuntivo_u, tot_budget_u)


def _print_subtotals(ce, be, cu, bu):
    print(f"  {'─'*35} {'─'*12} {'─'*12} {'─'*12}")
    print(f"  {'ENTRATE TOTALI':<35s} {fmt_eur(ce)} {fmt_eur(be)} {fmt_eur(ce-be)}")
    print(f"  {'USCITE TOTALI':<35s} {fmt_eur(cu)} {fmt_eur(bu)} {fmt_eur(cu-bu)}")
    netto_c = ce - cu
    netto_b = be - bu
    print(f"  {'CASH FLOW NETTO':<35s} {fmt_eur(netto_c)} {fmt_eur(netto_b)} {fmt_eur(netto_c-netto_b)}")


# ── BVA: Budget vs Consuntivo per conto ─────────────────────────────────────

def cmd_bva(args):
    """Budget vs Consuntivo per codice conto."""
    societa = args.societa or "ORTI"
    anno = args.anno or 2026
    mese = args.mese

    mese_filter = f"AND mese = {mese}" if mese else "AND mese <= EXTRACT(MONTH FROM CURRENT_DATE('Europe/Rome'))"

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
    print(f"  {'Codice':<12s} {'Descrizione':<30s} {'Budget':>10s} {'Actual':>10s} {'Delta':>10s} {'Status'}")
    print(f"  {'─'*12} {'─'*30} {'─'*10} {'─'*10} {'─'*10} {'─'*12}")

    for r in rows:
        codice = (r["codice_conto_display"] or "???")[:12]
        desc = (r["descrizione"] or "")[:30]
        print(f"  {codice:<12s} {desc:<30s} {fmt_eur(r['budget'])} {fmt_eur(r['consuntivo'])} {fmt_eur(r['delta'])} {r['status']}")


# ── Health check ────────────────────────────────────────────────────────────

def cmd_health(args):
    """Health check: freshness dati, gap, alert."""
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
        print(f"    {flag} {r['societa_id']}/{r['banca_id']}: ultima {r['ultima']} ({r['giorni']}gg fa)")

    # Movimenti freshness
    rows = query("""
    SELECT societa_id, MAX(data_registrazione) AS ultima,
      DATE_DIFF(CURRENT_DATE('Europe/Rome'), MAX(data_registrazione), DAY) AS giorni
    FROM hotelops.f_movimenti_contabili GROUP BY 1
    """)
    print("\n  MOVIMENTI CONTABILI:")
    for r in rows:
        flag = "⚠" if r["giorni"] > 14 else "✓"
        print(f"    {flag} {r['societa_id']}: ultima {r['ultima']} ({r['giorni']}gg fa)")

    # Budget loaded
    rows = query("""
    SELECT fonte, COUNT(*) AS righe, COUNT(DISTINCT codice_conto) AS conti,
      ROUND(SUM(importo), 0) AS totale
    FROM hotelops.f_budget_mensile WHERE anno = 2026 GROUP BY 1
    """)
    print("\n  BUDGET 2026:")
    for r in rows:
        print(f"    ✓ {r['fonte']}: {r['righe']} righe, {r['conti']} conti, {fmt_eur(r['totale'])}/anno")

    # PF input
    rows = query("""
    SELECT fonte, societa_id, COUNT(*) AS righe, COUNT(DISTINCT voce_id) AS voci
    FROM hotelops.f_piano_finanziario_input WHERE anno = 2026
    GROUP BY 1, 2
    """)
    print("\n  PIANO FINANZIARIO INPUT:")
    for r in rows:
        print(f"    ✓ {r['fonte']} {r['societa_id']}: {r['righe']} righe, {r['voci']} voci")

    # Dimension tables
    for table, label in [
        ("d_voci_piano_finanziario", "Voci PF"),
        ("d_piano_conti", "Piano dei Conti"),
        ("d_categorie_conti", "Categorie"),
    ]:
        rows = query(f"SELECT COUNT(*) AS n FROM hotelops.{table}")
        n = rows[0]["n"] if rows else 0
        print(f"\n  {label}: {n} righe")


# ── Previsione ──────────────────────────────────────────────────────────────

def cmd_previsione(args):
    """Inserisci/aggiorna previsione budget."""
    from actions.update_previsione import update_previsione, resolve_voce

    voce_id = resolve_voce(args.voce) or args.voce.upper()
    societa = args.societa or "ORTI"
    anno = args.anno or 2026

    if "-" in args.mesi:
        parts = args.mesi.split("-")
        from actions.update_previsione import resolve_mese
        mese_start = resolve_mese(parts[0]) or int(parts[0])
        mese_end = resolve_mese(parts[1]) or int(parts[1])
    else:
        from actions.update_previsione import resolve_mese
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
    print(f"  €{args.importo:,.0f}/mese × {n_mesi} mesi (mesi {mese_start}-{mese_end}) = €{totale:,.0f}")

    if not args.dry_run:
        deleted = result.get("rows_deleted", 0)
        inserted = result.get("rows_inserted", 0)
        print(f"  BQ: {deleted} righe sostituite, {inserted} inserite (fonte={result.get('fonte')})")


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


# ── Saldo banca helper ──────────────────────────────────────────────────────

def _compute_saldo_banca(societa: str, as_of_date: str) -> tuple[float, list[dict]]:
    """Real bank balance at end of as_of_date via nearest snapshot + movement delta.

    For each bank with a snapshot >= as_of_date: saldo = anchor_saldo - sum(movements
    between as_of_date+1 and anchor_date).  Falls back to cumulative sum if no snapshots.

    Returns (total, [{banca_id, saldo, anchor_date, note}]).
    """
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
    # Fallback: cumulative sum (no opening balance — inaccurate)
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

    print(f"  {'Voce':<32s} {'Consuntivo':>11s} {'Previsione':>11s} {'Delta':>11s}  {'%':>6s}")
    print(f"  {'─'*32} {'─'*11} {'─'*11} {'─'*11}  {'─'*6}")

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
        print(f"  {voce:<32s} {fmt_eur(c)} {fmt_eur(b)} {fmt_eur(d)}  {pct_s:>6s}{flag}")

        if sez == "ENTRATE":
            tot_c_e += c
            tot_b_e += b
        else:
            tot_c_u += c
            tot_b_u += b

        # Collect for snapshot
        snapshot_rows.append({
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
        })

    print(f"\n  {'─'*80}")
    print(f"  {'ENTRATE TOTALI':<32s} {fmt_eur(tot_c_e)} {fmt_eur(tot_b_e)} {fmt_eur(tot_c_e - tot_b_e)}")
    print(f"  {'USCITE TOTALI':<32s} {fmt_eur(tot_c_u)} {fmt_eur(tot_b_u)} {fmt_eur(tot_c_u - tot_b_u)}")
    cf_c = tot_c_e - tot_c_u
    cf_b = tot_b_e - tot_b_u
    print(f"  {'CASH FLOW NETTO':<32s} {fmt_eur(cf_c)} {fmt_eur(cf_b)} {fmt_eur(cf_c - cf_b)}")

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
        danger = " ⛔ PERICOLO" if saldo_running < 0 else (" ⚠ ATTENZIONE" if saldo_running < 50000 else "")
        print(f"    Mese {r['mese']:02d}/{fwd_anno}: entrate {fmt_eur(r['entrate_prev'])} - uscite {fmt_eur(r['uscite_prev'])} = netto {fmt_eur(netto)} → saldo {fmt_eur(saldo_running)}{danger}")

    if not fwd_rows:
        print("    (nessuna previsione disponibile per i prossimi mesi)")

    # 4. Save snapshot to BQ
    if save and snapshot_rows:
        _save_chiusura_snapshot(societa, anno, mese_chiuso, snapshot_rows)
    elif not save:
        print("\n  ℹ DRY RUN — snapshot NON salvato. Usa senza --dry-run per salvare.")


def _save_chiusura_snapshot(societa: str, anno: int, mese: int, rows: list[dict]):
    """Save monthly close snapshot to f_chiusura_mensile (DELETE-INSERT)."""
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
    errors = client.insert_rows_json(table_id, rows)
    if errors:
        print(f"\n  ✗ Errori inserimento snapshot: {errors[:3]}")
    else:
        print(f"\n  ✓ Snapshot salvato: {len(rows)} righe → f_chiusura_mensile ({societa} {mese:02d}/{anno})")
        print("    Nel tempo: hotelops chiudi mostra se le previsioni migliorano")


# ── Saldo: posizione banca corrente + proiezione ──────────────────────────

def cmd_saldo(args):
    """Saldo banca reale (da snapshot) + proiezione cash forward."""
    import calendar
    from datetime import date

    societa = args.societa or "ORTI"
    anno = args.anno or 2026
    today = date.today()

    # Starting saldo = end of last complete month
    prev_mese = today.month - 1 if today.month > 1 else 12
    prev_anno = today.year if today.month > 1 else today.year - 1
    last_day = calendar.monthrange(prev_anno, prev_mese)[1]
    as_of_date = f"{prev_anno}-{prev_mese:02d}-{last_day:02d}"

    print(f"\n  ═══ POSIZIONE DI CASSA — {societa} ═══")
    print(f"  Saldo reale al {last_day:02d}/{prev_mese:02d}/{prev_anno}\n")

    totale_banca, saldo_rows = _compute_saldo_banca(societa, as_of_date)

    print("  ── SALDI PER BANCA ──")
    for r in saldo_rows:
        method = f"  anchor {r['anchor_date']}" if r.get("note") == "ANCHOR" else "  ⚠ stima cumsum"
        print(f"    {r['banca_id']:<12s} {fmt_eur(r['saldo'])}{method}")
    print(f"    {'─'*48}")
    print(f"    {'TOTALE':<12s} {fmt_eur(totale_banca)}")

    if any(r.get("note") == "CUMSUM" for r in saldo_rows):
        print("\n  ⚠  Saldo stimato — esegui pipeline banca per caricare snapshot reali")

    # Forward projection: only months after the anchor month
    mese_filter = f"AND mese > {prev_mese}" if prev_anno == anno else ""
    print(f"\n  ── PROIEZIONE {anno} (partenza {fmt_eur(totale_banca)} al {as_of_date}) ──")
    print(f"  {'Mese':<8s} {'Entrate':>11s} {'Uscite':>11s} {'Netto':>11s} {'Saldo':>12s}")
    print(f"  {'─'*8} {'─'*11} {'─'*11} {'─'*11} {'─'*12}")

    fwd = query(f"""
    SELECT mese,
      ROUND(SUM(CASE WHEN sezione = 'ENTRATE' THEN
        CASE WHEN tipo_periodo = 'CONSUNTIVO' THEN importo_consuntivo ELSE importo_budget END
        ELSE 0 END), 0) AS entrate,
      ROUND(SUM(CASE WHEN sezione = 'USCITE' THEN
        CASE WHEN tipo_periodo = 'CONSUNTIVO' THEN importo_consuntivo ELSE importo_budget END
        ELSE 0 END), 0) AS uscite,
      MIN(tipo_periodo) AS tipo
    FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile`
    WHERE anno = {anno} AND societa_id = '{societa}'
      {mese_filter}
    GROUP BY mese ORDER BY mese
    """)

    saldo = totale_banca
    for r in fwd:
        entrate = r["entrate"] or 0
        uscite = r["uscite"] or 0
        netto = entrate - uscite
        saldo += netto
        tipo_tag = "📊" if r["tipo"] == "CONSUNTIVO" else "🔮"
        danger = " ⛔ NEGATIVO" if saldo < 0 else (" ⚠ BASSO" if saldo < 50000 else "")
        print(f"  {tipo_tag} {r['mese']:02d}/{anno}  {fmt_eur(entrate)} {fmt_eur(uscite)} {fmt_eur(netto)} {fmt_eur(saldo)}{danger}")

    print("\n  📊 = consuntivo reale  |  🔮 = previsione")


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
    p_chiudi.add_argument("--mese", type=int, help="Mese da chiudere (default: mese precedente)")
    p_chiudi.add_argument("--societa", choices=["ORTI", "INTUR"])
    p_chiudi.add_argument("--anno", type=int, default=2026)
    p_chiudi.add_argument("--dry-run", action="store_true", help="Mostra senza salvare snapshot in BQ")

    # saldo
    p_saldo = sub.add_parser("saldo", help="Saldo banca + proiezione cash forward")
    p_saldo.add_argument("--societa", choices=["ORTI", "INTUR"])
    p_saldo.add_argument("--anno", type=int, default=2026)

    # health
    sub.add_parser("health", help="Health check dati")

    # previsione
    p_prev = sub.add_parser("previsione", aliases=["prev"], help="Aggiorna previsione budget")
    p_prev.add_argument("voce", help="Voce (alias o voce_id, es. 'utenze' o 'USCITE_UTENZE')")
    p_prev.add_argument("mesi", help="Range mesi: '4-12' o 'aprile-dicembre' o '6' (singolo)")
    p_prev.add_argument("importo", type=float, help="Importo mensile in €")
    p_prev.add_argument("--societa", choices=["ORTI", "INTUR"], default="ORTI")
    p_prev.add_argument("--anno", type=int, default=2026)
    p_prev.add_argument("--fonte", default="CLI")
    p_prev.add_argument("--note", default=None)
    p_prev.add_argument("--dry-run", action="store_true")

    # voci
    sub.add_parser("voci", help="Lista voci piano finanziario")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
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
    }

    handlers[args.command](args)


if __name__ == "__main__":
    main()
