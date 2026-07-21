#!/usr/bin/env python3
"""
Camere dimension loader — idempotente (WRITE_TRUNCATE).

Carica il CSV d_camere → BigQuery d_camere.
Inventario fisico unità del gruppo (115: 86 HOTEL + 20 RESIDENCE + 9 CVM;
fonte: foglio "Distribuzione camere" + rooming list 2026-07-21 — dato
statico, seedato a mano).

Usage:
    python -m core.bq.load.load_camere
    python -m core.bq.load.load_camere --dry-run
"""

import argparse
import csv
import logging
import sys
from collections import Counter
from pathlib import Path

try:
    from google.cloud import bigquery

    HAS_BQ = True
except ImportError:
    HAS_BQ = False

from core.bq.client import get_client
from core.config import PROJECT
from core.schemas import CameraRow, validate_batch

BQ_TABLE = f"{PROJECT}.hotelops.d_camere"

DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "dimensioni" / "d_camere.csv"

BQ_SCHEMA = (
    [
        bigquery.SchemaField("room_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("piano", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("cod_camera", "STRING"),
        bigquery.SchemaField("tipologia", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("occupazione", "STRING"),
        bigquery.SchemaField("pax_max", "INTEGER"),
        bigquery.SchemaField("vista", "STRING"),
        bigquery.SchemaField("esposizione", "STRING"),
        bigquery.SchemaField("affaccio", "STRING"),
        bigquery.SchemaField("doccia_vasca", "STRING"),
        bigquery.SchemaField("letto_principale", "STRING"),
        bigquery.SchemaField("letto_secondario", "STRING"),
        bigquery.SchemaField("bagno_fa", "STRING"),
        bigquery.SchemaField("comunicante_con", "STRING"),
        bigquery.SchemaField("note", "STRING"),
        bigquery.SchemaField("business_unit_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("load_camere")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def parse_csv(filepath: Path, logger: logging.Logger) -> list[dict]:
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            room_id = row["room_id"].strip()
            if not room_id:
                continue
            rows.append(
                {
                    "room_id": room_id,
                    "piano": int(row["piano"]),
                    "cod_camera": row["cod_camera"].strip() or None,
                    "tipologia": row["tipologia"].strip(),
                    "occupazione": row["occupazione"].strip() or None,
                    "pax_max": int(row["pax_max"]) if row["pax_max"].strip() else None,
                    "vista": row["vista"].strip() or None,
                    "esposizione": row["esposizione"].strip() or None,
                    "affaccio": row["affaccio"].strip() or None,
                    "doccia_vasca": row["doccia_vasca"].strip() or None,
                    "letto_principale": row["letto_principale"].strip() or None,
                    "letto_secondario": row["letto_secondario"].strip() or None,
                    "bagno_fa": row["bagno_fa"].strip() or None,
                    "comunicante_con": row["comunicante_con"].strip() or None,
                    "note": row["note"].strip() or None,
                    "business_unit_id": row["business_unit_id"].strip(),
                    "societa_id": row["societa_id"].strip(),
                }
            )

    logger.info(f"Camere parsate: {len(rows)}")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Load d_camere → BigQuery")
    parser.add_argument(
        "--file",
        default=str(DEFAULT_SOURCE),
        help=f"Path al CSV (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no write")
    args = parser.parse_args()

    logger = setup_logger()
    filepath = Path(args.file)
    if not filepath.exists():
        logger.error(f"File non trovato: {filepath}")
        sys.exit(1)

    rows = parse_csv(filepath, logger)

    dup = [r for r, n in Counter(r["room_id"] for r in rows).items() if n > 1]
    if dup:
        logger.error(f"room_id duplicati: {dup}")
        sys.exit(1)

    validate_batch(rows, CameraRow, context="d_camere")
    logger.info("Schema validation OK")

    pax_tot = sum(r["pax_max"] or 0 for r in rows)
    logger.info(f"  pax totali: {pax_tot}")
    for tip, n in sorted(Counter(r["tipologia"] for r in rows).items()):
        logger.info(f"  {tip:<15} {n}")

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    bq_client = get_client()

    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    job = bq_client.load_table_from_json(rows, BQ_TABLE, job_config=job_config)
    job.result()

    if job.errors:
        logger.error(f"BQ load errors: {job.errors}")
        sys.exit(1)

    logger.info(f"d_camere caricato: {len(rows)} righe → {BQ_TABLE}")
    logger.info("DONE")


if __name__ == "__main__":
    main()
