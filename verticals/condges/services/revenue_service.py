"""Servizi dati per la superficie Revenue."""

from __future__ import annotations

import pandas as pd

from core.bq.client import get_client
from core.config import V_BOOKING_CURVE


def load_booking_curve() -> pd.DataFrame:
    sql = (
        f"SELECT * FROM `{V_BOOKING_CURVE}` "
        "ORDER BY business_unit_id, mese_soggiorno, snapshot_date"
    )
    df = get_client().query(sql).to_dataframe()
    for column in ("snapshot_date", "mese_soggiorno"):
        df[column] = pd.to_datetime(df[column]).dt.date
    return df
