#!/usr/bin/env python3
"""
Fornitori dimension loader — idempotente (WRITE_TRUNCATE).

Carica il CSV d_fornitori → BigQuery d_fornitori.
Mappa codice_fornitore Esolver a voce_id Piano Finanziario.

Usage:
    python -m core.bq.load.load_fornitori
    python -m core.bq.load.load_fornitori --file bq/dimensioni/d_fornitori.csv
    python -m core.bq.load.load_fornitori --dry-run
"""

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

BQ_TABLE = f"{PROJECT}.hotelops.d_fornitori"

DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[2] / "bq" / "dimensioni" / "d_fornitori.csv"
)

BQ_SCHEMA = (
    [
        bigquery.SchemaField("codice_fornitore", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("nome_esolver", "STRING"),
        bigquery.SchemaField("nome_pf", "STRING"),
        bigquery.SchemaField("voce_id", "STRING"),
        bigquery.SchemaField("is_intercompany", "BOOLEAN"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_fornitori")
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
            codice = row["codice_fornitore"].strip()
            if not codice:
                continue
            is_ic_raw = row.get("is_intercompany", "False").strip().lower()
            rows.append(
                {
                    "codice_fornitore": int(codice),
                    "nome_esolver": row["nome_esolver"].strip() or None,
                    "nome_pf": row.get("nome_pf", "").strip() or None,
                    "voce_id": row.get("voce_id", "").strip() or None,
                    "is_intercompany": is_ic_raw in ("true", "1", "yes"),
                }
            )

    logger.info(f"Fornitori parsati: {len(rows)}")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Load d_fornitori → BigQuery")
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

    # Summary
    with_voce = sum(1 for r in rows if r["voce_id"])
    interco = sum(1 for r in rows if r["is_intercompany"])
    logger.info(f"  con voce_id: {with_voce}, intercompany: {interco}")

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        for r in rows:
            logger.info(
                f"  {r['codice_fornitore']:>4} | {r['nome_esolver']:<40} | {r['voce_id'] or '-'}"
            )
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

    logger.info(f"d_fornitori caricato: {len(rows)} righe → {BQ_TABLE}")
    logger.info("DONE")


if __name__ == "__main__":
    main()
