#!/usr/bin/env python3
"""
Piano dei conti loader — one-shot, idempotent.

Loads full Esolver chart of accounts from reconciliation_dino/docs/pianodeiconti.xlsx
into BigQuery d_piano_conti. Safe to re-run (WRITE_TRUNCATE).

Usage:
    python -m pipelines.amministrativa.ingest_piano_conti
    python -m pipelines.amministrativa.ingest_piano_conti --file /path/to/pianodeiconti.xlsx
    python -m pipelines.amministrativa.ingest_piano_conti --dry-run
"""

import argparse
import logging
import sys
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

BQ_TABLE = "hotelops-suite.hotelops.d_piano_conti"

DEFAULT_SOURCE = Path(
    "/Users/stefanodellapietra/dev/Projects/reconciliation_dino/docs/pianodeiconti.xlsx"
)

# Account prefix → business_unit_id (revenue accounts only)
BU_RICAVI_MAP = {
    "47.91": "HOTEL",
    "47.92": "RESIDENCE",
    "47.93": "CVM",
    "47.94": "LIDO",
    "47.95": "HQ",
}

BQ_SCHEMA = [
    bigquery.SchemaField("codice_conto", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("descrizione", "STRING"),
    bigquery.SchemaField("tipo_conto", "STRING"),   # SP / CE
    bigquery.SchemaField("sezione", "STRING"),       # Attivo / Passivo / Ricavi / Costi / ...
    bigquery.SchemaField("partitario", "STRING"),    # Si / No
    bigquery.SchemaField("business_unit_id", "STRING"),  # derived from 47.9x prefix
] if HAS_BQ else []


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_piano_conti")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def infer_business_unit(codice: str) -> str | None:
    for prefix, bu in BU_RICAVI_MAP.items():
        if codice.startswith(prefix):
            return bu
    return None


def parse_piano_conti(filepath: Path, logger: logging.Logger) -> list[dict]:
    if not HAS_OPENPYXL:
        logger.error("openpyxl not installed. Run: pip install openpyxl")
        sys.exit(1)

    wb = openpyxl.load_workbook(str(filepath), read_only=True)
    ws = wb.active
    rows = []
    skipped = 0

    for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True)):
        codice = str(row[0]).strip() if row[0] else None
        if not codice or codice == "None":
            skipped += 1
            continue

        descrizione = str(row[1]).strip() if row[1] else ""
        tipo_conto = str(row[2]).strip() if row[2] else ""
        sezione = str(row[3]).strip() if row[3] else ""
        partitario = str(row[4]).strip() if row[4] else ""
        business_unit_id = infer_business_unit(codice)

        rows.append({
            "codice_conto": codice,
            "descrizione": descrizione,
            "tipo_conto": tipo_conto,
            "sezione": sezione,
            "partitario": partitario,
            "business_unit_id": business_unit_id,
        })

    wb.close()
    logger.info(f"Conti parsati: {len(rows)} (skipped: {skipped})")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Load piano dei conti → d_piano_conti")
    parser.add_argument(
        "--file",
        default=str(DEFAULT_SOURCE),
        help=f"Path to pianodeiconti.xlsx (default: {DEFAULT_SOURCE})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no write")
    args = parser.parse_args()

    logger = setup_logger()
    filepath = Path(args.file)
    if not filepath.exists():
        logger.error(f"File non trovato: {filepath}")
        sys.exit(1)

    rows = parse_piano_conti(filepath, logger)

    # Summary
    by_tipo = {}
    for r in rows:
        t = r["tipo_conto"] or "?"
        by_tipo[t] = by_tipo.get(t, 0) + 1
    for t, n in sorted(by_tipo.items()):
        logger.info(f"  {t}: {n} conti")

    bu_conti = [r for r in rows if r["business_unit_id"]]
    logger.info(f"  Conti con business_unit_id (47.9x): {len(bu_conti)}")

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    bq_client = bigquery.Client(project="hotelops-suite")

    # WRITE_TRUNCATE — dimension table, safe to replace entirely
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    job = bq_client.load_table_from_json(rows, BQ_TABLE, job_config=job_config)
    job.result()

    if job.errors:
        logger.error(f"BQ load errors: {job.errors}")
        sys.exit(1)

    logger.info(f"d_piano_conti caricato: {len(rows)} righe → {BQ_TABLE}")
    logger.info("DONE")


if __name__ == "__main__":
    main()
