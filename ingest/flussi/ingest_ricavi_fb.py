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
