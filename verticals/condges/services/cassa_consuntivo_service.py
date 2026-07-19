"""Servizi dati per la pagina hub di cassa consuntivo."""

from __future__ import annotations

import pandas as pd
from google.cloud import bigquery

from core.bq.client import get_client
from core.config import V_CASH_POSITION
from verticals.condges.cashflow_consuntivo_data import (
    classificato_mensile,
    consolidato_societa,
    detect_trasferimenti_interni,
    fetch_movimenti_mese,
)


def load_cash_position(societa: str) -> pd.DataFrame:
    sql = f"""
    SELECT mese, banca_id, saldo_iniziale_cert, accrediti, addebiti, netto,
           saldo_calcolato, saldo_finale_cert, scarto
    FROM `{V_CASH_POSITION}`
    WHERE societa_id = @societa
    ORDER BY mese DESC, banca_id
    """
    job = get_client().query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("societa", "STRING", societa)
            ]
        ),
    )
    return job.to_dataframe()


def load_consolidato(societa: str, anno: int, mese: int) -> dict:
    movs = fetch_movimenti_mese(societa, anno, mese)
    return consolidato_societa(detect_trasferimenti_interni(movs))


def load_classificato(societa: str, anno: int, mese: int) -> dict:
    return classificato_mensile(societa, anno, mese)
