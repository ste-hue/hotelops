#!/usr/bin/env python3
"""
Genera Piano Finanziario Excel da BigQuery.

Produce un XLSX con il formato che Rosa conosce, ma alimentato da dati reali:
  - Foglio "PF ORTI": 28 voci × 12 mesi, consuntivo + previsione
  - Foglio "PF INTUR": idem
  - Foglio "Stagionalità 2025": pattern mensile ricavi/costi anno precedente
  - Foglio "Riepilogo": totali entrate/uscite/cash flow per mese

Colori:
  - Nero: consuntivo (dati reali da Esolver/Banche)
  - Blu: previsione (da f_piano_finanziario_input, modificabile)
  - Verde: formule (totali)
  - Giallo sfondo: celle da aggiornare con Rosa

Usage:
    python -m actions.genera_piano_finanziario
    python -m actions.genera_piano_finanziario --anno 2026 --output piano_finanziario_2026.xlsx
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

try:
    from google.cloud import bigquery  # noqa: F401 — presence check
except ImportError:
    print("google-cloud-bigquery non installato")
    sys.exit(1)

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from core.bq.client import get_client
from core.config import (
    D_VOCI_PIANO_FINANZIARIO,
    F_BANCHE_MOVIMENTI,
    V_PIANO_FINANZIARIO_CONSUNTIVO,
    V_PIANO_FINANZIARIO_MENSILE,
)

MESI = [
    "Gen",
    "Feb",
    "Mar",
    "Apr",
    "Mag",
    "Giu",
    "Lug",
    "Ago",
    "Set",
    "Ott",
    "Nov",
    "Dic",
]

# Styles
FONT_HEADER = Font(name="Arial", bold=True, size=11)
FONT_SECTION = Font(name="Arial", bold=True, size=12, color="333333")
FONT_CONSUNTIVO = Font(name="Arial", size=10, color="000000")
FONT_PREVISIONE = Font(name="Arial", size=10, color="0000FF")
FONT_FORMULA = Font(name="Arial", size=10, color="008000")
FONT_TOTALE = Font(name="Arial", bold=True, size=10)
FILL_HEADER = PatternFill("solid", fgColor="D9E1F2")
FILL_ENTRATE = PatternFill("solid", fgColor="E2EFDA")
FILL_USCITE = PatternFill("solid", fgColor="FCE4D6")
FILL_TOTALE = PatternFill("solid", fgColor="DDDDDD")
FILL_INPUT = PatternFill("solid", fgColor="FFFF00")
FILL_CONSUNTIVO = PatternFill("solid", fgColor="E8F5E9")
EUR_FMT = '#,##0;(#,##0);"-"'
PCT_FMT = "0.0%"
THIN_BORDER = Border(
    bottom=Side(style="thin", color="AAAAAA"),
)


def query_bq(sql: str) -> list[dict]:
    client = get_client()
    return [dict(r) for r in client.query(sql).result()]


def fetch_pf_data(anno: int) -> list[dict]:
    """Fetch piano finanziario mensile for both società."""
    return query_bq(f"""
    SELECT societa_id, voce_id, voce_label, sezione, categoria, ord, mese,
      tipo_periodo, importo_consuntivo, importo_budget, scostamento, scostamento_pct
    FROM `{V_PIANO_FINANZIARIO_MENSILE}`
    WHERE anno = {anno}
      AND (importo_consuntivo != 0 OR importo_budget != 0)
    ORDER BY societa_id, ord, mese
    """)


def fetch_stagionalita(anno_prev: int) -> list[dict]:
    """Fetch monthly actuals from previous year for seasonality."""
    return query_bq(f"""
    SELECT societa_id, voce_id, voce_label, sezione, mese,
      ROUND(importo, 2) AS importo
    FROM `{V_PIANO_FINANZIARIO_CONSUNTIVO}`
    WHERE anno = {anno_prev}
    ORDER BY societa_id, voce_id, mese
    """)


def fetch_voci() -> list[dict]:
    """Fetch all voci ordered."""
    return query_bq(f"""
    SELECT voce_id, voce_label, sezione, categoria, ord, societa_id
    FROM `{D_VOCI_PIANO_FINANZIARIO}`
    ORDER BY ord
    """)


def fetch_saldo_banca(societa: str) -> tuple[float, dict]:
    """Fetch current bank balance per banca + total for a società.
    Returns (totale, {banca_id: saldo})."""
    rows = query_bq(f"""
    SELECT banca_id,
      ROUND(SUM(importo_netto), 2) AS saldo
    FROM `{F_BANCHE_MOVIMENTI}`
    WHERE societa_id = '{societa}'
    GROUP BY 1
    ORDER BY 1
    """)
    per_banca = {r["banca_id"]: r["saldo"] for r in rows}
    totale = sum(per_banca.values())
    return totale, per_banca


def build_pf_sheet(
    wb: Workbook,
    sheet_name: str,
    societa: str,
    anno: int,
    voci: list[dict],
    pf_data: list[dict],
    stag_data: list[dict],
    saldo_iniziale: float = 0,
    saldi_banca: dict | None = None,
):
    """Build one PF sheet for a società."""
    ws = wb.create_sheet(sheet_name)
    mese_corrente = date.today().month

    # Index data by (voce_id, mese)
    pf = {}
    for r in pf_data:
        if r["societa_id"] == societa:
            pf[(r["voce_id"], r["mese"])] = r

    stag = {}
    for r in stag_data:
        if r["societa_id"] == societa:
            stag[(r["voce_id"], r["mese"])] = r.get("importo", 0)

    # Filter voci for this società
    soc_voci = [
        v for v in voci if v["societa_id"] is None or v["societa_id"] == societa
    ]

    # Header
    ws.merge_cells("A1:N1")
    ws["A1"] = f"Piano Finanziario {societa} — {anno}"
    ws["A1"].font = Font(name="Arial", bold=True, size=14)

    ws["A2"] = "Generato da BigQuery"
    ws["A2"].font = Font(name="Arial", italic=True, size=9, color="888888")
    ws["A3"] = "Nero = consuntivo | Blu = previsione (modificabile) | Verde = formula"
    ws["A3"].font = Font(name="Arial", size=9, color="666666")

    # Column headers: A=Voce, B=Categoria, C-N=Gen-Dic, O=Totale, P=2025
    row = 5
    headers = ["Voce", "Cat."] + MESI + ["TOTALE", f"{anno - 1}"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row, col, h)
        cell.font = FONT_HEADER
        cell.fill = FILL_HEADER
        cell.alignment = Alignment(horizontal="center")

    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 12
    for col in range(3, 17):
        ws.column_dimensions[get_column_letter(col)].width = 13

    # Data rows
    row = 6
    current_sezione = None

    for v in soc_voci:
        vid = v["voce_id"]
        sezione = v["sezione"]

        # Section header
        if sezione != current_sezione:
            current_sezione = sezione
            if row > 6:
                row += 1
            ws.cell(row, 1, f"══ {sezione} ══").font = FONT_SECTION
            fill = FILL_ENTRATE if sezione == "ENTRATE" else FILL_USCITE
            for col in range(1, 17):
                ws.cell(row, col).fill = fill
            row += 1

        # Voce label + categoria
        ws.cell(row, 1, v["voce_label"]).font = Font(name="Arial", size=10)
        ws.cell(row, 2, v.get("categoria", "")).font = Font(
            name="Arial", size=9, color="888888"
        )

        # Monthly values
        for mese in range(1, 13):
            col = mese + 2  # C=Gen(1), D=Feb(2), ...
            data = pf.get((vid, mese))

            if data:
                consuntivo = data.get("importo_consuntivo", 0) or 0
                budget = data.get("importo_budget", 0) or 0
                tipo = data.get("tipo_periodo", "BUDGET")

                if tipo == "CONSUNTIVO" and consuntivo != 0:
                    cell = ws.cell(row, col, round(consuntivo))
                    cell.font = FONT_CONSUNTIVO
                    if mese < mese_corrente:
                        cell.fill = FILL_CONSUNTIVO
                elif budget != 0:
                    cell = ws.cell(row, col, round(budget))
                    cell.font = FONT_PREVISIONE
                    cell.fill = FILL_INPUT
                elif consuntivo != 0:
                    cell = ws.cell(row, col, round(consuntivo))
                    cell.font = FONT_CONSUNTIVO
            else:
                ws.cell(row, col, 0).font = FONT_PREVISIONE

            ws.cell(row, col).number_format = EUR_FMT

        # Total formula (col O = 15)
        first = get_column_letter(3)
        last = get_column_letter(14)
        ws.cell(row, 15, f"=SUM({first}{row}:{last}{row})").font = FONT_FORMULA
        ws.cell(row, 15).number_format = EUR_FMT

        # Previous year (col P = 16)
        anno_prev_total = sum(stag.get((vid, m), 0) for m in range(1, 13))
        if anno_prev_total:
            ws.cell(row, 16, round(anno_prev_total)).font = Font(
                name="Arial", size=9, color="888888"
            )
            ws.cell(row, 16).number_format = EUR_FMT

        ws.cell(row, 1).border = THIN_BORDER
        row += 1

    # Totals section
    row += 1
    for col in range(1, 17):
        ws.cell(row, col).fill = FILL_TOTALE

    # Find row ranges for ENTRATE and USCITE
    entrate_rows = []
    uscite_rows = []
    current = None
    section_start = 6
    for r in range(6, row):
        val = ws.cell(r, 1).value
        if val and "══ ENTRATE ══" in str(val):
            section_start = r + 1
            current = "E"
        elif val and "══ USCITE ══" in str(val):
            if current == "E":
                entrate_rows = list(range(section_start, r))
            section_start = r + 1
            current = "U"
    if current == "U":
        uscite_rows = list(range(section_start, row))

    # TOTALE ENTRATE
    ws.cell(row, 1, "TOTALE ENTRATE").font = FONT_TOTALE
    ws.cell(row, 1).fill = FILL_ENTRATE
    for col in range(3, 16):
        cl = get_column_letter(col)
        if entrate_rows:
            parts = "+".join(f"{cl}{r}" for r in entrate_rows)
            ws.cell(row, col, f"={parts}").font = FONT_FORMULA
        ws.cell(row, col).number_format = EUR_FMT
        ws.cell(row, col).fill = FILL_ENTRATE
    tot_e_row = row

    row += 1
    ws.cell(row, 1, "TOTALE USCITE").font = FONT_TOTALE
    ws.cell(row, 1).fill = FILL_USCITE
    for col in range(3, 16):
        cl = get_column_letter(col)
        if uscite_rows:
            parts = "+".join(f"{cl}{r}" for r in uscite_rows)
            ws.cell(row, col, f"={parts}").font = FONT_FORMULA
        ws.cell(row, col).number_format = EUR_FMT
        ws.cell(row, col).fill = FILL_USCITE
    tot_u_row = row

    row += 1
    ws.cell(row, 1, "CASH FLOW NETTO").font = Font(name="Arial", bold=True, size=11)
    ws.cell(row, 1).fill = FILL_TOTALE
    for col in range(3, 16):
        cl = get_column_letter(col)
        ws.cell(row, col, f"={cl}{tot_e_row}-{cl}{tot_u_row}").font = Font(
            name="Arial", bold=True, size=10, color="008000"
        )
        ws.cell(row, col).number_format = EUR_FMT
        ws.cell(row, col).fill = FILL_TOTALE

    # Saldo banca reale (prima del cumulativo)
    row += 1
    if saldo_iniziale and saldi_banca:
        ws.cell(row, 1, "SALDO BANCA INIZIALE").font = Font(
            name="Arial", bold=True, size=10, color="8B0000"
        )
        ws.cell(row, 1).fill = PatternFill("solid", fgColor="FFF2CC")
        banca_note = ", ".join(f"{b}: €{int(s):,}" for b, s in saldi_banca.items())
        ws.cell(row, 2, banca_note).font = Font(name="Arial", size=8, color="888888")
        # Saldo iniziale in colonna Gen (C)
        ws.cell(row, 3, round(saldo_iniziale)).font = Font(
            name="Arial", bold=True, size=10, color="8B0000"
        )
        ws.cell(row, 3).number_format = EUR_FMT
        ws.cell(row, 3).fill = PatternFill("solid", fgColor="FFF2CC")
    saldo_row = row

    # Saldo cumulativo
    row += 1
    ws.cell(row, 1, "SALDO CUMULATIVO").font = Font(name="Arial", bold=True, size=10)
    prev_cl = None
    for col in range(3, 16):
        cl = get_column_letter(col)
        if prev_cl is None:
            # First month: saldo iniziale + cash flow netto
            if saldo_iniziale:
                ws.cell(row, col, f"={cl}{saldo_row}+{cl}{row - 2}").font = FONT_FORMULA
            else:
                ws.cell(row, col, f"={cl}{row - 2}").font = FONT_FORMULA
        else:
            ws.cell(row, col, f"={prev_cl}{row}+{cl}{row - 2}").font = FONT_FORMULA
        ws.cell(row, col).number_format = EUR_FMT
        prev_cl = cl

    return ws


def main():
    parser = argparse.ArgumentParser(
        description="Genera Piano Finanziario Excel da BigQuery"
    )
    parser.add_argument("--anno", type=int, default=2026)
    parser.add_argument("--output", default=None, help="Output file path")
    args = parser.parse_args()

    anno = args.anno
    output = args.output or f"Piano_Finanziario_{anno}_{date.today().isoformat()}.xlsx"

    print("Fetching data from BigQuery...")

    voci = fetch_voci()
    print(f"  Voci: {len(voci)}")

    pf_data = fetch_pf_data(anno)
    print(f"  PF {anno}: {len(pf_data)} righe")

    stag_data = fetch_stagionalita(anno - 1)
    print(f"  Stagionalità {anno - 1}: {len(stag_data)} righe")

    wb = Workbook()
    wb.remove(wb.active)

    for societa in ["ORTI", "INTUR"]:
        print(f"  Building sheet PF {societa}...")
        saldo_tot, saldi_per_banca = fetch_saldo_banca(societa)
        print(f"  Saldo banca {societa}: €{saldo_tot:,.0f}")
        build_pf_sheet(
            wb,
            f"PF {societa}",
            societa,
            anno,
            voci,
            pf_data,
            stag_data,
            saldo_iniziale=saldo_tot,
            saldi_banca=saldi_per_banca,
        )

    wb.save(output)
    print(f"\n✓ {output} generato ({len(wb.sheetnames)} fogli)")
    print("  Nero = consuntivo reale | Blu su giallo = previsione da modificare")
    print("  Dopo la sessione con Rosa: usa 'hotelops previsione' per riscrivere in BQ")


if __name__ == "__main__":
    main()
