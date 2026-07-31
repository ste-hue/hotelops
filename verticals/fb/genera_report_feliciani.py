#!/usr/bin/env python3
"""Report Excel F&B giornaliero per il consulente Feliciani.

4 sheet: Riepilogo Giornaliero, Breakdown Categorie, Top Articoli, Trend Settimanale.
Fonte: v_fb_giornaliero (KPI data × servizio) + f_ristocube_orders (top articoli).
Base ricavi = LORDO IVA (RistoCube nativo).

Usage:
    python -m verticals.fb.genera_report_feliciani [--output X.xlsx] [--days 30]
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from core.config import DATASET, PROJECT

log = logging.getLogger("fb.report_feliciani")

SERVIZIO_ORDER = {"pranzo": 0, "cena": 1, "bar": 2, "altro": 3}

FMT_EURO = "#,##0.00 €"
FMT_RATIO = "0.00"
FMT_INT = "#,##0"
FMT_PCT = "+0.0%;-0.0%"

# Stessa classificazione della vista v_fb_giornaliero (mapping f_vendite_fb + fallback prefisso)
_SQL_CATEGORIA = """
COALESCE(
  m.tipo_piatto,
  CASE
    WHEN STARTS_WITH(o.item_codice_pos, 'COP') THEN 'COPERTO'
    WHEN STARTS_WITH(o.item_codice_pos, 'AD.') THEN 'ANTIPASTI'
    WHEN STARTS_WITH(o.item_codice_pos, 'ANT') THEN 'ANTIPASTI'
    WHEN STARTS_WITH(o.item_codice_pos, 'PD.') THEN 'PRIMI PIATTI'
    WHEN STARTS_WITH(o.item_codice_pos, 'SD.') THEN 'SECONDI PIATTI'
    WHEN STARTS_WITH(o.item_codice_pos, 'DD.') THEN 'DESSERT'
    WHEN STARTS_WITH(o.item_codice_pos, 'CD.') THEN 'CONTORNI D.'
    WHEN STARTS_WITH(o.item_codice_pos, 'LU') THEN 'LUNCH'
    WHEN STARTS_WITH(o.item_codice_pos, 'SO') THEN 'SOFT DRINK'
    WHEN STARTS_WITH(o.item_codice_pos, 'BI') THEN 'BIRRE'
    WHEN STARTS_WITH(o.item_codice_pos, 'VI') THEN 'VINI'
    WHEN STARTS_WITH(o.item_codice_pos, 'CO') THEN 'COCKTAIL'
    WHEN STARTS_WITH(o.item_codice_pos, 'CA') THEN 'CAFFETTERIA'
    WHEN STARTS_WITH(o.item_codice_pos, 'LI') THEN 'LIQUORI'
    ELSE 'ALTRO'
  END
)
"""


def query_giornaliero(client, days: int) -> pd.DataFrame:
    q = f"""
    SELECT * FROM `{PROJECT}.{DATASET}.v_fb_giornaliero`
    WHERE data >= DATE_SUB(
      (SELECT MAX(data) FROM `{PROJECT}.{DATASET}.v_fb_giornaliero`),
      INTERVAL @days - 1 DAY)
    ORDER BY data, servizio
    """
    from google.cloud import bigquery

    job = client.query(
        q,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", days)]
        ),
    )
    df = pd.DataFrame([dict(r) for r in job.result()])
    if df.empty:
        return df
    df["_ord"] = df["servizio"].map(SERVIZIO_ORDER).fillna(9)
    return df.sort_values(["data", "_ord"]).drop(columns="_ord").reset_index(drop=True)


def query_top_articoli(client, days: int, limit: int = 40) -> pd.DataFrame:
    q = f"""
    WITH mapping AS (
      SELECT codice_articolo, ANY_VALUE(NULLIF(tipo_piatto, '')) AS tipo_piatto
      FROM `{PROJECT}.{DATASET}.f_vendite_fb` GROUP BY 1
    ),
    periodo AS (
      SELECT MAX(data) AS dmax FROM `{PROJECT}.{DATASET}.f_ristocube_orders`
    )
    SELECT
      COALESCE(ANY_VALUE(o.item_descrizione), o.item_codice_pos) AS articolo,
      {_SQL_CATEGORIA} AS categoria,
      SUM(o.item_quantita) AS qty,
      SUM(o.item_importo_finale) AS ricavo
    FROM `{PROJECT}.{DATASET}.f_ristocube_orders` o
    LEFT JOIN mapping m ON o.item_codice_pos = m.codice_articolo
    CROSS JOIN periodo p
    WHERE o.data >= DATE_SUB(p.dmax, INTERVAL @days - 1 DAY)
      AND o.item_codice_pos != 'Articolo POS'
      AND NOT STARTS_WITH(o.item_codice_pos, 'COP')
    GROUP BY o.item_codice_pos, m.tipo_piatto
    ORDER BY qty DESC
    LIMIT @limit
    """
    from google.cloud import bigquery

    job = client.query(
        q,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("days", "INT64", days),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
            ]
        ),
    )
    return pd.DataFrame([dict(r) for r in job.result()])


PASTO_ORDER = {"BRK": 0, "LUNCH": 1, "DINNER": 2}


def query_coperti_completi(client, days: int) -> pd.DataFrame:
    from google.cloud import bigquery

    q = f"""
    SELECT * FROM `{PROJECT}.{DATASET}.v_fb_coperti_giornaliero`
    WHERE data_servizio >= DATE_SUB(
      (SELECT MAX(data_servizio) FROM `{PROJECT}.{DATASET}.v_fb_coperti_giornaliero`),
      INTERVAL @days - 1 DAY)
    """
    job = client.query(
        q,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("days", "INT64", days)]
        ),
    )
    df = pd.DataFrame([dict(r) for r in job.result()])
    if df.empty:
        return df
    df["_ord"] = df["tipo_pasto"].map(PASTO_ORDER).fillna(9)
    return (
        df.sort_values(["data_servizio", "_ord"]).drop(columns="_ord").reset_index(drop=True)
    )


def add_sheet_coperti(wb: Workbook, df: pd.DataFrame) -> None:
    ws = wb.create_sheet("Coperti Completi")
    rows = [
        [r["data_servizio"], r["tipo_pasto"], r["hotel"], r["residence"], r["cvm"],
         r["esterni"], r["paganti"], r["dipendenti"], r["courtesy_pm"], r["totale"]]
        for _, r in df.iterrows()
    ]
    _write_sheet(
        ws,
        ["Data", "Pasto", "Hotel", "Residence", "CVM", "Esterni", "Paganti",
         "Dipendenti", "Courtesy/PM", "Totale"],
        rows,
        dict.fromkeys(range(2, 10), FMT_INT),
    )


def build_trend_settimanale(df: pd.DataFrame) -> pd.DataFrame:
    """Aggrega il giornaliero per settimana ISO (lun-dom) con Δ% vs settimana precedente."""
    if df.empty:
        return pd.DataFrame()
    g = df.copy()
    g["data"] = pd.to_datetime(g["data"])
    g["settimana"] = g["data"].dt.to_period("W-SUN")
    wk = (
        g.groupby("settimana", sort=True)
        .agg(
            coperti=("coperti", "sum"),
            ricavi=("ricavi", "sum"),
            giorni=("data", "nunique"),
        )
        .reset_index()
    )
    wk["coperto_medio"] = wk["ricavi"] / wk["coperti"].replace(0, pd.NA)
    wk["delta_coperti_pct"] = wk["coperti"].pct_change()
    wk["delta_ricavi_pct"] = wk["ricavi"].pct_change()
    # Settimane incomplete: il confronto col totale della settimana piena è fuorviante
    parziale = wk["giorni"] < 7
    wk.loc[parziale, ["delta_coperti_pct", "delta_ricavi_pct"]] = pd.NA
    wk.loc[
        parziale.shift(1, fill_value=False), ["delta_coperti_pct", "delta_ricavi_pct"]
    ] = pd.NA
    # Settimane non consecutive (buco stagionale): Δ% oltre il buco non ha senso
    ordinali = wk["settimana"].map(lambda p: p.ordinal)
    non_consecutive = ordinali.diff() != 1
    non_consecutive.iloc[0] = False  # la prima ha già Δ% NA da pct_change
    wk.loc[non_consecutive, ["delta_coperti_pct", "delta_ricavi_pct"]] = pd.NA
    wk["settimana"] = wk["settimana"].astype(str) + parziale.map(
        {True: " (parziale)", False: ""}
    )
    return (
        wk.drop(columns="giorni").iloc[::-1].reset_index(drop=True)
    )  # più recente in alto


def _style_header(ws, ncols: int) -> None:
    fill = PatternFill("solid", fgColor="1F4E5F")
    for col in range(1, ncols + 1):
        cell = ws.cell(row=1, column=col)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill
        cell.alignment = Alignment(horizontal="center")
    ws.freeze_panes = "A2"


def _write_sheet(
    ws, headers: list[str], rows: list[list], formats: dict[int, str]
) -> None:
    """headers, poi righe; formats = {col_index_0based: number_format}."""
    thin = Border(bottom=Side(style="thin", color="D9D9D9"))
    ws.append(headers)
    for row in rows:
        ws.append(row)
    for r in range(2, ws.max_row + 1):
        for c0, fmt in formats.items():
            ws.cell(row=r, column=c0 + 1).number_format = fmt
        for c in range(1, len(headers) + 1):
            ws.cell(row=r, column=c).border = thin
    for c, h in enumerate(headers, start=1):
        width = max(len(h) + 2, 12)
        ws.column_dimensions[get_column_letter(c)].width = width
    _style_header(ws, len(headers))


def build_workbook(
    df_giorni: pd.DataFrame, df_top: pd.DataFrame, df_trend: pd.DataFrame
) -> Workbook:
    wb = Workbook()

    # Sheet 1 — Riepilogo Giornaliero
    ws = wb.active
    ws.title = "Riepilogo Giornaliero"
    rows = [
        [
            r["data"],
            r["servizio"].capitalize(),
            r["n_comande"],
            r["coperti"],
            r["ricavi"],
            r["coperto_medio"],
            r["articoli"],
            r["articoli_per_coperto"],
        ]
        for _, r in df_giorni.iterrows()
    ]
    _write_sheet(
        ws,
        [
            "Data",
            "Servizio",
            "Comande",
            "Coperti",
            "Ricavi",
            "Coperto Medio",
            "Articoli",
            "Art/Coperto",
        ],
        rows,
        {2: FMT_INT, 3: FMT_INT, 4: FMT_EURO, 5: FMT_EURO, 6: FMT_INT, 7: FMT_RATIO},
    )

    # Sheet 2 — Breakdown Categorie (per coperto)
    ws2 = wb.create_sheet("Breakdown Categorie")
    rows2 = [
        [
            r["data"],
            r["servizio"].capitalize(),
            r["bevande_per_coperto"],
            r["food_per_coperto"],
            r["antipasti_per_coperto"],
            r["primi_per_coperto"],
            r["secondi_per_coperto"],
            r["dessert_per_coperto"],
            r["bottiglie_vino_per_10_coperti"],
        ]
        for _, r in df_giorni.iterrows()
    ]
    _write_sheet(
        ws2,
        [
            "Data",
            "Servizio",
            "Bevande/Cop",
            "Food/Cop",
            "Antipasti/Cop",
            "Primi/Cop",
            "Secondi/Cop",
            "Dessert/Cop",
            "Bott. Vino/10 Cop",
        ],
        rows2,
        dict.fromkeys(range(2, 9), FMT_RATIO),
    )

    # Sheet 3 — Top Articoli (coperti esclusi)
    ws3 = wb.create_sheet("Top Articoli")
    qty_tot = float(df_top["qty"].sum()) if not df_top.empty else 0.0
    rows3 = [
        [
            r["articolo"],
            r["categoria"],
            r["qty"],
            (r["qty"] / qty_tot) if qty_tot else None,
            r["ricavo"],
        ]
        for _, r in df_top.iterrows()
    ]
    _write_sheet(
        ws3,
        ["Articolo", "Categoria", "Qty Totale", "% su Top", "Ricavo Generato"],
        rows3,
        {2: FMT_INT, 3: "0.0%", 4: FMT_EURO},
    )
    ws3.column_dimensions["A"].width = 38

    # Sheet 4 — Trend Settimanale
    ws4 = wb.create_sheet("Trend Settimanale")
    rows4 = [
        [
            r["settimana"],
            r["coperti"],
            r["ricavi"],
            r["coperto_medio"],
            r["delta_coperti_pct"],
            r["delta_ricavi_pct"],
        ]
        for _, r in df_trend.iterrows()
    ]
    _write_sheet(
        ws4,
        [
            "Settimana (lun-dom)",
            "Coperti",
            "Ricavi",
            "Coperto Medio",
            "Δ% Coperti",
            "Δ% Ricavi",
        ],
        rows4,
        {1: FMT_INT, 2: FMT_EURO, 3: FMT_EURO, 4: FMT_PCT, 5: FMT_PCT},
    )
    ws4.column_dimensions["A"].width = 22

    return wb


def genera_report(output_path: str, days: int = 30) -> str:
    from google.cloud import bigquery

    client = bigquery.Client(project=PROJECT)
    df_giorni = query_giornaliero(client, days)
    if df_giorni.empty:
        raise SystemExit("Nessun dato in v_fb_giornaliero — verifica la vista/ingest.")
    df_top = query_top_articoli(client, days)
    df_trend = build_trend_settimanale(df_giorni)

    wb = build_workbook(df_giorni, df_top, df_trend)
    wb.save(output_path)
    log.info(
        "OK %s — periodo %s → %s, %d righe giornaliere",
        output_path,
        df_giorni["data"].min(),
        df_giorni["data"].max(),
        len(df_giorni),
    )
    return output_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Report Excel F&B per Feliciani")
    ap.add_argument(
        "--output",
        default=f"report_fb_feliciani_{date.today():%Y%m%d}.xlsx",
        help="path Excel di output",
    )
    ap.add_argument("--days", type=int, default=30, help="giorni coperti (default 30)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    genera_report(args.output, days=args.days)


if __name__ == "__main__":
    main()
