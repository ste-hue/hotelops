#!/usr/bin/env python3
"""
PMS codici dimension loader — idempotente (WRITE_TRUNCATE).

Carica il CSV d_pms_codici → BigQuery d_pms_codici.
Decodifiche HotelCube/Power BI (legende prenotazioni): 7 domini in una tabella
(TRATTAMENTO, CANALE, NAZIONE, SEGMENTO, TIPO_DITTA, ROOM_TYPE, CLASSE_TARIFFA).

Usage:
    python -m core.bq.load.load_pms_codici
    python -m core.bq.load.load_pms_codici --dry-run
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
from core.schemas import PmsCodiceRow, validate_batch

BQ_TABLE = f"{PROJECT}.hotelops.d_pms_codici"

DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "dimensioni" / "d_pms_codici.csv"

BQ_SCHEMA = (
    [
        bigquery.SchemaField("dominio", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("codice", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("descrizione", "STRING"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("load_pms_codici")
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
            codice = row["codice"].strip()
            if not codice:
                continue
            rows.append(
                {
                    "dominio": row["dominio"].strip(),
                    "codice": codice,
                    "descrizione": row["descrizione"].strip(),
                }
            )

    logger.info(f"Codici parsati: {len(rows)}")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Load d_pms_codici → BigQuery")
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

    dup = [
        k
        for k, n in Counter((r["dominio"], r["codice"]) for r in rows).items()
        if n > 1
    ]
    if dup:
        logger.error(f"(dominio, codice) duplicati: {dup}")
        sys.exit(1)

    validate_batch(rows, PmsCodiceRow, context="d_pms_codici")
    logger.info("Schema validation OK")

    for dom, n in sorted(Counter(r["dominio"] for r in rows).items()):
        logger.info(f"  {dom:<15} {n}")

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

    logger.info(f"d_pms_codici caricato: {len(rows)} righe → {BQ_TABLE}")
    logger.info("DONE")


if __name__ == "__main__":
    main()
