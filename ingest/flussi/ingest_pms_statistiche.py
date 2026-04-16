#!/usr/bin/env python3
"""
PMS Dashboard Manager ingestion pipeline.

Reads HotelCube "Dashboard Manager" daily exports, extracts KPIs
from the 4 sheets (Produzione, AdrRevPar, Occupazione, Occupazione Risorse),
and writes daily rows to f_pms_statistiche in BigQuery.

BU detection: Camere Totali signature (86=HOTEL, 20=RESIDENCE, 10=CVM).

Usage:
    python -m ingest.flussi.ingest_pms_statistiche /path/to/files/*.xlsx
    python -m ingest.flussi.ingest_pms_statistiche /path/to/folder/
    python -m ingest.flussi.ingest_pms_statistiche --dry-run /path/to/files/
"""

import argparse
import hashlib
import logging
from datetime import datetime
from pathlib import Path

import openpyxl
import pandas as pd
from google.cloud import bigquery

from core.config import F_PMS_STATISTICHE
from core.schemas import PmsStatisticheRow, validate_batch

logger = logging.getLogger("ingest_pms_statistiche")

# BU detection by Camere Totali value
CAMERE_TOTALI_MAP = {
    86: "HOTEL",
    20: "RESIDENCE",
    10: "CVM",
    7: "CVM",       # CVM sometimes shows 7
}


def md5(*args) -> str:
    return hashlib.md5("|".join(str(a) for a in args).encode()).hexdigest()


def parse_date_header(val) -> str:
    """Parse date from header cell like '03/04/26' or '11/04/26'."""
    s = str(val).strip()
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {val}")


def parse_num(val) -> float:
    """Parse numeric value, handling Italian format (comma as decimal)."""
    if val is None or val == "" or val == 0:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def extract_from_file(filepath: Path) -> dict | None:
    """Extract one daily KPI row from a Dashboard Manager xlsx."""
    wb = openpyxl.load_workbook(filepath, data_only=True)

    # --- Date (from Produzione or AdrRevPar header) ---
    ws_prod = wb["Produzione"]
    header_row = list(ws_prod.iter_rows(min_row=1, max_row=1, values_only=True))[0]
    data = parse_date_header(header_row[4])

    # --- Occupazione ---
    ws_occ = wb["Occupazione"]
    occ = {}
    for row in ws_occ.iter_rows(values_only=True):
        label = str(row[0]).strip() if row[0] else ""
        if label:
            occ[label] = row[1]  # "oggi" column

    camere_totali = int(occ.get("Camere Totali", 0))
    camere_vendute = int(occ.get("Camere Vendute", 0))
    camere_bloccate = int(occ.get("Camere Bloccate", 0))
    pax_in_casa = int(occ.get("Pax In Casa", 0))

    # Occupazione % — parse Italian comma format
    occ_pct_raw = occ.get("% Occupazione", 0)
    if isinstance(occ_pct_raw, str):
        occ_pct = parse_num(occ_pct_raw)
    else:
        occ_pct = float(occ_pct_raw) if occ_pct_raw else 0.0

    # --- BU detection ---
    bu = CAMERE_TOTALI_MAP.get(camere_totali)
    if bu is None:
        logger.warning(f"  Unknown BU for Camere Totali={camere_totali} in {filepath.name}, skipping")
        return None

    # --- AdrRevPar ---
    ws_adr = wb["AdrRevPar"]
    adr_data = {}
    for row in ws_adr.iter_rows(values_only=True):
        label = str(row[0]).strip() if row[0] else ""
        if label:
            adr_data[label] = row[1]

    revenue_room = parse_num(adr_data.get("Room", 0))
    adr = parse_num(adr_data.get("ADR", 0))
    revpar = parse_num(adr_data.get("RevPAR", 0))

    # --- Produzione (revenue by class) ---
    revenue_fb = 0.0
    revenue_parking = 0.0
    revenue_other = 0.0
    current_class = ""

    for row in ws_prod.iter_rows(min_row=2, values_only=True):
        classe = str(row[0]).strip() if row[0] else ""
        if classe:
            current_class = classe
        today_val = parse_num(row[4]) if row[4] is not None else 0.0
        if current_class == "02FB":
            revenue_fb += today_val
        elif current_class == "03PARK":
            revenue_parking += today_val
        elif current_class not in ("01ROOM", ""):
            revenue_other += today_val

    revenue_totale = revenue_room + revenue_fb + revenue_parking + revenue_other

    return {
        "societa_id": "ORTI",
        "business_unit_id": bu,
        "data": data,
        "camere_totali": camere_totali,
        "camere_vendute": camere_vendute,
        "camere_bloccate": camere_bloccate,
        "occupazione_pct": occ_pct,
        "pax_in_casa": pax_in_casa,
        "adr": round(adr, 2),
        "revpar": round(revpar, 2),
        "revenue_room": round(revenue_room, 2),
        "revenue_fb": round(revenue_fb, 2),
        "revenue_parking": round(revenue_parking, 2),
        "revenue_totale": round(revenue_totale, 2),
        "fonte": "DASHBOARD_MANAGER",
        "hash_riga": md5("ORTI", bu, data),
        "data_caricamento": datetime.now().strftime("%Y-%m-%d"),
    }


def load_hashes(bq_client: bigquery.Client) -> set:
    try:
        result = bq_client.query(
            f"SELECT hash_riga FROM `{F_PMS_STATISTICHE}` WHERE hash_riga IS NOT NULL"
        ).result()
        return {row.hash_riga for row in result}
    except Exception:
        return set()


def main():
    parser = argparse.ArgumentParser(description="PMS Dashboard Manager ingestion")
    parser.add_argument("paths", nargs="+", help="Files or folders to ingest")
    parser.add_argument("--dry-run", "-d", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    # Collect files
    files = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(path.glob("*.xlsx")))
        elif path.suffix == ".xlsx":
            files.append(path)
    logger.info(f"Files to process: {len(files)}")

    # Extract rows
    rows = []
    for f in files:
        try:
            row = extract_from_file(f)
            if row:
                logger.info(f"  {f.name} -> {row['business_unit_id']} {row['data']} occ={row['occupazione_pct']}% rev=€{row['revenue_totale']:,.0f}")
                rows.append(row)
        except Exception as e:
            logger.error(f"  {f.name}: {e}")

    if not rows:
        logger.warning("No rows extracted")
        return

    # Dedup
    bq_client = bigquery.Client(project="hotelops-suite")
    hashes = load_hashes(bq_client)
    new_rows = [r for r in rows if r["hash_riga"] not in hashes]
    dupes = len(rows) - len(new_rows)
    logger.info(f"Total: {len(rows)}, New: {len(new_rows)}, Dupes: {dupes}")

    if args.dry_run:
        logger.info("DRY RUN — no writes")
        return

    if not new_rows:
        logger.info("Nothing to write")
        return

    # Validate and write
    validate_batch(new_rows, PmsStatisticheRow, "f_pms_statistiche")
    df = pd.DataFrame(new_rows)
    df["data"] = pd.to_datetime(df["data"])
    df["data_caricamento"] = pd.to_datetime(df["data_caricamento"])
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    bq_client.load_table_from_dataframe(df, F_PMS_STATISTICHE, job_config=job_config).result()
    logger.info(f"Wrote {len(new_rows)} rows to BigQuery")


if __name__ == "__main__":
    main()
