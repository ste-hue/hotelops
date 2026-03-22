#!/usr/bin/env python3
"""
Piano Finanziario — App Interattiva per Rosa (Tesoreria)
Legge da BigQuery, scrive in f_piano_finanziario_input con fonte='APP'.

Usage:
    streamlit run condges/app.py
    pip install -e ".[dashboard]"
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from io import BytesIO

import pandas as pd
import streamlit as st

from core import config as cfg
from core.schemas import PianoFinanziarioInputRow, make_hash, validate_batch

MESI_NOMI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
FONTE_APP = "APP"
ANNO_DEFAULT = 2026


# ── BQ Client ─────────────────────────────────────────────────────────────────

@st.cache_resource
def get_bq():
    from google.cloud import bigquery
    return bigquery.Client(project=cfg.PROJECT)


# ── Data Loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def load_saldi_banca(societa: str, _bq=None) -> pd.DataFrame:
    """Ultimo saldo reale per banca (f_saldi_banca_snapshot)."""
    bq = _bq or get_bq()
    sql = f"""
    SELECT banca_id, saldo_finale, data_snapshot
    FROM (
      SELECT *, ROW_NUMBER() OVER (PARTITION BY banca_id ORDER BY data_snapshot DESC) AS rn
      FROM `{cfg.F_SALDI_BANCA_SNAPSHOT}`
      WHERE societa_id = '{societa}'
    )
    WHERE rn = 1
    ORDER BY banca_id
    """
    try:
        return bq.query(sql).to_dataframe()
    except Exception:
        return pd.DataFrame(columns=["banca_id", "saldo_finale", "data_snapshot"])


@st.cache_data(ttl=300, show_spinner=False)
def load_pf_data(societa: str, anno: int, _bq=None) -> tuple[pd.DataFrame, dict]:
    """
    Carica il piano finanziario da v_piano_finanziario_mensile.

    Returns:
        df_pf: DataFrame indexed by voce_id, cols = [voce_label, sezione, ord, Gen..Dic]
               valori: importo_consuntivo per mesi passati, importo_budget per futuri
        budget_costi: dict {(voce_id, mese): float} — componente da f_budget_mensile
                      serve per calcolare il delta corretto al salvataggio
    """
    bq = _bq or get_bq()

    # Vista principale
    sql_pf = f"""
    SELECT voce_id, voce_label, sezione, categoria, ord, mese,
           tipo_periodo, importo_consuntivo, importo_budget
    FROM `{cfg.V_PIANO_FINANZIARIO_MENSILE}`
    WHERE societa_id = '{societa}' AND anno = {anno}
    ORDER BY ord, mese
    """
    df_raw = bq.query(sql_pf).to_dataframe()

    # Componente budget_costi (per il save logic)
    sql_bc = f"""
    SELECT v.voce_id, b.mese, ROUND(SUM(b.importo), 2) AS budget_costi
    FROM `{cfg.F_BUDGET_MENSILE}` b
    JOIN `{cfg.D_VOCI_PIANO_FINANZIARIO}` v
      ON v.fonte = 'ESOLVER'
      AND (REPLACE(b.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pattern, '%')
        OR (v.cod_conto_pat2 IS NOT NULL AND REPLACE(b.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pat2, '%'))
        OR (v.cod_conto_pat3 IS NOT NULL AND REPLACE(b.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pat3, '%')))
      AND (v.societa_id IS NULL OR v.societa_id = b.societa_id)
    WHERE b.societa_id = '{societa}' AND b.anno = {anno}
    GROUP BY 1, 2
    """
    try:
        df_bc = bq.query(sql_bc).to_dataframe()
        budget_costi = {(r.voce_id, int(r.mese)): float(r.budget_costi) for r in df_bc.itertuples()}
    except Exception:
        budget_costi = {}

    if df_raw.empty:
        return pd.DataFrame(), budget_costi

    # Scegli il valore da mostrare: consuntivo per mesi passati, budget per futuri
    def pick_value(row):
        if row["tipo_periodo"] == "CONSUNTIVO":
            return float(row["importo_consuntivo"] or 0)
        return float(row["importo_budget"] or 0)

    df_raw["importo"] = df_raw.apply(pick_value, axis=1)

    # Pivot: righe=voce_id, colonne=mesi 1..12
    pivot = df_raw.pivot_table(index="voce_id", columns="mese", values="importo", fill_value=0.0)
    for m in range(1, 13):
        if m not in pivot.columns:
            pivot[m] = 0.0
    pivot = pivot[[m for m in range(1, 13)]]
    pivot.columns = MESI_NOMI

    # Tipo periodo per mese (per sapere quali sono consuntivo)
    tipo_pivot = df_raw.pivot_table(
        index="voce_id", columns="mese", values="tipo_periodo", aggfunc="first"
    )

    # Metadati voce
    meta = (
        df_raw.drop_duplicates("voce_id")
        [["voce_id", "voce_label", "sezione", "categoria", "ord"]]
        .set_index("voce_id")
    )

    df = meta.join(pivot)

    # tipo_periodo per voce: dict {mese: 'CONSUNTIVO'|'BUDGET'}
    def build_tipo(voce_id):
        return {
            m: (tipo_pivot.loc[voce_id, m] if voce_id in tipo_pivot.index and m in tipo_pivot.columns else "BUDGET")
            for m in range(1, 13)
        }
    df["_tipo"] = [build_tipo(vid) for vid in df.index]

    return df, budget_costi


@st.cache_data(ttl=300, show_spinner=False)
def load_scadenzario_agg(societa: str, _bq=None) -> pd.DataFrame:
    """Scadenzario aggregato per voce × mese con roll-forward."""
    bq = _bq or get_bq()
    sql = f"""
    WITH latest AS (
      SELECT MAX(data_snapshot) AS snap
      FROM `{cfg.F_PARTITE_APERTE_FORNITORI}`
      WHERE societa_id = '{societa}'
    )
    SELECT
      COALESCE(d.voce_id, 'ALTRI') AS voce_id,
      EXTRACT(YEAR  FROM GREATEST(p.data_scadenza, DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH))) AS anno,
      EXTRACT(MONTH FROM GREATEST(p.data_scadenza, DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH))) AS mese,
      ROUND(SUM(p.importo_abs), 0) AS uscite_scadenzario,
      COUNT(*) AS n_fatture
    FROM `{cfg.F_PARTITE_APERTE_FORNITORI}` p
    CROSS JOIN latest l
    LEFT JOIN `{cfg.D_FORNITORI}` d ON p.codice_fornitore = d.codice_fornitore
    WHERE p.societa_id = '{societa}'
      AND p.data_snapshot = l.snap
      AND p.is_intercompany = FALSE
    GROUP BY 1, 2, 3
    ORDER BY 1, 2, 3
    """
    try:
        return bq.query(sql).to_dataframe()
    except Exception:
        return pd.DataFrame(columns=["voce_id", "anno", "mese", "uscite_scadenzario", "n_fatture"])


@st.cache_data(ttl=300, show_spinner=False)
def load_scadenzario_detail(societa: str, voce_id: str, _bq=None) -> pd.DataFrame:
    """Dettaglio fornitori per una voce (roll-forward applicato)."""
    bq = _bq or get_bq()
    sql = f"""
    WITH latest AS (
      SELECT MAX(data_snapshot) AS snap
      FROM `{cfg.F_PARTITE_APERTE_FORNITORI}`
      WHERE societa_id = '{societa}'
    )
    SELECT
      COALESCE(d.nome_pf, p.nome_fornitore) AS fornitore,
      p.data_scadenza,
      GREATEST(p.data_scadenza, DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH)) AS data_effettiva,
      p.importo_abs AS importo,
      p.tipo_documento,
      p.numero_documento,
      p.metodo_pagamento,
      CASE
        WHEN p.data_scadenza < DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH)
          THEN '⚠️ Rolled fwd'
        WHEN p.data_scadenza < DATE_ADD(DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH), INTERVAL 1 MONTH)
          THEN 'In scadenza'
        ELSE 'Futuro'
      END AS stato
    FROM `{cfg.F_PARTITE_APERTE_FORNITORI}` p
    CROSS JOIN latest l
    LEFT JOIN `{cfg.D_FORNITORI}` d ON p.codice_fornitore = d.codice_fornitore
    WHERE p.societa_id = '{societa}'
      AND p.data_snapshot = l.snap
      AND p.is_intercompany = FALSE
      AND d.voce_id = '{voce_id}'
    ORDER BY data_effettiva, p.importo_abs DESC
    """
    try:
        df = bq.query(sql).to_dataframe()
        if not df.empty:
            df["data_scadenza"] = pd.to_datetime(df["data_scadenza"]).dt.strftime("%d/%m/%Y")
            df["data_effettiva"] = pd.to_datetime(df["data_effettiva"]).dt.strftime("%d/%m/%Y")
        return df
    except Exception:
        return pd.DataFrame()


# ── BQ Write ──────────────────────────────────────────────────────────────────

def save_changes(
    societa: str,
    anno: int,
    changes: list[tuple[str, int, float]],
    budget_costi: dict,
    bq,
) -> tuple[int, list[str]]:
    """
    Salva le celle modificate in f_piano_finanziario_input.

    Logica:
      - importo_budget (vista) = budget_costi (f_budget_mensile) + input_manuale (f_pf_input)
      - APP = new_value - budget_costi  → così la vista mostra esattamente new_value
      - DELETE tutti i f_piano_finanziario_input per (voce, mese) — tutte le fonti
      - INSERT una riga con fonte='APP' e importo=APP

    Returns (n_salvate, errori).
    """
    from google.cloud import bigquery as bq_lib

    errors = []
    now = datetime.now(timezone.utc)
    rows_to_insert = []

    for voce_id, mese, new_importo in changes:
        bc = float(budget_costi.get((voce_id, mese), 0.0) or 0.0)
        app_importo = round(new_importo - bc, 2)
        if app_importo < 0:
            app_importo = 0.0  # non possiamo scendere sotto il budget Gasparotto

        rows_to_insert.append({
            "hash_riga":        make_hash(societa, voce_id, str(anno), str(mese), FONTE_APP),
            "societa_id":       societa,
            "voce_id":          voce_id,
            "anno":             anno,
            "mese":             mese,
            "importo":          app_importo,
            "fonte":            FONTE_APP,
            "note":             f"App PF — {date.today().isoformat()}",
            "file_sorgente":    "app_piano_finanziario",
            "data_caricamento": now.isoformat(),
        })

    if not rows_to_insert:
        return 0, []

    try:
        validate_batch(rows_to_insert, PianoFinanziarioInputRow, "App PF save")
    except Exception as e:
        return 0, [f"Validazione: {e}"]

    # DELETE all f_piano_finanziario_input for each changed cell (tutte le fonti)
    for voce_id, mese, _ in changes:
        delete_sql = f"""
        DELETE FROM `{cfg.F_PIANO_FINANZIARIO_INPUT}`
        WHERE societa_id = '{societa}'
          AND voce_id = '{voce_id}'
          AND anno = {anno}
          AND mese = {mese}
        """
        try:
            bq.query(delete_sql).result()
        except Exception as e:
            errors.append(f"DELETE {voce_id}/{mese}: {e}")

    if errors:
        return 0, errors

    # INSERT
    schema = [
        bq_lib.SchemaField("hash_riga",        "STRING",    mode="REQUIRED"),
        bq_lib.SchemaField("societa_id",        "STRING",    mode="REQUIRED"),
        bq_lib.SchemaField("voce_id",           "STRING",    mode="REQUIRED"),
        bq_lib.SchemaField("anno",              "INTEGER",   mode="REQUIRED"),
        bq_lib.SchemaField("mese",              "INTEGER",   mode="REQUIRED"),
        bq_lib.SchemaField("importo",           "FLOAT64"),
        bq_lib.SchemaField("fonte",             "STRING"),
        bq_lib.SchemaField("note",              "STRING"),
        bq_lib.SchemaField("file_sorgente",     "STRING"),
        bq_lib.SchemaField("data_caricamento",  "TIMESTAMP"),
    ]
    try:
        job = bq.load_table_from_json(
            rows_to_insert,
            cfg.F_PIANO_FINANZIARIO_INPUT,
            job_config=bq_lib.LoadJobConfig(
                schema=schema,
                write_disposition=bq_lib.WriteDisposition.WRITE_APPEND,
            ),
        )
        job.result()
    except Exception as e:
        return 0, [f"INSERT: {e}"]

    return len(rows_to_insert), []


# ── Excel Export ──────────────────────────────────────────────────────────────

def generate_excel(societa: str, anno: int) -> bytes:
    """Genera Excel da BQ usando il generatore esistente."""
    from openpyxl import Workbook
    from condges.genera_excel import (
        build_pf_sheet,
        fetch_pf_data,
        fetch_saldo_banca,
        fetch_stagionalita,
        fetch_voci,
    )

    voci = fetch_voci()
    pf_data = fetch_pf_data(anno)
    stag = fetch_stagionalita(anno - 1)
    saldo_tot, saldi_per_banca = fetch_saldo_banca(societa)

    wb = Workbook()
    wb.remove(wb.active)
    build_pf_sheet(
        wb, f"PF {societa}", societa, anno, voci, pf_data, stag,
        saldo_iniziale=saldo_tot, saldi_banca=saldi_per_banca,
    )

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_eur(v) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
        if f != f:  # NaN
            return "—"
        return f"€ {f:,.0f}"
    except (TypeError, ValueError):
        return "—"


def stato_liquidita(saldo: float) -> str:
    if saldo > 50_000:
        return "🟢"
    if saldo > 0:
        return "🟡"
    return "🔴"


def past_months_for_anno(anno: int) -> list[str]:
    today = date.today()
    if anno < today.year:
        return MESI_NOMI[:]
    if anno > today.year:
        return []
    return MESI_NOMI[: today.month - 1]


def build_editor_df(df_pf: pd.DataFrame, sezione: str) -> pd.DataFrame:
    sub = df_pf[df_pf["sezione"] == sezione].sort_values("ord")
    if sub.empty:
        return pd.DataFrame()
    return sub[["voce_label"] + MESI_NOMI].copy()


def make_col_config(past_months: list[str]) -> dict:
    cfg_cols: dict = {
        "voce_label": st.column_config.TextColumn("Voce", disabled=True, width="large"),
    }
    for nome in MESI_NOMI:
        cfg_cols[nome] = st.column_config.NumberColumn(
            nome,
            format="€ %d",
            disabled=(nome in past_months),
            width="small",
            min_value=0,
        )
    return cfg_cols


def totals_row_df(label: str, series: pd.Series) -> pd.DataFrame:
    row = {"voce_label": label}
    row.update({nome: int(round(float(series[nome]))) for nome in MESI_NOMI})
    return pd.DataFrame([row])


# ── Main App ──────────────────────────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title="Piano Finanziario",
        page_icon="💼",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── Sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("Piano Finanziario")
        societa = st.selectbox("Società", ["ORTI", "INTUR"], key="societa")
        anno = st.selectbox("Anno", [2025, 2026, 2027], index=1, key="anno")
        st.divider()
        if st.button("🔄 Ricarica da BigQuery", use_container_width=True):
            st.cache_data.clear()
            # Reset session state for this società/anno
            for k in list(st.session_state.keys()):
                if k.startswith("orig_") or k.startswith("det_"):
                    del st.session_state[k]
            st.rerun()
        st.divider()
        st.caption(
            "**Colori celle:**\n"
            "- ⬛ Consuntivo (non editabile)\n"
            "- ✏️ Previsione (editabile)\n\n"
            "**Stato liquidità:**\n"
            "- 🟢 > €50K\n"
            "- 🟡 €0 – €50K\n"
            "- 🔴 < €0"
        )

    bq = get_bq()

    # ── Load data ─────────────────────────────────────────────────────────────
    with st.spinner("Caricamento dati da BigQuery..."):
        saldi_df     = load_saldi_banca(societa, _bq=bq)
        df_pf, bc    = load_pf_data(societa, anno, _bq=bq)
        scad_agg     = load_scadenzario_agg(societa, _bq=bq)

    if df_pf.empty:
        st.warning(f"Nessun dato PF per {societa} {anno}. Verificare BigQuery.")
        return

    past_months = past_months_for_anno(anno)
    col_cfg = make_col_config(past_months)

    # Conserva i valori originali nella session per il rilevamento modifiche
    orig_key = f"orig_{societa}_{anno}"
    if orig_key not in st.session_state:
        st.session_state[orig_key] = df_pf[MESI_NOMI].copy()
    orig_vals: pd.DataFrame = st.session_state[orig_key]

    # ── Header: Saldo Banca ───────────────────────────────────────────────────
    col_saldo, col_excel = st.columns([3, 1])
    with col_saldo:
        if not saldi_df.empty:
            saldo_tot = float(saldi_df["saldo_finale"].sum())
            data_ancora = pd.to_datetime(saldi_df["data_snapshot"].max()).strftime("%d/%m/%Y")
            st.metric(
                label=f"💰 Saldo Banca {societa} al {data_ancora}",
                value=fmt_eur(saldo_tot),
            )
            cols_b = st.columns(len(saldi_df))
            for i, (_, brow) in enumerate(saldi_df.iterrows()):
                cols_b[i].caption(f"{brow['banca_id']}: {fmt_eur(float(brow['saldo_finale']))}")
        else:
            st.warning("Saldo banca non disponibile — caricare f_saldi_banca_snapshot.")
            saldo_tot = 0.0

    with col_excel:
        st.write("")
        try:
            if st.button("📥 Genera Excel", use_container_width=True):
                with st.spinner("Generazione Excel..."):
                    xlsx = generate_excel(societa, anno)
                st.download_button(
                    label="⬇️ Scarica",
                    data=xlsx,
                    file_name=f"PF_{societa}_{anno}_{date.today().isoformat()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
        except Exception as e:
            st.caption(f"Excel: {e}")

    st.divider()

    # ── ENTRATE ───────────────────────────────────────────────────────────────
    st.subheader("📈 ENTRATE")
    ent_df = build_editor_df(df_pf, "ENTRATE")
    edited_entrate = st.data_editor(
        ent_df,
        column_config=col_cfg,
        hide_index=True,
        use_container_width=True,
        key="editor_entrate",
        num_rows="fixed",
    )
    tot_e = edited_entrate[MESI_NOMI].sum()
    st.dataframe(
        totals_row_df("**TOTALE ENTRATE**", tot_e),
        column_config=make_col_config([]),
        hide_index=True, use_container_width=True,
    )

    st.divider()

    # ── USCITE ────────────────────────────────────────────────────────────────
    st.subheader("📉 USCITE")
    usc_df = build_editor_df(df_pf, "USCITE")
    edited_uscite = st.data_editor(
        usc_df,
        column_config=col_cfg,
        hide_index=True,
        use_container_width=True,
        key="editor_uscite",
        num_rows="fixed",
    )
    tot_u = edited_uscite[MESI_NOMI].sum()
    st.dataframe(
        totals_row_df("**TOTALE USCITE**", tot_u),
        column_config=make_col_config([]),
        hide_index=True, use_container_width=True,
    )

    st.divider()

    # ── Cash Flow + Saldo Proiettato ──────────────────────────────────────────
    st.subheader("💹 Cash Flow e Saldo Proiettato")

    cash_flow = tot_e - tot_u
    saldo_prog = []
    saldo = saldo_tot
    for nome in MESI_NOMI:
        saldo += float(cash_flow[nome])
        saldo_prog.append(saldo)

    summary_rows = [
        {"Voce": "Cash Flow Netto"}
        | {nome: int(round(float(cash_flow[nome]))) for nome in MESI_NOMI},
        {"Voce": "Saldo Proiettato"}
        | {nome: int(round(saldo_prog[i])) for i, nome in enumerate(MESI_NOMI)},
        {"Voce": "Stato"}
        | {nome: stato_liquidita(saldo_prog[i]) for i, nome in enumerate(MESI_NOMI)},
    ]
    sum_col_cfg = {
        "Voce": st.column_config.TextColumn("Voce", disabled=True, width="large"),
        **{nome: st.column_config.TextColumn(nome, disabled=True, width="small") for nome in MESI_NOMI},
    }
    st.dataframe(
        pd.DataFrame(summary_rows),
        column_config=sum_col_cfg,
        hide_index=True, use_container_width=True,
    )

    # ── Scadenzario Drill-down ─────────────────────────────────────────────────
    st.divider()
    st.subheader("📋 Scadenzario Fornitori")

    if scad_agg.empty:
        st.info("Nessun dato scadenzario. Caricare f_partite_aperte_fornitori.")
    else:
        uscite_meta = df_pf[df_pf["sezione"] == "USCITE"].sort_values("ord")

        for voce_id, row in uscite_meta.iterrows():
            voce_scad = scad_agg[scad_agg["voce_id"] == voce_id]
            if voce_scad.empty:
                continue

            total_scad = float(voce_scad["uscite_scadenzario"].sum())
            n_fatt = int(voce_scad["n_fatture"].sum())

            with st.expander(f"▶ {row['voce_label']} — Scadenzario: {fmt_eur(total_scad)} ({n_fatt} fatture)"):
                # Confronto per mese: stima PF vs scadenzario
                scad_per_mese = {
                    MESI_NOMI[int(r.mese) - 1]: float(r.uscite_scadenzario)
                    for r in voce_scad.itertuples()
                    if 1 <= int(r.mese) <= 12
                }
                pf_per_mese = {}
                if voce_id in usc_df.index:
                    pf_per_mese = {nome: float(usc_df.loc[voce_id, nome]) for nome in MESI_NOMI}

                comp = []
                for nome in MESI_NOMI:
                    pf_v = pf_per_mese.get(nome, 0.0)
                    sc_v = scad_per_mese.get(nome, 0.0)
                    if pf_v > 0 or sc_v > 0:
                        comp.append({
                            "Mese":       nome,
                            "Stima PF":   fmt_eur(pf_v),
                            "Scadenzario": fmt_eur(sc_v),
                            "Non coperto": fmt_eur(max(0.0, pf_v - sc_v)),
                        })
                if comp:
                    st.dataframe(pd.DataFrame(comp), hide_index=True, use_container_width=True)

                # Dettaglio per fornitore (lazy, su richiesta)
                det_key = f"det_{societa}_{anno}_{voce_id}"
                if st.button("📋 Carica dettaglio fornitori", key=f"btn_{voce_id}"):
                    with st.spinner("Caricamento dettaglio..."):
                        st.session_state[det_key] = load_scadenzario_detail(
                            societa, voce_id, _bq=bq
                        )

                if det_key in st.session_state and not st.session_state[det_key].empty:
                    detail = st.session_state[det_key]
                    detail["importo"] = detail["importo"].apply(fmt_eur)
                    st.dataframe(
                        detail[["fornitore", "importo", "data_scadenza", "data_effettiva",
                                "metodo_pagamento", "stato"]].rename(columns={
                            "fornitore":        "Fornitore",
                            "importo":          "Importo",
                            "data_scadenza":    "Scadenza",
                            "data_effettiva":   "Effettiva",
                            "metodo_pagamento": "Pagamento",
                            "stato":            "Stato",
                        }),
                        hide_index=True, use_container_width=True,
                    )

    # ── Salva in BigQuery ─────────────────────────────────────────────────────
    st.divider()
    col_btn, col_msg = st.columns([1, 3])

    with col_btn:
        save_clicked = st.button("💾 Salva in BigQuery", type="primary", use_container_width=True)

    if save_clicked:
        changes: list[tuple[str, int, float]] = []

        # Entrate
        for voce_id in edited_entrate.index:
            for nome in MESI_NOMI:
                if nome in past_months:
                    continue
                orig = float(orig_vals.loc[voce_id, nome]) if voce_id in orig_vals.index else 0.0
                new  = float(edited_entrate.loc[voce_id, nome])
                if abs(new - orig) > 0.5:
                    changes.append((voce_id, MESI_NOMI.index(nome) + 1, new))

        # Uscite
        for voce_id in edited_uscite.index:
            for nome in MESI_NOMI:
                if nome in past_months:
                    continue
                orig = float(orig_vals.loc[voce_id, nome]) if voce_id in orig_vals.index else 0.0
                new  = float(edited_uscite.loc[voce_id, nome])
                if abs(new - orig) > 0.5:
                    changes.append((voce_id, MESI_NOMI.index(nome) + 1, new))

        with col_msg:
            if not changes:
                st.info("Nessuna modifica rilevata.")
            else:
                with st.spinner(f"Salvando {len(changes)} celle in BigQuery..."):
                    n_saved, errors = save_changes(societa, anno, changes, bc, bq)

                if errors:
                    st.error("Errori durante il salvataggio:\n" + "\n".join(errors))
                else:
                    st.success(
                        f"✓ {n_saved} celle salvate (fonte=APP). "
                        "Clicca 🔄 nella sidebar per aggiornare la vista."
                    )
                    # Aggiorna i valori originali e invalida la cache
                    del st.session_state[orig_key]
                    st.cache_data.clear()
                    st.rerun()


if __name__ == "__main__":
    main()
