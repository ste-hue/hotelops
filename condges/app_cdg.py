#!/usr/bin/env python3
"""
Controllo di Gestione — App Unificata.

Quattro tab:
  1. CONTO ECONOMICO: P&L consuntivo YTD
  2. BUDGET: consuntivo vs budget mensile per fonte, con manopole crescita per BU
  3. TESORERIA: saldo banca proiettato mese per mese (entrate - uscite)
  4. INDICATORI: KPI operativi

Usage:
    streamlit run condges/app_cdg.py
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from io import BytesIO

from core import config as cfg
from condges.cdg_engine import compute_ce_cascade, compute_indicatori

MESI_NOMI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
ANNO = 2026
SOCIETA = "ORTI"


# ── BQ Client ─────────────────────────────────────────────────────────────────

@st.cache_resource
def get_bq():
    from google.cloud import bigquery
    return bigquery.Client(project=cfg.PROJECT)


# ── Data Loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Caricamento budget...")
def load_budget_base() -> pd.DataFrame:
    """Budget mensile corrente da BQ (tutte le fonti nostre)."""
    bq = get_bq()
    sql = f"""
    SELECT codice_conto, descrizione, tipo_costo, categoria_ce,
           business_unit_id, mese, importo, fonte
    FROM `{cfg.F_BUDGET_MENSILE}`
    WHERE societa_id = '{SOCIETA}' AND anno = {ANNO}
      AND fonte IN ('CONS2025_IP', 'MAPPATURA', 'STRUTTURALI', 'CONS2025_F',
                    'PERSONALE', 'CONS2025_V', 'CONS2025_X', 'APP_BUDGET')
    ORDER BY codice_conto, mese
    """
    return bq.query(sql).to_dataframe()


@st.cache_data(ttl=300, show_spinner="Caricamento consuntivo...")
def load_consuntivo_ytd() -> pd.DataFrame:
    """Consuntivo 2026 YTD da f_movimenti_contabili."""
    bq = get_bq()
    sql = f"""
    SELECT
      c.cod_conto,
      cat.codice_conto,
      cat.descrizione,
      cat.tipo_costo,
      cat.categoria_ce,
      c.mese,
      CASE
        WHEN c.cod_conto LIKE '47%' OR c.cod_conto LIKE '48%' OR c.cod_conto LIKE '53%'
        THEN SUM(imp_avere) - SUM(imp_dare)
        ELSE SUM(imp_dare) - SUM(imp_avere)
      END as importo
    FROM `{cfg.F_MOVIMENTI_CONTABILI}` c
    JOIN `{cfg.D_CATEGORIE_CONTI}` cat
      ON REPLACE(cat.codice_conto, '.', '') = c.cod_conto
    WHERE c.anno = {ANNO} AND c.societa_id = '{SOCIETA}'
    GROUP BY c.cod_conto, cat.codice_conto, cat.descrizione, cat.tipo_costo, cat.categoria_ce, c.mese
    """
    return bq.query(sql).to_dataframe()


@st.cache_data(ttl=300, show_spinner="Caricamento saldi banca...")
def load_saldi_banca() -> pd.DataFrame:
    """Ultimo saldo reale per banca."""
    bq = get_bq()
    sql = f"""
    SELECT banca_id, saldo_finale, data_snapshot
    FROM (
      SELECT *, ROW_NUMBER() OVER (PARTITION BY banca_id ORDER BY data_snapshot DESC) AS rn
      FROM `{cfg.F_SALDI_BANCA_SNAPSHOT}`
      WHERE societa_id = '{SOCIETA}'
    )
    WHERE rn = 1
    ORDER BY banca_id
    """
    try:
        return bq.query(sql).to_dataframe()
    except Exception:
        return pd.DataFrame(columns=["banca_id", "saldo_finale", "data_snapshot"])


@st.cache_data(ttl=300, show_spinner="Caricamento CE...")
def load_consuntivo_ce(societa: str, anno: int) -> pd.DataFrame:
    """Consuntivo aggregato per categoria_ce (for CE cascade)."""
    bq = get_bq()
    sql = f"""
    SELECT
      cat.categoria_ce,
      CASE
        WHEN c.cod_conto LIKE '47%' OR c.cod_conto LIKE '48%' OR c.cod_conto LIKE '53%'
        THEN SUM(imp_avere) - SUM(imp_dare)
        ELSE SUM(imp_dare) - SUM(imp_avere)
      END as importo
    FROM `{cfg.F_MOVIMENTI_CONTABILI}` c
    JOIN `{cfg.D_CATEGORIE_CONTI}` cat
      ON REPLACE(cat.codice_conto, '.', '') = c.cod_conto
    WHERE c.anno = {anno} AND c.societa_id = '{societa}'
    GROUP BY cat.categoria_ce
    """
    return bq.query(sql).to_dataframe()


@st.cache_data(ttl=600, show_spinner=False)
def load_stagionalita() -> pd.DataFrame:
    """Load seasonality coefficients per BU per month."""
    bq = get_bq()
    sql = f"""
    SELECT business_unit_id, mese, coefficiente
    FROM `{cfg.D_COEFFICIENTI_STAGIONALITA}`
    ORDER BY business_unit_id, mese
    """
    return bq.query(sql).to_dataframe()


@st.cache_data(ttl=300, show_spinner="Caricamento dettaglio CE...")
def load_consuntivo_ce_detail(societa: str, anno: int) -> pd.DataFrame:
    """Consuntivo per codice conto (for CE drill-down)."""
    bq = get_bq()
    sql = f"""
    SELECT
      cat.codice_conto,
      cat.descrizione,
      cat.categoria_ce,
      cat.tipo_costo,
      CASE
        WHEN c.cod_conto LIKE '47%' OR c.cod_conto LIKE '48%' OR c.cod_conto LIKE '53%'
        THEN SUM(imp_avere) - SUM(imp_dare)
        ELSE SUM(imp_dare) - SUM(imp_avere)
      END as importo
    FROM `{cfg.F_MOVIMENTI_CONTABILI}` c
    JOIN `{cfg.D_CATEGORIE_CONTI}` cat
      ON REPLACE(cat.codice_conto, '.', '') = c.cod_conto
    WHERE c.anno = {anno} AND c.societa_id = '{societa}'
    GROUP BY cat.codice_conto, cat.descrizione, cat.categoria_ce, cat.tipo_costo
    ORDER BY cat.categoria_ce, cat.codice_conto
    """
    return bq.query(sql).to_dataframe()


# ── Budget Engine ─────────────────────────────────────────────────────────────

def apply_growth(budget: pd.DataFrame, growth_pcts: dict[str, float]) -> pd.DataFrame:
    """Apply additional growth % per BU on top of budget base.

    - IP rows: multiply by (1 + pct/100) for matching business_unit_id
    - V rows: multiply by weighted average of all BU growths
    - F, P, X rows: unchanged
    """
    df = budget.copy()
    avg_growth = sum(growth_pcts.values()) / len(growth_pcts) if growth_pcts else 0

    for idx, row in df.iterrows():
        tipo = row["tipo_costo"]
        bu = row.get("business_unit_id")

        if tipo == "IP" and bu in growth_pcts:
            pct = growth_pcts[bu]
            df.loc[idx, "importo"] = row["importo"] * (1 + pct / 100)
        elif tipo == "V":
            df.loc[idx, "importo"] = row["importo"] * (1 + avg_growth / 100)

    return df


# ── Pivot helpers ─────────────────────────────────────────────────────────────

def pivot_mensile(df: pd.DataFrame, index_cols=None, value_col: str = "importo") -> pd.DataFrame:
    """Pivot to: rows=index_cols, cols=mesi, values=importo."""
    if df.empty:
        return pd.DataFrame()
    if index_cols is None:
        index_cols = ["codice_conto", "descrizione"]
    pv = df.pivot_table(
        index=index_cols,
        columns="mese", values=value_col, aggfunc="sum", fill_value=0
    )
    pv.columns = [MESI_NOMI[m - 1] for m in pv.columns]
    pv["TOTALE"] = pv.sum(axis=1)
    return pv.sort_values("TOTALE", ascending=False).reset_index()


def add_totals_row(df: pd.DataFrame, label_col: str = "descrizione") -> pd.DataFrame:
    """Append a TOTALE row to a pivoted dataframe."""
    num_cols = [c for c in df.columns if c in MESI_NOMI or c == "TOTALE"]
    totals = {c: df[c].sum() for c in num_cols}
    for c in df.columns:
        if c not in totals:
            totals[c] = "TOTALE" if c == label_col else ""
    return pd.concat([df, pd.DataFrame([totals])], ignore_index=True)


def fmt_thousands(df: pd.DataFrame) -> dict:
    """Format dict for numeric columns."""
    return {c: "{:,.0f}" for c in df.columns if c in MESI_NOMI or c == "TOTALE"}


# ── Excel Export ──────────────────────────────────────────────────────────

def genera_excel(budget: pd.DataFrame, consuntivo: pd.DataFrame,
                 last_actual_month: int, growth: dict) -> bytes:
    """Generate multi-sheet Excel with budget, consuntivo, and delta."""
    from openpyxl.styles import Font

    buf = BytesIO()

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        # ── Riepilogo Mensile
        ricavi_m = budget[budget["tipo_costo"] == "IP"].groupby("mese")["importo"].sum()
        costi_m = budget[budget["tipo_costo"] != "IP"].groupby("mese")["importo"].sum()

        summary = pd.DataFrame({
            "Mese": MESI_NOMI,
            "Ricavi": [ricavi_m.get(m, 0) for m in range(1, 13)],
            "Costi": [costi_m.get(m, 0) for m in range(1, 13)],
        })
        summary["Margine"] = summary["Ricavi"] - summary["Costi"]
        totals = pd.DataFrame([{
            "Mese": "TOTALE",
            "Ricavi": summary["Ricavi"].sum(),
            "Costi": summary["Costi"].sum(),
            "Margine": summary["Margine"].sum(),
        }])
        summary = pd.concat([summary, totals], ignore_index=True)
        summary.to_excel(writer, sheet_name="Riepilogo", index=False)

        # ── Budget per Fonte (full monthly grid)
        fonte_pv = pivot_mensile(budget, index_cols=["fonte", "tipo_costo"])
        fonte_pv.to_excel(writer, sheet_name="Per Fonte", index=False)

        # ── Ricavi per codice
        ip_pv = pivot_mensile(budget[budget["tipo_costo"] == "IP"])
        ip_pv.to_excel(writer, sheet_name="Ricavi", index=False)

        # ── Costi per tipo
        for tipo, sheet_name in [("F", "Fissi"), ("V", "Variabili"),
                                  ("P", "Personale"), ("X", "Finanziari")]:
            tipo_df = budget[budget["tipo_costo"] == tipo]
            if tipo_df.empty:
                continue
            pv = pivot_mensile(tipo_df, index_cols=["codice_conto", "descrizione", "fonte"])
            pv.to_excel(writer, sheet_name=sheet_name, index=False)

        # ── BvA
        if not consuntivo.empty and last_actual_month >= 1:
            b_ytd = budget[budget["mese"] <= last_actual_month].groupby(
                ["codice_conto", "descrizione", "tipo_costo"]
            )["importo"].sum().reset_index()
            b_ytd.columns = ["codice_conto", "descrizione", "tipo_costo", "budget"]

            a_ytd = consuntivo[consuntivo["mese"] <= last_actual_month].groupby(
                ["codice_conto", "descrizione", "tipo_costo"]
            )["importo"].sum().reset_index()
            a_ytd.columns = ["codice_conto", "descrizione", "tipo_costo", "consuntivo"]

            comp = pd.merge(b_ytd, a_ytd, on=["codice_conto", "descrizione", "tipo_costo"],
                           how="outer").fillna(0)
            comp["delta"] = comp["consuntivo"] - comp["budget"]
            comp["delta_%"] = (comp["delta"] / comp["budget"].replace(0, float("nan")) * 100).round(1)
            comp = comp.sort_values("delta", key=abs, ascending=False)
            comp.to_excel(writer, sheet_name=f"BvA mesi 1-{last_actual_month}", index=False)

        # ── Parametri
        params = pd.DataFrame([
            {"Parametro": "Societa", "Valore": SOCIETA},
            {"Parametro": "Anno", "Valore": ANNO},
            {"Parametro": "Base", "Valore": "Consuntivo 2025"},
            {"Parametro": "Crescita Hotel", "Valore": f"{growth.get('HOTEL', 0):+d}%"},
            {"Parametro": "Crescita Residence", "Valore": f"{growth.get('RESIDENCE', 0):+d}%"},
            {"Parametro": "Crescita CVM", "Valore": f"{growth.get('CVM', 0):+d}%"},
            {"Parametro": "Crescita Spiaggia", "Valore": f"{growth.get('LIDO', 0):+d}%"},
            {"Parametro": "Personale", "Valore": "Budget Personale 2026 Excel"},
            {"Parametro": "Fissi mappati", "Valore": "Mappatura Costi v2 Excel"},
            {"Parametro": "Generato", "Valore": datetime.now().strftime("%Y-%m-%d %H:%M")},
        ])
        params.to_excel(writer, sheet_name="Parametri", index=False)

    # Format workbook
    buf.seek(0)
    from openpyxl import load_workbook
    wb = load_workbook(buf)

    header_font = Font(bold=True)
    number_fmt = '#,##0'

    for ws in wb.worksheets:
        for cell in ws[1]:
            cell.font = header_font
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, (int, float)):
                    cell.number_format = number_fmt
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 20)

    buf2 = BytesIO()
    wb.save(buf2)
    buf2.seek(0)
    return buf2.getvalue()


# ── Save to BQ ─────────────────────────────────────────────────────────────

def save_to_bq(df: pd.DataFrame):
    """DELETE-INSERT budget with fonte=APP_BUDGET."""
    from google.cloud import bigquery

    bq = get_bq()

    bq.query(f"""
        DELETE FROM `{cfg.F_BUDGET_MENSILE}`
        WHERE societa_id = '{SOCIETA}' AND anno = {ANNO} AND fonte = 'APP_BUDGET'
    """).result()

    rows = []
    for _, r in df.iterrows():
        rows.append({
            "societa_id": SOCIETA,
            "anno": ANNO,
            "mese": int(r["mese"]),
            "codice_conto": r["codice_conto"],
            "descrizione": r["descrizione"],
            "tipo_costo": r["tipo_costo"],
            "categoria_ce": r["categoria_ce"],
            "business_unit_id": r.get("business_unit_id"),
            "importo": round(float(r["importo"]), 2),
            "fonte": "APP_BUDGET",
        })

    job_config = bigquery.LoadJobConfig(
        schema=[
            bigquery.SchemaField("societa_id", "STRING"),
            bigquery.SchemaField("anno", "INTEGER"),
            bigquery.SchemaField("mese", "INTEGER"),
            bigquery.SchemaField("codice_conto", "STRING"),
            bigquery.SchemaField("descrizione", "STRING"),
            bigquery.SchemaField("tipo_costo", "STRING"),
            bigquery.SchemaField("categoria_ce", "STRING"),
            bigquery.SchemaField("business_unit_id", "STRING"),
            bigquery.SchemaField("importo", "FLOAT64"),
            bigquery.SchemaField("fonte", "STRING"),
        ],
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = bq.load_table_from_json(rows, str(cfg.F_BUDGET_MENSILE), job_config=job_config)
    job.result()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1: BUDGET
# ══════════════════════════════════════════════════════════════════════════════

def page_budget(adjusted: pd.DataFrame, consuntivo: pd.DataFrame,
                last_actual_month: int, growth: dict):

    # ── Metrics ─────────────────────────────────────────────────────────────
    ricavi = adjusted[adjusted["tipo_costo"] == "IP"]["importo"].sum()
    costi = adjusted[adjusted["tipo_costo"] != "IP"]["importo"].sum()
    margine = ricavi - costi
    cons_ytd = consuntivo["importo"].sum() if not consuntivo.empty else 0
    budget_ytd = adjusted[adjusted["mese"] <= last_actual_month]["importo"].sum() if last_actual_month > 0 else 0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Ricavi 2026", f"{ricavi:,.0f} \u20ac")
    col2.metric("Costi 2026", f"{costi:,.0f} \u20ac")
    col3.metric("Margine", f"{margine:,.0f} \u20ac",
                delta=f"{margine / ricavi * 100:.0f}%" if ricavi else None,
                delta_color="normal" if margine >= 0 else "inverse")
    col4.metric("Consuntivo YTD", f"{cons_ytd:,.0f} \u20ac")
    col5.metric("Budget YTD", f"{budget_ytd:,.0f} \u20ac",
                delta=f"{cons_ytd - budget_ytd:+,.0f}" if last_actual_month > 0 else None)

    # ── Chart: Profilo Mensile ──────────────────────────────────────────────
    st.subheader("Profilo Mensile")

    ricavi_m = adjusted[adjusted["tipo_costo"] == "IP"].groupby("mese")["importo"].sum()
    costi_m = adjusted[adjusted["tipo_costo"] != "IP"].groupby("mese")["importo"].sum()

    cons_ricavi_m = {}
    cons_costi_m = {}
    if not consuntivo.empty:
        cons_ip = consuntivo[consuntivo["tipo_costo"] == "IP"].groupby("mese")["importo"].sum()
        cons_cost = consuntivo[consuntivo["tipo_costo"] != "IP"].groupby("mese")["importo"].sum()
        for m in range(1, last_actual_month + 1):
            cons_ricavi_m[m] = cons_ip.get(m, 0)
            cons_costi_m[m] = cons_cost.get(m, 0)

    fig = go.Figure()

    budget_ricavi = [ricavi_m.get(m, 0) for m in range(1, 13)]
    budget_costi = [costi_m.get(m, 0) for m in range(1, 13)]

    fig.add_trace(go.Bar(
        x=MESI_NOMI, y=budget_ricavi, name="Budget Ricavi",
        marker_color=["rgba(134,239,172,0.3)" if m <= last_actual_month else "#86efac" for m in range(1, 13)],
        marker_pattern_shape=["" if m <= last_actual_month else "/" for m in range(1, 13)],
        marker_line=dict(color="#22c55e", width=1),
    ))
    fig.add_trace(go.Bar(
        x=MESI_NOMI, y=budget_costi, name="Budget Costi",
        marker_color=["rgba(252,165,165,0.3)" if m <= last_actual_month else "#fca5a5" for m in range(1, 13)],
        marker_pattern_shape=["" if m <= last_actual_month else "/" for m in range(1, 13)],
        marker_line=dict(color="#ef4444", width=1),
    ))

    actual_ricavi = [cons_ricavi_m.get(m, 0) if m <= last_actual_month else 0 for m in range(1, 13)]
    actual_costi = [cons_costi_m.get(m, 0) if m <= last_actual_month else 0 for m in range(1, 13)]

    fig.add_trace(go.Bar(x=MESI_NOMI, y=actual_ricavi, name="Consuntivo Ricavi", marker_color="#16a34a"))
    fig.add_trace(go.Bar(x=MESI_NOMI, y=actual_costi, name="Consuntivo Costi", marker_color="#dc2626"))

    if 1 <= last_actual_month < 12:
        fig.add_vline(x=last_actual_month - 0.5, line_dash="dash", line_color="gray",
                      annotation_text="consuntivo | budget", annotation_position="top")

    fig.update_layout(barmode="group", yaxis_tickformat=",",
                      legend=dict(orientation="h", y=-0.15), height=450)
    st.plotly_chart(fig, use_container_width=True)

    # ── Budget Mensile per Fonte ────────────────────────────────────────────
    st.subheader("Budget Mensile per Fonte")

    fonte_pv = pivot_mensile(adjusted, index_cols=["fonte", "tipo_costo"])
    if not fonte_pv.empty:
        fonte_pv = add_totals_row(fonte_pv, label_col="fonte")
        st.dataframe(fonte_pv.style.format(fmt_thousands(fonte_pv)),
                     use_container_width=True, hide_index=True)

    # ── BvA ─────────────────────────────────────────────────────────────────
    if not consuntivo.empty and last_actual_month >= 1:
        st.subheader(f"Budget vs Consuntivo (mesi 1-{last_actual_month})")

        b_ytd = adjusted[adjusted["mese"] <= last_actual_month].groupby("categoria_ce")["importo"].sum()
        a_ytd = consuntivo[consuntivo["mese"] <= last_actual_month].groupby("categoria_ce")["importo"].sum()

        bva = pd.DataFrame({"Budget YTD": b_ytd, "Consuntivo": a_ytd}).fillna(0)
        bva["Delta"] = bva["Consuntivo"] - bva["Budget YTD"]
        bva["Delta %"] = (bva["Delta"] / bva["Budget YTD"].replace(0, float("nan")) * 100).round(1)
        bva = bva.sort_values("Delta", key=abs, ascending=False)

        def _color_delta(val):
            if isinstance(val, (int, float)):
                return "color: #16a34a" if val > 0 else "color: #dc2626" if val < 0 else ""
            return ""

        st.dataframe(
            bva.style.format({"Budget YTD": "{:,.0f}", "Consuntivo": "{:,.0f}",
                              "Delta": "{:+,.0f}", "Delta %": "{:+.1f}%"})
            .map(_color_delta, subset=["Delta", "Delta %"]),
            use_container_width=True
        )

        # ── Year-end projection per codice conto ───────────────────────────
        st.subheader("Proiezione Fine Anno")

        from condges.cdg_engine import compute_proiezione_anno

        stag_df = load_stagionalita()
        stag_by_bu = {}
        for bu in stag_df["business_unit_id"].unique():
            bu_df = stag_df[stag_df["business_unit_id"] == bu].sort_values("mese")
            stag_by_bu[bu] = bu_df["coefficiente"].tolist()
        flat_stag = [1.0] * 12

        # Per-codice consuntivo YTD
        cons_by_code = consuntivo.groupby(
            ["codice_conto", "descrizione", "tipo_costo", "categoria_ce"]
        )["importo"].sum().reset_index()

        # Full-year budget per codice
        budget_full = adjusted.groupby("codice_conto")["importo"].sum()

        proiezioni = []
        for _, row in cons_by_code.iterrows():
            stag = flat_stag  # default; BU-level would need mapping
            proj = compute_proiezione_anno(
                row["importo"], row["tipo_costo"], last_actual_month, stag
            )
            budget_anno = budget_full.get(row["codice_conto"], 0)
            proiezioni.append({
                "Codice": row["codice_conto"],
                "Descrizione": row["descrizione"],
                "Tipo": row["tipo_costo"],
                "Categoria": row["categoria_ce"],
                "Consuntivo YTD": row["importo"],
                "Proiezione Anno": proj,
                "Budget Anno": budget_anno,
                "Delta Proiez.": proj - budget_anno,
            })

        if proiezioni:
            proj_df = pd.DataFrame(proiezioni)
            proj_df = proj_df.sort_values("Delta Proiez.", key=abs, ascending=False)

            st.dataframe(
                proj_df.style.format({
                    "Consuntivo YTD": "{:,.0f}",
                    "Proiezione Anno": "{:,.0f}",
                    "Budget Anno": "{:,.0f}",
                    "Delta Proiez.": "{:+,.0f}",
                }).map(_color_delta, subset=["Delta Proiez."]),
                use_container_width=True, hide_index=True,
            )

    # ── Dettaglio per tipo ──────────────────────────────────────────────────
    st.subheader("Dettaglio per Categoria")

    for tipo, label in [("IP", "Ricavi"), ("F", "Costi Fissi"),
                        ("V", "Variabili"), ("P", "Personale"), ("X", "Finanziari")]:
        with st.expander(label):
            tipo_df = pivot_mensile(adjusted[adjusted["tipo_costo"] == tipo])
            if not tipo_df.empty:
                tipo_df = add_totals_row(tipo_df)
                st.dataframe(tipo_df.style.format(fmt_thousands(tipo_df)),
                             use_container_width=True, hide_index=True)

    # ── Export ──────────────────────────────────────────────────────────────
    st.divider()
    growth_desc = ", ".join(f"{bu} {pct:+d}%" for bu, pct in growth.items() if pct != 0)
    st.info(f"Scenario: {growth_desc}" if growth_desc else "Scenario base (nessun aggiustamento)")

    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        excel_bytes = genera_excel(adjusted, consuntivo, last_actual_month, growth)
        st.download_button("Scarica Excel", data=excel_bytes,
                           file_name=f"Budget_{SOCIETA}_{ANNO}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary")
    with col_exp2:
        if st.button("Salva in BQ (fonte=APP_BUDGET)"):
            save_to_bq(adjusted)
            st.success("Salvato in BQ")
            st.cache_data.clear()


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2: TESORERIA
# ══════════════════════════════════════════════════════════════════════════════

def page_tesoreria(adjusted: pd.DataFrame, consuntivo: pd.DataFrame,
                   last_actual_month: int):

    st.subheader("Saldo Banca Attuale")

    saldi = load_saldi_banca()
    if saldi.empty:
        st.warning("Nessun saldo banca trovato in f_saldi_banca_snapshot.")
        saldo_iniziale = 0.0
        data_saldo = "N/A"
    else:
        saldo_iniziale = saldi["saldo_finale"].sum()
        data_saldo = saldi["data_snapshot"].max()

        # Show per-bank breakdown
        cols = st.columns(len(saldi) + 1)
        cols[0].metric("TOTALE", f"{saldo_iniziale:,.0f} \u20ac",
                       help=f"Al {data_saldo}")
        for i, (_, row) in enumerate(saldi.iterrows()):
            cols[i + 1].metric(row["banca_id"],
                               f"{row['saldo_finale']:,.0f} \u20ac",
                               help=f"Al {row['data_snapshot']}")

    # ── Monthly cash flow from budget ───────────────────────────────────────
    st.subheader("Proiezione Cassa Mensile")
    st.caption("Entrate e uscite dal budget, saldo proiettato partendo dal saldo banca reale")

    # For consuntivo months: use actual data; for future months: use budget
    rows = []
    for m in range(1, 13):
        if m <= last_actual_month and not consuntivo.empty:
            # Actual
            entrate = consuntivo[
                (consuntivo["mese"] == m) & (consuntivo["tipo_costo"] == "IP")
            ]["importo"].sum()
            uscite = consuntivo[
                (consuntivo["mese"] == m) & (consuntivo["tipo_costo"] != "IP")
            ]["importo"].sum()
            tipo_dato = "CONSUNTIVO"
        else:
            # Budget projection
            entrate = adjusted[
                (adjusted["mese"] == m) & (adjusted["tipo_costo"] == "IP")
            ]["importo"].sum()
            uscite = adjusted[
                (adjusted["mese"] == m) & (adjusted["tipo_costo"] != "IP")
            ]["importo"].sum()
            tipo_dato = "BUDGET"

        rows.append({
            "mese": m,
            "mese_nome": MESI_NOMI[m - 1],
            "tipo": tipo_dato,
            "entrate": entrate,
            "uscite": uscite,
            "netto": entrate - uscite,
        })

    cashflow = pd.DataFrame(rows)

    # Running balance
    cashflow["saldo"] = saldo_iniziale + cashflow["netto"].cumsum()

    # ── Table ───────────────────────────────────────────────────────────────
    display_cf = cashflow[["mese_nome", "tipo", "entrate", "uscite", "netto", "saldo"]].copy()
    display_cf.columns = ["Mese", "Fonte", "Entrate", "Uscite", "Netto", "Saldo Proiettato"]

    # Add totals
    totals_row = {
        "Mese": "TOTALE",
        "Fonte": "",
        "Entrate": display_cf["Entrate"].sum(),
        "Uscite": display_cf["Uscite"].sum(),
        "Netto": display_cf["Netto"].sum(),
        "Saldo Proiettato": display_cf["Saldo Proiettato"].iloc[-1],
    }
    display_cf = pd.concat([display_cf, pd.DataFrame([totals_row])], ignore_index=True)

    def _color_saldo(val):
        if isinstance(val, (int, float)):
            if val < 0:
                return "background-color: #fecaca; color: #991b1b"
            elif val < 50000:
                return "background-color: #fef9c3; color: #854d0e"
        return ""

    def _color_fonte(val):
        if val == "CONSUNTIVO":
            return "background-color: #dcfce7"
        elif val == "BUDGET":
            return "background-color: #f0f9ff"
        return ""

    st.dataframe(
        display_cf.style
        .format({"Entrate": "{:,.0f}", "Uscite": "{:,.0f}",
                 "Netto": "{:+,.0f}", "Saldo Proiettato": "{:,.0f}"})
        .map(_color_saldo, subset=["Saldo Proiettato"])
        .map(_color_fonte, subset=["Fonte"]),
        use_container_width=True, hide_index=True,
        height=500,
    )

    # ── Chart: saldo + cash flow ────────────────────────────────────────────
    st.subheader("Andamento Cassa")

    fig = go.Figure()

    # Entrate/uscite bars
    colors_entrate = ["#16a34a" if r["tipo"] == "CONSUNTIVO" else "#86efac" for _, r in cashflow.iterrows()]
    colors_uscite = ["#dc2626" if r["tipo"] == "CONSUNTIVO" else "#fca5a5" for _, r in cashflow.iterrows()]

    fig.add_trace(go.Bar(
        x=MESI_NOMI, y=cashflow["entrate"].tolist(),
        name="Entrate", marker_color=colors_entrate,
    ))
    fig.add_trace(go.Bar(
        x=MESI_NOMI, y=[-u for u in cashflow["uscite"].tolist()],
        name="Uscite", marker_color=colors_uscite,
    ))

    # Saldo line
    fig.add_trace(go.Scatter(
        x=MESI_NOMI, y=cashflow["saldo"].tolist(),
        name="Saldo", mode="lines+markers",
        line=dict(color="#1d4ed8", width=3),
        yaxis="y2",
    ))

    # Danger zone
    fig.add_hline(y=0, line_dash="dot", line_color="red", opacity=0.5, yref="y2")
    fig.add_hline(y=50000, line_dash="dot", line_color="orange", opacity=0.3, yref="y2",
                  annotation_text="soglia attenzione 50K", annotation_position="bottom right")

    if 1 <= last_actual_month < 12:
        fig.add_vline(x=last_actual_month - 0.5, line_dash="dash", line_color="gray",
                      annotation_text="consuntivo | proiezione", annotation_position="top")

    fig.update_layout(
        barmode="relative",
        yaxis=dict(title="Flussi mensili (\u20ac)", tickformat=","),
        yaxis2=dict(title="Saldo (\u20ac)", overlaying="y", side="right", tickformat=","),
        legend=dict(orientation="h", y=-0.15),
        height=500,
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Liquidity status ────────────────────────────────────────────────────
    min_saldo = cashflow["saldo"].min()
    min_mese = MESI_NOMI[cashflow["saldo"].idxmin()]

    if min_saldo < 0:
        st.error(f"PERICOLO: saldo negativo a {min_mese} ({min_saldo:,.0f} \u20ac). Necessario intervento.")
    elif min_saldo < 50000:
        st.warning(f"ATTENZIONE: saldo minimo {min_saldo:,.0f} \u20ac a {min_mese}. Margine ridotto.")
    else:
        st.success(f"Liquidita OK: saldo minimo {min_saldo:,.0f} \u20ac a {min_mese}.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 3: CONTO ECONOMICO (placeholder)
# ══════════════════════════════════════════════════════════════════════════════

def page_ce(consuntivo: pd.DataFrame, last_actual_month: int):
    """Conto Economico riclassificato."""
    ce_data = load_consuntivo_ce(SOCIETA, ANNO)
    ce_detail = load_consuntivo_ce_detail(SOCIETA, ANNO)

    if ce_data.empty:
        st.warning("Nessun dato consuntivo trovato.")
        return

    cascade = compute_ce_cascade(ce_data)

    st.subheader(f"CE Riclassificato — {SOCIETA} {ANNO}")
    if last_actual_month > 0:
        st.caption(f"Consuntivo mesi 1-{last_actual_month} ({MESI_NOMI[last_actual_month - 1]})")

    rows_display = []
    for r in cascade:
        prefix = "  " * r["indent"]
        label = f"**{r['label']}**" if r["is_subtotal"] else f"{prefix}{r['label']}"
        rows_display.append({
            "Voce": label,
            "Importo": r["importo"],
            "% Ricavi": r["pct_ricavi"],
        })

    ce_df = pd.DataFrame(rows_display)

    def _color_subtotal(row):
        if "**" in str(row["Voce"]):
            return ["font-weight: bold; background-color: #f0f9ff"] * len(row)
        return [""] * len(row)

    st.dataframe(
        ce_df.style
        .format({"Importo": "{:,.0f}", "% Ricavi": "{:.1f}%"})
        .apply(_color_subtotal, axis=1),
        use_container_width=True, hide_index=True,
        height=500,
    )

    st.subheader("Dettaglio per Categoria")

    for cat in ["Ricavi", "Acquisti", "Costi Produttivi", "Costo del Personale",
                "Costi Commerciali", "Costi Amministrativi", "Oneri Finanziari"]:
        cat_df = ce_detail[ce_detail["categoria_ce"] == cat]
        if cat_df.empty:
            continue
        total = cat_df["importo"].sum()
        with st.expander(f"{cat} — {total:,.0f} €"):
            display = cat_df[["codice_conto", "descrizione", "tipo_costo", "importo"]].copy()
            display.columns = ["Codice", "Descrizione", "Tipo", "Importo"]
            display = display.sort_values("Importo", ascending=False)
            st.dataframe(
                display.style.format({"Importo": "{:,.0f}"}),
                use_container_width=True, hide_index=True,
            )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE 4: INDICATORI (placeholder)
# ══════════════════════════════════════════════════════════════════════════════

def page_indicatori(consuntivo: pd.DataFrame, adjusted: pd.DataFrame,
                    last_actual_month: int):
    """KPI dashboard: EBITDA%, ROS, BEP."""
    ce_data = load_consuntivo_ce(SOCIETA, ANNO)

    if ce_data.empty:
        st.warning("Nessun dato consuntivo per calcolare gli indicatori.")
        return

    cascade = compute_ce_cascade(ce_data)

    # tipo_costo totals from consuntivo
    tipo_df = consuntivo.groupby("tipo_costo")["importo"].sum().reset_index()

    kpi = compute_indicatori(cascade, tipo_df)

    # ── Big numbers ────────────────────────────────────────────────────────
    st.subheader(f"Indicatori — {SOCIETA} {ANNO}")
    if last_actual_month > 0:
        st.caption(f"Calcolati su consuntivo mesi 1-{last_actual_month}")

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("EBITDA %", f"{kpi['ebitda_pct']:.1f}%")
    col2.metric("ROS", f"{kpi['ros']:.1f}%")
    col3.metric("BEP Fatturato", f"{kpi['bep_fatturato']:,.0f} €")
    col4.metric("BEP Giorno", f"{kpi['bep_giorno']}")
    col5.metric("Margine Contribuzione", f"{kpi['margine_contribuzione']:.1f}%")

    # ── BEP explanation ────────────────────────────────────────────────────
    st.divider()

    vals = {r["label"]: r["importo"] for r in cascade}
    ricavi = vals.get("Ricavi", 0)

    if ricavi > 0 and kpi["bep_fatturato"] > 0:
        pct_bep = kpi["bep_fatturato"] / ricavi * 100
        if pct_bep > 100:
            st.error(
                f"Il fatturato attuale ({ricavi:,.0f} €) è **sotto** il break-even "
                f"({kpi['bep_fatturato']:,.0f} €). Servono {kpi['bep_fatturato'] - ricavi:,.0f} € in più."
            )
        elif pct_bep > 90:
            st.warning(
                f"Margine di sicurezza ridotto: il fatturato è al **{pct_bep:.0f}%** del break-even. "
                f"Giorno BEP = {kpi['bep_giorno']} su 365."
            )
        else:
            st.success(
                f"Fatturato al **{pct_bep:.0f}%** del break-even. "
                f"Giorno BEP = {kpi['bep_giorno']} — margine confortevole."
            )

    # ── Detail table ───────────────────────────────────────────────────────
    st.subheader("Dettaglio Calcolo")

    tipo_sums = tipo_df.groupby("tipo_costo")["importo"].sum().to_dict() if not tipo_df.empty else {}
    detail = pd.DataFrame([
        {"Voce": "Ricavi (IP)", "Importo": tipo_sums.get("IP", 0)},
        {"Voce": "Costi Fissi (F)", "Importo": tipo_sums.get("F", 0)},
        {"Voce": "Costi Variabili (V)", "Importo": tipo_sums.get("V", 0)},
        {"Voce": "Personale (P)", "Importo": tipo_sums.get("P", 0)},
        {"Voce": "Finanziari (X)", "Importo": tipo_sums.get("X", 0)},
    ])
    st.dataframe(
        detail.style.format({"Importo": "{:,.0f}"}),
        use_container_width=True, hide_index=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    st.set_page_config(page_title="Controllo di Gestione", layout="wide")
    st.title("Controllo di Gestione")

    # ── Data ────────────────────────────────────────────────────────────────
    budget_base = load_budget_base()
    consuntivo = load_consuntivo_ytd()

    if budget_base.empty:
        st.error("Nessun budget trovato in f_budget_mensile.")
        return

    today = datetime.now()
    if today.year == ANNO:
        max_closed_month = today.month - 1
    else:
        max_closed_month = 12
    data_max = int(consuntivo["mese"].max()) if not consuntivo.empty else 0
    last_actual_month = min(data_max, max_closed_month)

    # ── Sidebar ─────────────────────────────────────────────────────────────
    st.sidebar.header("Parametri")

    _societa = st.sidebar.selectbox("Società", ["ORTI", "INTUR"])
    anno = st.sidebar.number_input("Anno", min_value=2024, max_value=2030, value=ANNO)

    st.sidebar.divider()
    st.sidebar.subheader("Scenario Crescita")
    st.sidebar.caption("Crescita % aggiuntiva rispetto al budget base.")

    growth = {}
    growth["HOTEL"] = st.sidebar.slider("Hotel", -30, 50, 0, 1, format="%+d%%")
    growth["RESIDENCE"] = st.sidebar.slider("Residence", -30, 50, 0, 1, format="%+d%%")
    growth["CVM"] = st.sidebar.slider("CVM", -30, 50, 0, 1, format="%+d%%")
    growth["LIDO"] = st.sidebar.slider("Spiaggia", -30, 50, 0, 1, format="%+d%%")

    adjusted = apply_growth(budget_base, growth)

    # Sidebar summary
    ricavi = adjusted[adjusted["tipo_costo"] == "IP"]["importo"].sum()
    costi = adjusted[adjusted["tipo_costo"] != "IP"]["importo"].sum()
    st.sidebar.divider()
    st.sidebar.metric("Ricavi", f"{ricavi:,.0f} €")
    st.sidebar.metric("Margine", f"{ricavi - costi:,.0f} €",
                      delta=f"{(ricavi - costi) / ricavi * 100:.0f}%" if ricavi else None)

    if last_actual_month > 0:
        st.sidebar.caption(f"Consuntivo fino a: {MESI_NOMI[last_actual_month - 1]} {anno}")

    # ── Tabs ────────────────────────────────────────────────────────────────
    tab_ce, tab_budget, tab_tesoreria, tab_indicatori = st.tabs(
        ["Conto Economico", "Budget", "Tesoreria", "Indicatori"]
    )

    with tab_ce:
        page_ce(consuntivo, last_actual_month)

    with tab_budget:
        page_budget(adjusted, consuntivo, last_actual_month, growth)

    with tab_tesoreria:
        page_tesoreria(adjusted, consuntivo, last_actual_month)

    with tab_indicatori:
        page_indicatori(consuntivo, adjusted, last_actual_month)


if __name__ == "__main__":
    main()
