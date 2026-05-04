"""BigQuery reads for tesoreria — shared by Streamlit (cached) and CLI export.

No Streamlit import; safe for ``python -m condges.gen_tesoreria_xlsx``.
"""

from __future__ import annotations

import pandas as pd

from core import config as cfg
from core.bq.client import get_client


def fetch_voci_df() -> pd.DataFrame:
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
    return get_client().query(sql).to_dataframe()


def fetch_consuntivo_df(societa: str, anno: int) -> pd.DataFrame:
    """Aggregate f_movimenti_contabili joined to d_voci (same semantics as load_consuntivo)."""
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
          ON mov.cod_conto LIKE CONCAT(v.cod_conto_pattern, '%')
        WHERE v.fonte = 'ESOLVER'
          AND mov.societa_id = '{societa}'
          AND EXTRACT(YEAR FROM mov.data_registrazione) = {anno}
          AND (v.societa_id IS NULL OR v.societa_id = '{societa}')
        GROUP BY v.voce_id, mese
        ORDER BY v.voce_id, mese
    """
    return get_client().query(sql).to_dataframe()
