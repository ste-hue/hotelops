#!/usr/bin/env python3
"""Ingest HotelCube Power BI "Produzione Netta Dashboard" → f_ricavi_fb.

One xlsx file = one struttura × one mese. Period metadata (CodiceHotel, Anno,
Mese) lives in the file's last "Applied filters" cell, not in the data rows.

Lifecycle: SNAPSHOT, natural_key (business_unit_id, anno, mese). Re-loading a
month replaces that structure-month's rows.

È il parser_module della source POWERBI_RICAVIFB_ORTI_SNAPSHOT, invocato da
`hotelops promote` come: python -m ingest.flussi.ingest_ricavi_fb --file X --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_ricavi_fb --file <xlsx> --raw-object-id <id>
    python -m ingest.flussi.ingest_ricavi_fb --file <xlsx> --dry-run
"""
from __future__ import annotations

import argparse
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path

from openpyxl import load_workbook

from core.config import F_RICAVI_FB
from core.schemas import RicaviFbRow, make_hash, validate_batch

log = logging.getLogger("ingest.ricavi_fb")

# Switch operativo HotelCube INTUR → ORTI (vedi 2026-04-29-produzione-pms spec).
OPERATIONS_CUTOVER_DATE = date(2025, 4, 1)

HOTEL_TO_BU = {
    "PANORAMAHT": "HOTEL",
    "ANGELINARES": "RESIDENCE",
    "HOMEHOLIDAY": "CVM",
}
MESE_IT = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}


def parse_applied_filters(text: str) -> tuple[str, int, int]:
    """Extract (business_unit_id, anno, mese) from the 'Applied filters' cell.

    Raises ValueError if any of the three tokens is missing or unrecognized.
    """
    hotel_m = re.search(r"CodiceHotel is (\w+)", text)
    anno_m = re.search(r"Anno is (\d+)", text)
    mese_m = re.search(r"Mese is (\w+)", text)
    if not (hotel_m and anno_m and mese_m):
        raise ValueError(f"Applied filters incompleti: {text[:120]!r}")
    codice_hotel = hotel_m.group(1)
    if codice_hotel not in HOTEL_TO_BU:
        raise ValueError(f"CodiceHotel sconosciuto: {codice_hotel}")
    mese_nome = mese_m.group(1).lower()
    if mese_nome not in MESE_IT:
        raise ValueError(f"Mese sconosciuto: {mese_nome}")
    return HOTEL_TO_BU[codice_hotel], int(anno_m.group(1)), MESE_IT[mese_nome]


def parse_xlsx(path: Path) -> tuple[tuple[str, int, int], list[dict]]:
    """Read a Produzione Netta xlsx → (period, data_rows).

    period = (business_unit_id, anno, mese) from the last 'Applied filters' cell.
    data_rows = list of {codice, descrizione, netto, lordo}; the 'Total' row and
    blanks are skipped.

    Column layout (0-indexed): 0 Classe | 1 Codice | 2 Descrizione | 3 Netto |
    ... | 10 Lordo.
    """
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb["Export"] if "Export" in wb.sheetnames else wb.worksheets[0]
    rows = [r for r in ws.iter_rows(values_only=True) if any(c is not None for c in r)]
    wb.close()
    if len(rows) < 3:
        raise ValueError(f"{path.name}: troppe poche righe ({len(rows)})")

    period = parse_applied_filters(str(rows[-1][0] or ""))

    data_rows: list[dict] = []
    for r in rows[1:-1]:  # skip header (rows[0]) and filter cell (rows[-1])
        codice = r[1] if len(r) > 1 else None
        netto = r[3] if len(r) > 3 else None
        if not codice or not isinstance(netto, (int, float)):
            continue  # 'Total' row (codice None) and blanks
        lordo = r[10] if len(r) > 10 else None
        data_rows.append({
            "codice": str(codice).strip(),
            "descrizione": (str(r[2]).strip() if len(r) > 2 and r[2] else None),
            "netto": float(netto),
            "lordo": float(lordo) if isinstance(lordo, (int, float)) else 0.0,
        })
    return period, data_rows


def _societa_for(anno: int, mese: int) -> str:
    """ORTI post-cutover, INTUR before. All 24 current files are ORTI."""
    return "INTUR" if date(anno, mese, 1) < OPERATIONS_CUTOVER_DATE else "ORTI"


def build_rows(
    period: tuple[str, int, int],
    raw_rows: list[dict],
    file_name: str,
    raw_object_id: str | None = None,
) -> list[dict]:
    """Turn parsed raw rows into f_ricavi_fb dict rows.

    Adds societa_id (cutover-derived), hash_riga (md5 of the natural key plus
    codice), raw_object_id (lineage FK — stamped by the `promote` path, None
    when run standalone), and data_caricamento.
    """
    bu, anno, mese = period
    societa = _societa_for(anno, mese)
    now = datetime.now(timezone.utc)
    out: list[dict] = []
    for r in raw_rows:
        codice = r["codice"]
        out.append({
            "societa_id": societa,
            "business_unit_id": bu,
            "anno": anno,
            "mese": mese,
            "codice": codice,
            "descrizione": r.get("descrizione"),
            "netto": r["netto"],
            "lordo": r["lordo"],
            "file_sorgente": file_name,
            "hash_riga": make_hash(bu, str(anno), str(mese), codice),
            "raw_object_id": raw_object_id,
            "data_caricamento": now,
        })
    return out
