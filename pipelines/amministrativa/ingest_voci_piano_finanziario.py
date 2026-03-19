#!/usr/bin/env python3
"""
Voci Piano Finanziario loader — idempotente (WRITE_TRUNCATE).

Carica il CSV di mappatura voci → BigQuery d_voci_piano_finanziario.
Sicuro da ri-eseguire: sovrascrive l'intera tabella.

Usage:
    python -m pipelines.amministrativa.ingest_voci_piano_finanziario
    python -m pipelines.amministrativa.ingest_voci_piano_finanziario \\
        --file bq/dimensioni/d_voci_piano_finanziario.csv
    python -m pipelines.amministrativa.ingest_voci_piano_finanziario --dry-run
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

BQ_TABLE = "hotelops-suite.hotelops.d_voci_piano_finanziario"

DEFAULT_SOURCE = Path(__file__).resolve().parents[2] / "bq" / "dimensioni" / "d_voci_piano_finanziario.csv"

BQ_SCHEMA = [
    bigquery.SchemaField("voce_id",            "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("voce_label",         "STRING"),
    bigquery.SchemaField("sezione",            "STRING"),
    bigquery.SchemaField("categoria",          "STRING"),
    bigquery.SchemaField("societa_id",         "STRING"),
    bigquery.SchemaField("fonte",              "STRING"),
    bigquery.SchemaField("cod_conto_pattern",  "STRING"),
    bigquery.SchemaField("cod_conto_pat2",     "STRING"),
    bigquery.SchemaField("cod_conto_pat3",     "STRING"),
    bigquery.SchemaField("banca_tipo_pat",     "STRING"),
    bigquery.SchemaField("ord",                "INTEGER"),
    bigquery.SchemaField("bu_filter",          "STRING"),
    bigquery.SchemaField("categoria_ce",       "STRING"),
    bigquery.SchemaField("tipo_costo",         "STRING"),
] if HAS_BQ else []


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_voci_piano_finanziario")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def parse_csv(filepath: Path, logger: logging.Logger) -> list[dict]:
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):
            voce_id = row["voce_id"].strip()
            if not voce_id:
                continue

            ord_val = row.get("ord", "").strip()

            rows.append({
                "voce_id":           voce_id,
                "voce_label":        row["voce_label"].strip() or None,
                "sezione":           row["sezione"].strip() or None,
                "categoria":         row["categoria"].strip() or None,
                "societa_id":        row["societa_id"].strip() or None,
                "fonte":             row["fonte"].strip() or None,
                "cod_conto_pattern": row["cod_conto_pattern"].strip() or None,
                "cod_conto_pat2":    row["cod_conto_pat2"].strip() or None,
                "cod_conto_pat3":    row["cod_conto_pat3"].strip() or None,
                "banca_tipo_pat":    row["banca_tipo_pat"].strip() or None,
                "ord":               int(ord_val) if ord_val else None,
                "bu_filter":         row["bu_filter"].strip() or None,
                "categoria_ce":      row.get("categoria_ce", "").strip() or None,
                "tipo_costo":        row.get("tipo_costo", "").strip() or None,
            })

    logger.info(f"Voci parsate: {len(rows)}")
    return rows


def main():
    parser = argparse.ArgumentParser(description="Load voci piano finanziario → d_voci_piano_finanziario")
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
    by_sezione = {}
    by_fonte = {}
    for r in rows:
        s = r["sezione"] or "?"
        by_sezione[s] = by_sezione.get(s, 0) + 1
        f = r["fonte"] or "?"
        by_fonte[f] = by_fonte.get(f, 0) + 1
    for s, n in sorted(by_sezione.items()):
        logger.info(f"  {s}: {n} voci")
    for f, n in sorted(by_fonte.items()):
        logger.info(f"  fonte={f}: {n} voci")

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        for r in rows:
            logger.info(f"  {r['voce_id']}: {r['voce_label']} | {r['fonte']} | {r['cod_conto_pattern']}")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    bq_client = bigquery.Client(project="hotelops-suite")

    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    job = bq_client.load_table_from_json(rows, BQ_TABLE, job_config=job_config)
    job.result()

    if job.errors:
        logger.error(f"BQ load errors: {job.errors}")
        sys.exit(1)

    logger.info(f"d_voci_piano_finanziario caricato: {len(rows)} righe → {BQ_TABLE}")
    logger.info("DONE")


if __name__ == "__main__":
    main()
