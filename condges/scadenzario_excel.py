"""Scadenzario → PF Excel Bridge.

Reads the Esolver 'Situazione sintetica scadenze' export, maps suppliers
to Piano Finanziario voci via d_fornitori, and generates an annotated
Excel for Rosa to update her PF.
"""
from __future__ import annotations

import csv
import re
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill, numbers


def parse_sintetica_scadenze(filepath: Path) -> list[dict]:
    """Parse Esolver 'Situazione sintetica scadenze' Excel.

    Returns list of dicts:
        {codice_fornitore, nome, totale, scaduto, buckets: {month_int: amount}}
    """
    wb = openpyxl.load_workbook(str(filepath), data_only=True)
    ws = wb.active

    bucket_months = {}
    for col in range(4, ws.max_column + 1):
        header = ws.cell(row=1, column=col).value
        if not header or "scadenza" not in str(header).lower():
            continue
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(header))
        if m:
            bucket_months[col] = int(m.group(2))

    results = []
    for row_idx in range(2, ws.max_row + 1):
        cell_a = ws.cell(row=row_idx, column=1).value
        if not cell_a:
            continue
        cell_str = str(cell_a).strip()
        m = re.match(r"^(\d+)\s+(.+)$", cell_str)
        if not m:
            continue
        codice = int(m.group(1))
        nome = m.group(2).strip()
        totale = ws.cell(row=row_idx, column=2).value or 0
        scaduto = ws.cell(row=row_idx, column=3).value or 0
        buckets = {}
        for col, month in bucket_months.items():
            val = ws.cell(row=row_idx, column=col).value
            if val:
                buckets[month] = float(val)
        results.append({
            "codice_fornitore": codice,
            "nome": nome,
            "totale": float(totale),
            "scaduto": float(scaduto),
            "buckets": buckets,
        })
    return results


# ── Mapper ─────────────────────────────────────────────────────────────────

FORNITORI_CSV = Path(__file__).parent.parent / "core" / "bq" / "dimensioni" / "d_fornitori.csv"


def load_fornitori_map(csv_path: Path = FORNITORI_CSV) -> dict[int, str]:
    """Load d_fornitori CSV, return {codice_fornitore: voce_id}."""
    result = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[int(row["codice_fornitore"])] = row["voce_id"]
    return result


def map_to_voci(
    partite: list[dict], fornitori_map: dict[int, str]
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Map suppliers to PF voci.

    Returns:
        (mapped, unmapped) where mapped = {voce_id: [supplier_dicts]},
        unmapped = [supplier_dicts without voce match]
    """
    mapped: dict[str, list[dict]] = {}
    unmapped: list[dict] = []

    for p in partite:
        voce = fornitori_map.get(p["codice_fornitore"])
        if voce:
            mapped.setdefault(voce, []).append(p)
        else:
            unmapped.append(p)

    return mapped, unmapped
