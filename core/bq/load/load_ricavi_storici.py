#!/usr/bin/env python3
"""
Ingest historical revenue per BU per month (2023-2025).

Source: "Riepilogo Entrate" XLSX from Antonio — one sheet "Dettaglio per Struttura"
with 3 blocks (ANGELINARES, HOMEHOLIDAY, PANORAMAHT) × 12 months × 3 years.

Usage:
    python -m core.bq.load.load_ricavi_storici --file path/to/Riepilogo_Entrate_2023_2024_2025.xlsx
    python -m core.bq.load.load_ricavi_storici --file path/to/file.xlsx --dry-run

Output BQ: f_ricavi_storici  (WRITE_APPEND + dedup via hash_riga)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

try:
    from google.cloud import bigquery
    HAS_BQ = True
except ImportError:
    HAS_BQ = False

from core.schemas import RicaviStoriciRow, make_hash, validate_batch

BQ_PROJECT = "hotelops-suite"
BQ_DATASET = "hotelops"
BQ_TABLE = "f_ricavi_storici"
BQ_TABLE_FULL = f"{BQ_PROJECT}.{BQ_DATASET}.{BQ_TABLE}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# Structure name in XLSX → canonical business_unit_id
STRUTTURA_MAP = {
    "ANGELINARES": "RESIDENCE",
    "HOMEHOLIDAY": "CVM",
    "PANORAMAHT": "HOTEL",
}

MESI_IT = {
    "Gennaio": 1, "Febbraio": 2, "Marzo": 3, "Aprile": 4,
    "Maggio": 5, "Giugno": 6, "Luglio": 7, "Agosto": 8,
    "Settembre": 9, "Ottobre": 10, "Novembre": 11, "Dicembre": 12,
}


def parse_xlsx(path: Path, societa_id: str) -> list[dict]:
    """Parse Riepilogo Entrate XLSX → list of row dicts."""
    if not HAS_OPENPYXL:
        log.error("openpyxl not installed")
        sys.exit(1)

    wb = openpyxl.load_workbook(str(path), data_only=True)
    ws = wb["Dettaglio per Struttura"]
    ts_now = datetime.now(timezone.utc).isoformat()
    fonte = path.name
    rows: list[dict] = []

    # Read all rows as lists
    all_rows = list(ws.iter_rows(values_only=True))

    current_bu = None
    year_cols: list[int] = []  # which years are in cols 1,2,3

    for raw in all_rows:
        if not raw or not any(raw):
            continue

        first = str(raw[0]).strip() if raw[0] is not None else ""

        # Detect structure header (e.g. "ANGELINARES")
        if first in STRUTTURA_MAP:
            current_bu = STRUTTURA_MAP[first]
            continue

        # Reset BU on unrecognized block headers (e.g. "TOTALE GENERALE")
        if first.startswith("TOTALE GENERALE"):
            current_bu = None
            continue

        # Detect year header row: "Mese", 2023, 2024, 2025, ...
        if first == "Mese":
            year_cols = []
            for i in range(1, min(4, len(raw))):
                try:
                    year_cols.append(int(raw[i]))
                except (TypeError, ValueError):
                    pass
            continue

        # Skip totals and non-month rows
        if first.startswith("TOTALE") or first.startswith("Riepilogo"):
            continue

        # Parse month row
        mese_num = MESI_IT.get(first)
        if mese_num is None or current_bu is None or not year_cols:
            continue

        for col_idx, anno in enumerate(year_cols):
            val = raw[col_idx + 1]  # +1 because col 0 is "Mese"
            try:
                importo = float(val) if val is not None else 0.0
            except (TypeError, ValueError):
                importo = 0.0

            rows.append({
                "societa_id": societa_id,
                "business_unit_id": current_bu,
                "anno": anno,
                "mese": mese_num,
                "importo_entrate": round(importo, 2),
                "fonte": fonte,
                "hash_riga": make_hash(societa_id, current_bu, anno, mese_num),
                "data_caricamento": ts_now,
            })

    return rows


BQ_SCHEMA = [
    bigquery.SchemaField("societa_id",       "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("business_unit_id",  "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("anno",             "INT64",     mode="REQUIRED"),
    bigquery.SchemaField("mese",             "INT64",     mode="REQUIRED"),
    bigquery.SchemaField("importo_entrate",  "FLOAT64",   mode="REQUIRED"),
    bigquery.SchemaField("fonte",            "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("hash_riga",        "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("data_caricamento", "TIMESTAMP", mode="NULLABLE"),
] if HAS_BQ else []


def ensure_table(client):
    """Create table if not exists."""
    dataset_ref = bigquery.DatasetReference(BQ_PROJECT, BQ_DATASET)
    table_ref = dataset_ref.table(BQ_TABLE)
    try:
        client.get_table(table_ref)
    except Exception:
        table = bigquery.Table(table_ref, schema=BQ_SCHEMA)
        client.create_table(table)
        log.info("Table %s created.", BQ_TABLE_FULL)


def get_existing_hashes(client) -> set[str]:
    """Fetch existing hash_riga values."""
    try:
        q = f"SELECT hash_riga FROM `{BQ_TABLE_FULL}`"
        return {row.hash_riga for row in client.query(q).result()}
    except Exception:
        return set()


def load_to_bq(rows: list[dict], dry_run: bool) -> None:
    """APPEND mode: insert only new rows (by hash_riga)."""
    if not HAS_BQ:
        log.error("google-cloud-bigquery not installed")
        sys.exit(1)

    client = bigquery.Client(project=BQ_PROJECT)
    ensure_table(client)

    existing = get_existing_hashes(client)
    new_rows = [r for r in rows if r["hash_riga"] not in existing]

    log.info("Total rows: %d | already in BQ: %d | new: %d",
             len(rows), len(rows) - len(new_rows), len(new_rows))

    if not new_rows:
        log.info("Nothing to load.")
        return

    if dry_run:
        log.info("[DRY RUN] Would load %d rows.", len(new_rows))
        return

    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = client.load_table_from_json(new_rows, BQ_TABLE_FULL, job_config=job_config)
    job.result()
    log.info("Loaded: %d rows → %s", len(new_rows), BQ_TABLE_FULL)


def quality_summary(rows: list[dict]) -> None:
    """Print data quality stats."""
    from collections import defaultdict

    by_bu_year: dict[tuple, float] = defaultdict(float)
    for r in rows:
        by_bu_year[(r["business_unit_id"], r["anno"])] += r["importo_entrate"]

    print("\n── QUALITY SUMMARY ──────────────────────────────────────────")
    print(f"  Total rows: {len(rows)}")
    bus = sorted({k[0] for k in by_bu_year})
    years = sorted({k[1] for k in by_bu_year})
    print(f"  BU: {', '.join(bus)}")
    print(f"  Years: {', '.join(str(y) for y in years)}")
    print(f"\n  {'BU':<12s} " + "  ".join(f"{y:>12d}" for y in years))
    print("  " + "─" * (12 + 14 * len(years)))
    for bu in bus:
        vals = "  ".join(f"{by_bu_year.get((bu, y), 0):>12,.0f}" for y in years)
        print(f"  {bu:<12s} {vals}")
    totals = "  ".join(
        f"{sum(by_bu_year.get((bu, y), 0) for bu in bus):>12,.0f}" for y in years
    )
    print("  " + "─" * (12 + 14 * len(years)))
    print(f"  {'TOTALE':<12s} {totals}")
    print("─────────────────────────────────────────────────────────────\n")


def main():
    parser = argparse.ArgumentParser(
        description="Ingest Riepilogo Entrate storici → f_ricavi_storici"
    )
    parser.add_argument("--file", required=True, help="Path to Riepilogo Entrate XLSX")
    parser.add_argument("--societa", default="ORTI", help="societa_id (default: ORTI)")
    parser.add_argument("--dry-run", action="store_true", help="No BQ write")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        log.error("File not found: %s", path)
        sys.exit(1)

    log.info("Parsing: %s (societa=%s)", path.name, args.societa)
    rows = parse_xlsx(path, args.societa)

    if not rows:
        log.warning("No rows parsed.")
        sys.exit(0)

    validate_batch(rows, RicaviStoriciRow, context="ricavi_storici")
    quality_summary(rows)
    load_to_bq(rows, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
