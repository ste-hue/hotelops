"""
condges/bq_data.py — Read-only BQ queries for the tesoreria Streamlit app.

All public functions are cached with @st.cache_data(ttl=300).
Queries use f-strings because societa and anno are trusted internal values
(not user-supplied strings).
"""

import pandas as pd
import streamlit as st

from core import config as cfg

from verticals.condges.bq_tesoreria_core import fetch_consuntivo_df, fetch_voci_df

BQ_PROJECT = "hotelops-suite"


def _client():
    from google.cloud import bigquery
    return bigquery.Client(project=BQ_PROJECT)


# ---------------------------------------------------------------------------
# 1. Voci del Piano Finanziario
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_voci() -> pd.DataFrame:
    """Return d_voci_piano_finanziario ordered by ord."""
    return fetch_voci_df()


# ---------------------------------------------------------------------------
# 2. Consuntivo da movimenti contabili
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_consuntivo(societa: str, anno: int) -> pd.DataFrame:
    """
    Aggregate f_movimenti_contabili joined to d_voci via LIKE on cod_conto_pattern.

    Sign convention:
      ENTRATE: SUM(imp_avere - imp_dare)
      USCITE:  SUM(imp_dare - imp_avere)

    Returns columns: voce_id, mese, importo_consuntivo
    """
    return fetch_consuntivo_df(societa, anno)


# ---------------------------------------------------------------------------
# 3. Budget mensile
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_budget(societa: str, anno: int) -> pd.DataFrame:
    """
    Aggregate f_budget_mensile joined to d_voci via LIKE on cod_conto_pattern.

    Returns columns: voce_id, mese, importo_budget
    """
    sql = f"""
        SELECT
            v.voce_id,
            b.mese,
            SUM(b.importo) AS importo_budget
        FROM `{cfg.F_BUDGET_MENSILE}` AS b
        JOIN `{cfg.D_VOCI_PIANO_FINANZIARIO}` AS v
          ON REPLACE(b.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pattern, '%')
        WHERE v.fonte = 'ESOLVER'
          AND b.societa_id = '{societa}'
          AND b.anno = {anno}
          AND (v.societa_id IS NULL OR v.societa_id = '{societa}')
        GROUP BY v.voce_id, b.mese
        ORDER BY v.voce_id, b.mese
    """
    return _client().query(sql).to_dataframe()


# ---------------------------------------------------------------------------
# 4. Mapping detail (drill-down)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_mapping_detail(societa: str) -> pd.DataFrame:
    """
    Return d_mapping_piano_finanziario rows for a given societa.

    Returns columns: voce_id, sotto_voce, tipo, codice_fornitore,
                     cod_conto_pattern, nome_esolver
    """
    sql = f"""
        SELECT
            voce_id,
            sotto_voce,
            tipo,
            codice_fornitore,
            cod_conto_pattern,
            nome_esolver
        FROM `{cfg.D_MAPPING_PIANO_FINANZIARIO}`
        WHERE societa_id = '{societa}'
        ORDER BY voce_id, sotto_voce
    """
    return _client().query(sql).to_dataframe()


# ---------------------------------------------------------------------------
# 5. Consuntivo detail (drill-down per codice conto)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_consuntivo_detail(societa: str, anno: int) -> pd.DataFrame:
    """
    Aggregate f_movimenti_contabili per codice_conto x mese for drill-down.

    Returns columns: codice_conto, descrizione, mese, importo
    """
    sql = f"""
        SELECT
            mov.cod_conto,
            mov.rag_sociale AS descrizione,
            EXTRACT(MONTH FROM mov.data_registrazione) AS mese,
            SUM(mov.imp_dare - mov.imp_avere) AS importo
        FROM `{cfg.F_MOVIMENTI_CONTABILI}` AS mov
        WHERE mov.societa_id = '{societa}'
          AND EXTRACT(YEAR FROM mov.data_registrazione) = {anno}
        GROUP BY mov.cod_conto, mov.rag_sociale, mese
        ORDER BY mov.cod_conto, mese
    """
    return _client().query(sql).to_dataframe()


# ---------------------------------------------------------------------------
# 6. Categorie conti
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_categorie() -> pd.DataFrame:
    """
    Return d_categorie_conti.

    Returns columns: codice_conto, tipo_costo, categoria_ce
    """
    sql = f"""
        SELECT
            codice_conto,
            tipo_costo,
            categoria_ce
        FROM `{cfg.D_CATEGORIE_CONTI}`
        ORDER BY codice_conto
    """
    return _client().query(sql).to_dataframe()


# ---------------------------------------------------------------------------
# 7. Budget vs Consuntivo (BvA)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_bva(societa: str, anno: int) -> pd.DataFrame:
    """
    Load v_budget_vs_consuntivo for a given societa/anno.

    Returns columns: codice_conto_display, descrizione, categoria_ce, mese,
                     budget, consuntivo, delta, status
    """
    sql = f"""
        SELECT
            codice_conto_display,
            descrizione,
            categoria_ce,
            mese,
            ROUND(budget, 0) AS budget,
            ROUND(consuntivo, 0) AS consuntivo,
            ROUND(delta, 0) AS delta,
            status
        FROM `{cfg.V_BUDGET_VS_CONSUNTIVO}`
        WHERE societa_id = '{societa}'
          AND anno = {anno}
        ORDER BY categoria_ce, codice_conto_display, mese
    """
    return _client().query(sql).to_dataframe()
