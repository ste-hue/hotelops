"""
condges/bq_data.py — Read-only BQ queries for the tesoreria Streamlit app.

All public functions are cached with @st.cache_data(ttl=300).
Queries use f-strings because societa and anno are trusted internal values
(not user-supplied strings).
"""

import pandas as pd
import streamlit as st

from core import config as cfg

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
    sql = f"""
        SELECT
            voce_id,
            voce_label,
            sezione,
            categoria,
            ord,
            societa_id,
            categoria_ce,
            tipo_costo
        FROM `{cfg.D_VOCI_PIANO_FINANZIARIO}`
        ORDER BY ord
    """
    return _client().query(sql).to_dataframe()


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
    sql = f"""
        SELECT
            v.voce_id,
            EXTRACT(MONTH FROM mov.data_registrazione) AS mese,
            SUM(
                CASE v.sezione
                    WHEN 'ENTRATE' THEN mov.imp_avere - mov.imp_dare
                    ELSE                 mov.imp_dare  - mov.imp_avere
                END
            ) AS importo_consuntivo
        FROM `{cfg.F_MOVIMENTI_CONTABILI}` AS mov
        JOIN `{cfg.D_VOCI_PIANO_FINANZIARIO}` AS v
          ON REPLACE(mov.codice_conto, '.', '') LIKE v.cod_conto_pattern
        WHERE v.fonte = 'ESOLVER'
          AND mov.societa_id = '{societa}'
          AND EXTRACT(YEAR FROM mov.data_registrazione) = {anno}
          AND (v.societa_id IS NULL OR v.societa_id = '{societa}')
        GROUP BY v.voce_id, mese
        ORDER BY v.voce_id, mese
    """
    return _client().query(sql).to_dataframe()


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
          ON REPLACE(b.codice_conto, '.', '') LIKE v.cod_conto_pattern
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
            mov.codice_conto,
            mov.descrizione_conto AS descrizione,
            EXTRACT(MONTH FROM mov.data_registrazione) AS mese,
            SUM(mov.imp_dare - mov.imp_avere) AS importo
        FROM `{cfg.F_MOVIMENTI_CONTABILI}` AS mov
        WHERE mov.societa_id = '{societa}'
          AND EXTRACT(YEAR FROM mov.data_registrazione) = {anno}
        GROUP BY mov.codice_conto, mov.descrizione_conto, mese
        ORDER BY mov.codice_conto, mese
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
