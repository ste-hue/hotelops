"""Data layer dashboard F&B — query BQ + helper puri. Zero Streamlit.

Importabile dal futuro hub (verticals/hub/) e da fb_dashboard.render().
Spec: docs/superpowers/specs/2026-06-12-fb-dashboard-streamlit-design.md
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def align_yoy_daily(df: pd.DataFrame, date_col: str = "data") -> pd.DataFrame:
    """Aggiunge colonne ``<col>_ap`` allineate allo stesso giorno-calendario
    dell'anno precedente. Il 29/02 non ha corrispondente nell'anno non
    bisestile e viene scartato dal lato anno-precedente.
    """

    def _plus_one_year(d: date) -> date | None:
        try:
            return d.replace(year=d.year + 1)
        except ValueError:  # 29/02 -> anno successivo non bisestile
            return None

    prev = df.copy()
    prev[date_col] = prev[date_col].map(_plus_one_year)
    prev = prev.dropna(subset=[date_col])
    value_cols = [c for c in df.columns if c != date_col]
    prev = prev.rename(columns={c: f"{c}_ap" for c in value_cols})
    return df.merge(prev, on=date_col, how="left")


def freshness_badge(granularita: str, ultimo_dato: str, oggi: date) -> str:
    """⚠️ se la fonte è indietro: giornaliera >3 giorni, mensile se manca
    l'ultimo mese chiuso. ``ultimo_dato``: 'YYYY-MM-DD' o 'YYYY-MM'."""
    if granularita == "giornaliera":
        ritardo = (oggi - date.fromisoformat(ultimo_dato)).days
        return "⚠️" if ritardo > 3 else "✅"
    anno, mese = (int(p) for p in ultimo_dato.split("-"))
    ultimo_chiuso = oggi.replace(day=1) - timedelta(days=1)
    indietro = (anno, mese) < (ultimo_chiuso.year, ultimo_chiuso.month)
    return "⚠️" if indietro else "✅"


def kpi_or_nd(pct: float | None, costo_totale: float, coperti: int) -> str:
    """Formatta un KPI %: 'n/d' se i consumi mensili non sono ancora caricati
    (costo 0 ma coperti presenti), '—' se il mese è proprio vuoto."""
    if not costo_totale:
        return "n/d" if coperti else "—"
    if pct is None or pd.isna(pct):
        return "n/d"
    return f"{pct * 100:.1f}%"
