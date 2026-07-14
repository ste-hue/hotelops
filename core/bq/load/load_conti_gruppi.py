#!/usr/bin/env python3
"""
Conti gruppo loader — d_conti_gruppi (codice_conto, descrizione).

`f_bilancino` porta solo conti FOGLIA; le descrizioni dei codici GRUPPO
(es. 55, 55.07) stanno solo nelle righe non-foglia dei bilancini esolver
esportati (colonna Descrizione), non in d_piano_conti. Questa dimensione
copre quel buco per l'artifact Bilancini (Navigatore/Progressione).

Source: CSV in repo, estratto una tantum dai 12 xlsx bilancino staged
(union ORTI+INTUR, dedup per codice — vedi Task 6 brief).

Usage:
    python -m core.bq.load.load_conti_gruppi --dry-run
    python -m core.bq.load.load_conti_gruppi
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

try:
    from google.cloud import bigquery

    HAS_BQ = True
except ImportError:
    HAS_BQ = False

from core.bq.client import get_client
from core.config import PROJECT

BQ_TABLE = f"{PROJECT}.hotelops.d_conti_gruppi"

DEFAULT_FILE = (
    Path(__file__).resolve().parents[2] / "bq" / "dimensioni" / "d_conti_gruppi.csv"
)

BQ_SCHEMA = (
    [
        bigquery.SchemaField("codice_conto", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("descrizione", "STRING", mode="REQUIRED"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("load_conti_gruppi")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))
        log.addHandler(h)
    return log


def parse_csv(filepath: Path, logger: logging.Logger) -> list[dict]:
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            codice = row["codice_conto"].strip()
            descrizione = row["descrizione"].strip()
            if not codice or not descrizione:
                continue
            rows.append({"codice_conto": codice, "descrizione": descrizione})
    logger.info(f"  Conti gruppo parsati: {len(rows)}")
    return rows


def load_to_bq(rows: list[dict], logger: logging.Logger) -> None:
    if not rows:
        logger.warning("Nessuna riga da caricare")
        return

    bq_client = get_client()
    job = bq_client.load_table_from_json(
        rows,
        BQ_TABLE,
        job_config=bigquery.LoadJobConfig(
            schema=BQ_SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ),
    )
    job.result()
    if job.errors:
        logger.error(f"BQ errors: {job.errors}")
        sys.exit(1)
    logger.info(f"  {BQ_TABLE}: {len(rows)} righe caricate (WRITE_TRUNCATE)")


def main() -> None:
    parser = argparse.ArgumentParser(description="d_conti_gruppi CSV → BigQuery")
    parser.add_argument(
        "--file",
        default=str(DEFAULT_FILE),
        help="Path al CSV codice_conto,descrizione",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Parse only, no BQ write"
    )
    args = parser.parse_args()

    logger = setup_logger()
    filepath = Path(args.file)
    if not filepath.exists():
        logger.error(f"File non trovato: {filepath}")
        sys.exit(1)

    logger.info(f"File: {filepath.name}")
    rows = parse_csv(filepath, logger)
    if not rows:
        logger.error("Nessun conto gruppo estratto")
        sys.exit(1)

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura su BQ.")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    load_to_bq(rows, logger)
    logger.info("DONE")


if __name__ == "__main__":
    main()
