#!/usr/bin/env python3
"""
Budget vs Consuntivo — App Interattiva (Gasparotto)

Dashboard BvA con slider crescita ricavi per BU e coefficienti stagionalità.
Legge da BigQuery, non scrive. Export Excel.

Usage:
    streamlit run condges/bva_app.py
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
import streamlit as st

from core import config as cfg

MESI = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
ANNO_DEFAULT = 2026

# BU inferred from codice_conto prefix
BU_PREFIX = {
    "4791": "HOTEL",
    "4792": "RESIDENCE",
    "4793": "CVM",
    "4794": "LIDO",
    "4795": "HQ",
}

CATEGORIE_ORD = [
    "Ricavi",
    "Acquisti",
    "Costi Produttivi",
    "Costo del Personale",
    "Costi Amministrativi",
    "Costi Commerciali",
    "Oneri Tributari",
    "Oneri Finanziari",
]


@st.cache_resource
def get_bq():
    from google.cloud import bigquery
    return bigquery.Client(project=cfg.PROJECT)


def infer_bu(cod_conto: str) -> str:
    """Infer business unit from codice_conto prefix."""
    for prefix, bu in BU_PREFIX.items():
        if cod_conto.startswith(prefix):
            return bu
    return "HQ"


# ── Data Loading ──────────────────────────────────────────────────────────────


@st.cache_data(ttl=300, show_spinner=False)
def load_budget(societa: str, anno: int, _bq=None) -> pd.DataFrame:
    """Load budget from v_budget: one row per conto, 12 monthly columns."""
    bq = _bq or get_bq()
    sql = f"""
    SELECT cod_conto, codice_conto_display, descrizione,
           tipo_costo, categoria_ce, fonte,
           gen, feb, mar, apr, mag, giu, lug, ago, sett, ott, nov, dic,
           totale_annuo
    FROM `{cfg.V_BUDGET}`
    WHERE societa_id = '{societa}' AND anno = {anno}
    ORDER BY categoria_ce, cod_conto
    """
    df = bq.query(sql).to_dataframe()
    df = df.set_index("cod_conto")
    # Rename sett -> Set for consistency with MESI
    df = df.rename(columns={"sett": "Set"})
    # Capitalize month columns to match MESI
    month_map = {"gen": "Gen", "feb": "Feb", "mar": "Mar", "apr": "Apr",
                 "mag": "Mag", "giu": "Giu", "lug": "Lug", "ago": "Ago",
                 "ott": "Ott", "nov": "Nov", "dic": "Dic"}
    df = df.rename(columns=month_map)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def load_consuntivo(societa: str, anno: int, _bq=None) -> pd.DataFrame:
    """Load consuntivo from f_movimenti_contabili, aggregated by conto × mese."""
    bq = _bq or get_bq()
    sql = f"""
    SELECT
      cod_conto,
      EXTRACT(MONTH FROM data_registrazione) AS mese,
      SUM(imp_dare - imp_avere) AS netto
    FROM `{cfg.F_MOVIMENTI_CONTABILI}`
    WHERE societa_id = '{societa}'
      AND EXTRACT(YEAR FROM data_registrazione) = {anno}
    GROUP BY cod_conto, EXTRACT(MONTH FROM data_registrazione)
    """
    df = bq.query(sql).to_dataframe()
    if df.empty:
        return pd.DataFrame(columns=["cod_conto"] + MESI).set_index("cod_conto")

    # Pivot: rows=cod_conto, cols=mesi
    pivot = df.pivot_table(index="cod_conto", columns="mese", values="netto", fill_value=0.0)
    for m in range(1, 13):
        if m not in pivot.columns:
            pivot[m] = 0.0
    pivot = pivot[[m for m in range(1, 13)]]
    pivot.columns = MESI
    return pivot


@st.cache_data(ttl=300, show_spinner=False)
def load_stagionalita(societa: str, _bq=None) -> pd.DataFrame:
    """Load seasonality coefficients per BU × mese."""
    bq = _bq or get_bq()
    sql = f"""
    SELECT business_unit_id AS bu, mese, coefficiente
    FROM `{cfg.D_COEFFICIENTI_STAGIONALITA}`
    WHERE societa_id = '{societa}'
    ORDER BY bu, mese
    """
    df = bq.query(sql).to_dataframe()
    return df.set_index(["bu", "mese"])


# ── Ricavi Ricalcolo ──────────────────────────────────────────────────────────


def recalc_ricavi(
    budget: pd.DataFrame,
    stag: pd.DataFrame,
    crescita: dict[str, float],
) -> pd.DataFrame:
    """
    Recalculate ricavi rows in budget using growth sliders + seasonality.

    For each ricavo conto:
      1. Infer BU from prefix (47.91=HOTEL, etc.)
      2. Get base annual total (from budget)
      3. Apply growth: annuo_new = annuo_base × (1 + crescita[bu])
      4. Distribute monthly: mese_new = annuo_new × coeff(bu, mese) / 12
    """
    df = budget.copy()
    ricavi_mask = df["categoria_ce"] == "Ricavi"

    for cod_conto in df[ricavi_mask].index:
        bu = infer_bu(cod_conto)
        growth = crescita.get(bu, 0.0)
        annuo_base = float(df.loc[cod_conto, "totale_annuo"])
        annuo_new = annuo_base * (1 + growth)

        for m_idx, nome in enumerate(MESI, 1):
            try:
                coeff = float(stag.loc[(bu, m_idx), "coefficiente"])
            except KeyError:
                coeff = 1.0  # fallback uniform
            df.loc[cod_conto, nome] = annuo_new * coeff / 12.0

        df.loc[cod_conto, "totale_annuo"] = df.loc[cod_conto, MESI].sum()

    return df


def recalc_variabili(
    budget: pd.DataFrame,
    ricavi_orig_totals: pd.Series,
    ricavi_new_totals: pd.Series,
) -> pd.DataFrame:
    """
    Scale variable costs proportionally to ricavi change per month.

    costo_var_mese_new = costo_var_mese_orig × (ricavi_new_mese / ricavi_orig_mese)
    """
    df = budget.copy()
    var_mask = df["tipo_costo"].isin(["V", "IP"]) & (df["categoria_ce"] != "Ricavi")

    for nome in MESI:
        orig = ricavi_orig_totals.get(nome, 0.0)
        new = ricavi_new_totals.get(nome, 0.0)
        if orig > 0:
            ratio = new / orig
        else:
            ratio = 1.0
        df.loc[var_mask, nome] = df.loc[var_mask, nome] * ratio

    # Recalc annual total
    df.loc[var_mask, "totale_annuo"] = df.loc[var_mask, MESI].sum(axis=1)
    return df
