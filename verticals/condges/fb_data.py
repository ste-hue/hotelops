"""Data layer dashboard F&B — query BQ + helper puri. Zero Streamlit.

Importabile dal futuro hub (verticals/hub/) e da fb_dashboard.render().
Spec: docs/superpowers/specs/2026-06-12-fb-dashboard-streamlit-design.md
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from core.bq.client import get_client
from core.config import (
    F_CONSUMI_ECONOMATO,
    F_COPERTI_GIORNALIERI,
    F_PRODUZIONE_PMS,
    F_RICAVI_FB,
    F_RISTOCUBE_ORDERS,
    F_VENDITE_FB,
    V_FB_CONSUMI,
    V_FB_KPI,
    V_FB_PASTI,
    V_FB_RICAVI,
)


def _q(sql: str) -> pd.DataFrame:
    return get_client().query(sql).to_dataframe()


def _mensa_predicate(includi_mensa: bool) -> str:
    """Predicato SQL per i coperti: di default esclude la **mensa dipendenti**
    (``business_unit_id = 'HQ'``) — è un costo senza ricavo e gonfia i coperti.
    ``includi_mensa=True`` → stringa vuota (nessun filtro).
    """
    return "" if includi_mensa else "COALESCE(business_unit_id, '') != 'HQ'"


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


# ---------------------------------------------------------------------------
# Query mensili
# ---------------------------------------------------------------------------


def kpi_mensili(anno: int) -> pd.DataFrame:
    """KPI F&B mensili da v_fb_kpi (3 bucket onesti + colonne _ap)."""
    return _q(f"SELECT * FROM `{V_FB_KPI}` WHERE anno = {int(anno)} ORDER BY mese")


_YOY_COLS = [
    "coperti_hotel",
    "ricavi_fb_totale",
    "costo_fb_totale",
    "euro_per_pasto",
    "food_cost_pct_breakfast",
    "food_cost_pct_ristorante",
    "food_cost_pct_bar",
]


def join_yoy(cur: pd.DataFrame, prev: pd.DataFrame) -> pd.DataFrame:
    """Affianca ai KPI mensili di ``cur`` quelli di ``prev`` (suffisso ``_prec``),
    join su mese. Pura (niente BQ): testabile con fixture."""
    out, p = cur.copy(), prev.copy()
    for df in (out, p):
        df["ricavi_fb_totale"] = (
            df["ricavi_breakfast"] + df["ricavi_food"] + df["ricavi_beverage"]
        )
    p = p[["mese", *_YOY_COLS]].rename(columns={c: f"{c}_prec" for c in _YOY_COLS})
    return out.merge(p, on="mese", how="left")


def kpi_yoy(anno: int) -> pd.DataFrame:
    """KPI mensili anno vs anno-1 (v_fb_kpi due volte, join su mese)."""
    return join_yoy(kpi_mensili(anno), kpi_mensili(anno - 1))


def ricavi_tipo_pasto_yoy(anno: int) -> pd.DataFrame:
    """Ricavi F&B per tipo pasto, anno vs anno-1 a parità di periodo:
    l'anno precedente è tagliato all'ultimo mese con ricavi dell'anno scelto
    (altrimenti a stagione in corso si confronterebbe col 2025 intero)."""
    a, p = int(anno), int(anno) - 1
    return _q(f"""
        WITH mese_max AS (
          SELECT MAX(mese) AS m FROM `{V_FB_RICAVI}` WHERE anno = {a} AND netto > 0
        )
        SELECT tipo_pasto,
          SUM(IF(anno = {a}, netto, 0)) AS ricavo,
          SUM(IF(anno = {p}, netto, 0)) AS ricavo_prec
        FROM `{V_FB_RICAVI}`, mese_max
        WHERE anno IN ({a}, {p}) AND tipo_pasto IS NOT NULL AND mese <= mese_max.m
        GROUP BY tipo_pasto ORDER BY ricavo DESC
    """)


def consumi(anno: int, solo_fb: bool = True) -> pd.DataFrame:
    """Costo merce per prodotto da v_fb_consumi.

    Default: solo reparti F&B e senza righe anomale (storni UoM mag-2025).
    """
    where = f"anno = {int(anno)}"
    if solo_fb:
        where += " AND is_fb_reparto AND NOT is_anomalia"
    return _q(f"SELECT * FROM `{V_FB_CONSUMI}` WHERE {where} ORDER BY mese, costo DESC")


def ricavi_codici(anno: int) -> pd.DataFrame:
    """Ricavi produzione netta per codice da v_fb_ricavi (tutte le classi)."""
    return _q(
        f"SELECT * FROM `{V_FB_RICAVI}` WHERE anno = {int(anno)} "
        "ORDER BY mese, netto DESC"
    )


def pasti(anno: int) -> pd.DataFrame:
    """Coperti pasto mensili da v_fb_pasti (is_staff esposto, non sommato)."""
    return _q(f"SELECT * FROM `{V_FB_PASTI}` WHERE anno = {int(anno)} ORDER BY mese")


# ---------------------------------------------------------------------------
# Query giornaliere e freshness
# ---------------------------------------------------------------------------


def stagione_giornaliera(anno: int, includi_mensa: bool = False) -> pd.DataFrame:
    """Una riga per giorno dell'anno: ricavi F&B PMS (classe 02FB), vendite
    POS, coperti. Colonne ``*_ap`` = stesso giorno-calendario anno precedente
    (allineamento in pandas via align_yoy_daily).

    ``includi_mensa=False`` (default): i coperti **escludono la mensa dipendenti**
    (BU 'HQ'). ``True`` la include.
    """
    pred = _mensa_predicate(includi_mensa)
    cop_where = f"WHERE {pred}" if pred else ""
    sql = f"""
    WITH prod AS (
      SELECT data, SUM(importo_imponibile) AS ricavi_fb_pms
      FROM `{F_PRODUZIONE_PMS}`
      WHERE classe = '02FB'
      GROUP BY data
    ), pos AS (
      SELECT data_servizio AS data, SUM(importo_netto) AS vendite_pos
      FROM `{F_VENDITE_FB}`
      GROUP BY 1
    ), cop AS (
      SELECT data_servizio AS data, SUM(n_coperti) AS coperti
      FROM `{F_COPERTI_GIORNALIERI}`
      {cop_where}
      GROUP BY 1
    ), giorni AS (
      SELECT data FROM prod
      UNION DISTINCT SELECT data FROM pos
      UNION DISTINCT SELECT data FROM cop
    )
    SELECT g.data, p.ricavi_fb_pms, v.vendite_pos, c.coperti
    FROM giorni g
    LEFT JOIN prod p USING (data)
    LEFT JOIN pos v USING (data)
    LEFT JOIN cop c USING (data)
    WHERE EXTRACT(YEAR FROM g.data) IN ({int(anno)}, {int(anno) - 1})
    ORDER BY g.data
    """
    df = _q(sql)
    df["data"] = pd.to_datetime(df["data"]).dt.date
    for col in ("ricavi_fb_pms", "vendite_pos", "coperti"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    aligned = align_yoy_daily(df, "data")
    correnti = aligned["data"].map(lambda d: d.year) == int(anno)
    return aligned[correnti].reset_index(drop=True)


def coperti_giornalieri(anno: int, includi_mensa: bool = False) -> pd.DataFrame:
    """Coperti per giorno × tipo_pasto (anno corrente).

    ``includi_mensa=False`` (default) esclude la mensa dipendenti (BU 'HQ').
    """
    pred = _mensa_predicate(includi_mensa)
    where = f"anno = {int(anno)}" + (f" AND {pred}" if pred else "")
    return _q(f"""
    SELECT data_servizio AS data, tipo_pasto, SUM(n_coperti) AS coperti
    FROM `{F_COPERTI_GIORNALIERI}`
    WHERE {where}
    GROUP BY 1, 2
    ORDER BY 1, 2
    """)


def vendite_per_sala(anno: int, ultimi_giorni: int = 30) -> pd.DataFrame:
    """Vendite POS giorno × sala, ultimi N giorni con dati."""
    return _q(f"""
    SELECT data_servizio AS data, sala, SUM(importo_netto) AS netto
    FROM `{F_VENDITE_FB}`
    WHERE anno = {int(anno)}
      AND data_servizio >= DATE_SUB(
        (SELECT MAX(data_servizio) FROM `{F_VENDITE_FB}` WHERE anno = {int(anno)}),
        INTERVAL {int(ultimi_giorni)} DAY)
    GROUP BY 1, 2
    ORDER BY 1, 2
    """)


def freshness() -> pd.DataFrame:
    """Ultima data disponibile per fonte F&B.

    Colonne: tabella, granularita ('giornaliera'|'mensile'), ultimo_dato
    ('YYYY-MM-DD' o 'YYYY-MM') — formato consumato da freshness_badge.
    """
    return _q(f"""
    SELECT 'coperti giornalieri' AS tabella, 'giornaliera' AS granularita,
           CAST(MAX(data_servizio) AS STRING) AS ultimo_dato
    FROM `{F_COPERTI_GIORNALIERI}`
    UNION ALL
    SELECT 'vendite POS', 'giornaliera', CAST(MAX(data_servizio) AS STRING)
    FROM `{F_VENDITE_FB}`
    UNION ALL
    SELECT 'comande RistoCube', 'giornaliera', CAST(MAX(data) AS STRING)
    FROM `{F_RISTOCUBE_ORDERS}`
    UNION ALL
    SELECT 'produzione PMS', 'giornaliera', CAST(MAX(data) AS STRING)
    FROM `{F_PRODUZIONE_PMS}`
    UNION ALL
    SELECT 'consumi economato', 'mensile',
           FORMAT('%d-%02d', MAX(anno), MAX_BY(mese, anno * 100 + mese))
    FROM `{F_CONSUMI_ECONOMATO}`
    UNION ALL
    SELECT 'ricavi F&B mensili', 'mensile',
           FORMAT('%d-%02d', MAX(anno), MAX_BY(mese, anno * 100 + mese))
    FROM `{F_RICAVI_FB}`
    ORDER BY granularita, tabella
    """)
