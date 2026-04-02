"""
Generate manifest.yaml — a metadata catalog of all BQ tables.

Each table gets: row count, freshness (date range), sources, and
per-column stats (type, distinct values or samples, min/max).

Usage:
    from core.bq.manifest import generate_manifest
    manifest = generate_manifest()  # returns dict
    generate_manifest(output_path="core/bq/manifest.yaml")  # writes file
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import yaml

from core.config import PROJECT, DATASET

log = logging.getLogger(__name__)

# Tables to catalog (all facts + dimensions from config.py)
TABLES = [
    "f_banche_movimenti",
    "f_movimenti_contabili",
    "f_budget_mensile",
    "f_piano_finanziario_input",
    "f_consumi_economato",
    "f_coperti_giornalieri",
    "f_bilancino",
    "f_partite_aperte_fornitori",
    "f_saldi_banca_snapshot",
    "f_accodamenti",
    "f_ricavi_storici",
    "d_voci_piano_finanziario",
    "d_piano_conti",
    "d_categorie_conti",
    "d_fornitori",
    "d_anagrafica_fornitori",
    "d_mapping_piano_finanziario",
    "d_coefficienti_stagionalita",
]

# Columns likely to hold date/freshness info (checked in order)
DATE_CANDIDATES = [
    "data_registrazione",
    "data_operazione",
    "data_caricamento",
    "data_ingresso",
    "data_snapshot",
    "data_servizio",
    "data_documento",
]

# Columns likely to hold source file info
SOURCE_CANDIDATES = ["file_sorgente", "fonte"]

# Thresholds for value listing
VALUES_THRESHOLD = 30  # list all values if distinct <= this
SAMPLE_THRESHOLD = 100  # show top-N if distinct > VALUES_THRESHOLD
SAMPLE_SIZE = 10


def _column_stats(
    col_name: str,
    col_type: str,
    distinct: int,
    values: list | None,
    sample: list | None,
    min_val,
    max_val,
) -> dict:
    """Build stats dict for a single column."""
    stats: dict = {"type": col_type}

    if col_type in ("FLOAT", "INTEGER", "NUMERIC"):
        if min_val is not None:
            stats["min"] = min_val
        if max_val is not None:
            stats["max"] = max_val
        if distinct is not None:
            stats["distinct"] = distinct
        return stats

    if col_type in ("DATE", "TIMESTAMP", "DATETIME"):
        if min_val is not None:
            stats["min"] = str(min_val) if not isinstance(min_val, str) else min_val
        if max_val is not None:
            stats["max"] = str(max_val) if not isinstance(max_val, str) else max_val
        if distinct is not None:
            stats["distinct"] = distinct
        return stats

    # STRING columns
    if distinct is not None:
        stats["distinct"] = distinct
    if distinct is not None and distinct <= VALUES_THRESHOLD and values:
        stats["values"] = values
    elif sample:
        stats["sample"] = sample

    return stats
