#!/usr/bin/env python3
"""Ingest dump JSON completo Spiagge.it → 3 tabelle canonical (fan-out 1→3).

Un dump = il DB intero di booking. Lifecycle SNAPSHOT full-replace: ogni dump
sostituisce integralmente le 3 tabelle. Il full-replace è ottenuto con
bq_write_validated(mode="snapshot", natural_key=["societa_id"]): siccome ogni
riga è societa_id='INTUR', il DELETE chirurgico del gate svuota la tabella prima
del re-insert.

È il parser_module della source SPIAGGEIT_SPIAGGIA_INTUR_SNAPSHOT, invocato da
`hotelops promote` come:
    python -m ingest.flussi.ingest_spiaggia --file X.json --raw-object-id Y

Usage:
    python -m ingest.flussi.ingest_spiaggia --file <json> --raw-object-id <id>
    python -m ingest.flussi.ingest_spiaggia --file <json> --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from core.config import (
    F_SPIAGGIA_CASH_FLOWS,
    F_SPIAGGIA_RESERVATIONS,
    F_SPIAGGIA_SPOTS,
)
from core.schemas import (
    SpiaggiaCashFlowRow,
    SpiaggiaReservationRow,
    SpiaggiaSpotRow,
    make_hash,
    validate_batch,
)

log = logging.getLogger("ingest.spiaggia")

# Dimensioni fisse del vertical (vedi spec): la spiaggia è INTUR / LIDO.
SOCIETA = "INTUR"
BUSINESS_UNIT = "LIDO"
LOCATION = "LIDO"

# Legenda metodi pagamento Spiagge.it: IGNOTA. Riempire qui quando nota
# (es. {1: "contanti", 14: "POS"}) e ri-promuovere il dump. Finché vuota,
# method_label resta "metodo_<codice>".
METHOD_LABELS: dict[int, str] = {}


def to_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def to_float(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_bool(v: Any) -> bool:
    """0/1/None → bool. None e falsy → False."""
    return bool(v) if v is not None else False


def to_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def unix_to_date(v: Any) -> Optional[date]:
    """Unix seconds → date UTC. 0/None/falsy → None (filtra epoch-junk 1970)."""
    n = to_int(v)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def unix_to_ts(v: Any) -> Optional[datetime]:
    """Unix seconds → datetime UTC. 0/None/falsy → None."""
    n = to_int(v)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def method_label(code: Optional[int]) -> str:
    if code is None:
        return "sconosciuto"
    return METHOD_LABELS.get(code, f"metodo_{code}")


def find_prefix(dump: dict) -> str:
    """Deduce il prefisso tabella dal dump (es. 'it-sa-84010-panorama-beach_').

    Cerca la chiave che termina in '_reservations'. Robusto a license_code
    diversi (altra spiaggia) senza hardcodare il nome.
    """
    suffix = "_reservations"
    for k in dump:
        if k.endswith(suffix):
            return k[: -len("reservations")]
    raise ValueError("dump senza tabella *_reservations: non è un dump Spiagge.it")


def extract_table(dump: dict, prefix: str, table: str) -> list[dict]:
    """Estrae una tabella {columns, rows} → list[dict] per nome colonna."""
    key = f"{prefix}{table}"
    block = dump.get(key)
    if block is None:
        raise KeyError(f"tabella mancante nel dump: {key}")
    cols = block["columns"]
    return [dict(zip(cols, row)) for row in block["rows"]]
