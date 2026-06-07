#!/usr/bin/env python3
"""Ingest HotelCube Power BI Daily Production Report (classe cut) → f_produzione_pms.

One xlsx = one struttura × one anno. Period metadata (CodiceHotel, Anno,
Descrizione) lives in the file's last "Applied filters" cell. Data rows are daily;
columns are revenue classes (01ROOM, 02FB, ...). Unpivot wide→long.

Lifecycle: SNAPSHOT, natural_key (business_unit_id, anno). Re-loading a
struttura×anno replaces those rows.

Parser_module della source POWERBI_PRODUZIONE_ORTI_SNAPSHOT, invocato da
`hotelops promote` come: python -m ingest.flussi.ingest_produzione_pms --file X --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_produzione_pms --file <xlsx> --raw-object-id <id>
    python -m ingest.flussi.ingest_produzione_pms --file <xlsx> --dry-run
"""
from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from core.config import F_PRODUZIONE_PMS
from core.schemas import (
    OPERATIONS_CUTOVER_DATE,
    ProduzioneRow,
    make_hash,
    validate_batch,
)

log = logging.getLogger("ingest.produzione_pms")

HOTEL_TO_BU = {
    "PANORAMAHT": "HOTEL",
    "ANGELINARES": "RESIDENCE",
    "HOMEHOLIDAY": "CVM",
}
CLASSE_RE = re.compile(r"^\d{2}[A-Z]+$")


def parse_applied_filters(text: str) -> tuple[str, int]:
    """Extract (business_unit_id, anno) from the 'Applied filters' cell.

    Requires Descrizione is Imponibile. Raises ValueError otherwise.
    """
    if not re.search(r"Descrizione is Imponibile", text):
        raise ValueError(
            f"file non Imponibile (atteso 'Descrizione is Imponibile'): {text[:120]!r}"
        )
    hotel_m = re.search(r"CodiceHotel is (\w+)", text)
    anno_m = re.search(r"Anno is (\d+)", text)
    if not (hotel_m and anno_m):
        raise ValueError(f"Applied filters incompleti: {text[:120]!r}")
    codice = hotel_m.group(1)
    if codice not in HOTEL_TO_BU:
        raise ValueError(f"CodiceHotel sconosciuto: {codice}")
    return HOTEL_TO_BU[codice], int(anno_m.group(1))


def detect_classe_columns(header: tuple) -> dict[int, str]:
    """Map column index → classe code for cells matching ^\\d{2}[A-Z]+$.

    Skips 'Total', 'Classe', blanks. Works regardless of leading blank cols.
    """
    out: dict[int, str] = {}
    for idx, cell in enumerate(header):
        if cell is None:
            continue
        name = str(cell).strip()
        if CLASSE_RE.match(name):
            out[idx] = name
    return out
