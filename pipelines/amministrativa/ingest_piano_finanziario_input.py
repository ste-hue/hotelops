#!/usr/bin/env python3
"""
Piano Finanziario Input ingestion — WRITE_APPEND con hash dedup.

Carica valori prospettici manuali (es. fitti futuri, budget ricavi) in
f_piano_finanziario_input. Sicuro da ri-eseguire: hash dedup previene duplicati.

Input CSV atteso:
    societa_id, voce_id, anno, mese, importo, fonte, note

Hash key: MD5(societa_id | voce_id | anno | mese | fonte)

Usage:
    python -m pipelines.amministrativa.ingest_piano_finanziario_input \\
        --file /path/to/input.csv
    python -m pipelines.amministrativa.ingest_piano_finanziario_input \\
        --file /path/to/input.csv --dry-run
"""

import argparse
import csv
import hashlib
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from google.cloud import bigquery
    HAS_BQ = True
except ImportError:
    HAS_BQ = False

BQ_TABLE = "hotelops-suite.hotelops.f_piano_finanziario_input"

INPUT_COLUMNS = {"societa_id", "voce_id", "anno", "mese", "importo", "fonte", "note"}

BQ_SCHEMA = [
    bigquery.SchemaField("hash_riga",        "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("societa_id",       "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("voce_id",          "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("anno",             "INTEGER",   mode="REQUIRED"),
    bigquery.SchemaField("mese",             "INTEGER",   mode="REQUIRED"),
    bigquery.SchemaField("importo",          "FLOAT64"),
    bigquery.SchemaField("fonte",            "STRING"),
    bigquery.SchemaField("note",             "STRING"),
    bigquery.SchemaField("file_sorgente",    "STRING"),
    bigquery.SchemaField("data_caricamento", "TIMESTAMP"),
] if HAS_BQ else []


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_piano_finanziario_input")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def make_hash(societa_id: str, voce_id: str, anno: int, mese: int, fonte: str) -> str:
    key = f"{societa_id}|{voce_id}|{anno}|{mese}|{fonte}"
    return hashlib.md5(key.encode()).hexdigest()


def parse_input_csv(filepath: Path, logger: logging.Logger) -> list[dict]:
    now_ts = datetime.now(timezone.utc).isoformat()
    file_sorgente = filepath.name
    rows = []

    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = INPUT_COLUMNS - {c.strip() for c in (reader.fieldnames or [])}
        if missing:
            logger.error(f"Colonne mancanti nel CSV: {missing}")
            sys.exit(1)

        for i, row in enumerate(reader, start=2):
            societa_id = row["societa_id"].strip()
            voce_id    = row["voce_id"].strip()
            anno_str   = row["anno"].strip()
            mese_str   = row["mese"].strip()
            fonte      = row["fonte"].strip()

            if not all([societa_id, voce_id, anno_str, mese_str, fonte]):
                logger.warning(f"Riga {i}: campi obbligatori mancanti — riga saltata")
                continue

            try:
                anno = int(anno_str)
                mese = int(mese_str)
            except ValueError:
                logger.warning(f"Riga {i}: anno/mese non numerici ({anno_str}/{mese_str}) — riga saltata")
                continue

            if not (1 <= mese <= 12):
                logger.warning(f"Riga {i}: mese non valido ({mese}) — riga saltata")
                continue

            importo_str = row.get("importo", "").strip()
            importo = float(importo_str) if importo_str else None

            rows.append({
                "hash_riga":        make_hash(societa_id, voce_id, anno, mese, fonte),
                "societa_id":       societa_id,
                "voce_id":          voce_id,
                "anno":             anno,
                "mese":             mese,
                "importo":          importo,
                "fonte":            fonte,
                "note":             row.get("note", "").strip() or None,
                "file_sorgente":    file_sorgente,
                "data_caricamento": now_ts,
            })

    logger.info(f"Righe parsate: {len(rows)}")
    return rows


def load_existing_hashes(bq_client, file_sorgente: str, logger: logging.Logger) -> set:
    try:
        result = bq_client.query(
            f"SELECT hash_riga FROM `{BQ_TABLE}` WHERE file_sorgente = '{file_sorgente}'"
        ).result()
        hashes = {row.hash_riga for row in result}
        logger.info(f"Hash BQ esistenti per {file_sorgente}: {len(hashes)}")
        return hashes
    except Exception as e:
        logger.warning(f"Impossibile caricare hash BQ: {e}")
        return set()


def write_to_bq(rows: list[dict], bq_client, logger: logging.Logger):
    if not rows:
        return
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    )
    job = bq_client.load_table_from_json(rows, BQ_TABLE, job_config=job_config)
    job.result()
    if job.errors:
        logger.error(f"BQ errors: {job.errors}")
    else:
        logger.info(f"  BQ: {len(rows)} righe inserite in {BQ_TABLE}")


def main():
    parser = argparse.ArgumentParser(description="Ingest piano finanziario input CSV → f_piano_finanziario_input")
    parser.add_argument("--file", required=True, help="Path al CSV di input")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no write")
    args = parser.parse_args()

    logger = setup_logger()
    filepath = Path(args.file)
    if not filepath.exists():
        logger.error(f"File non trovato: {filepath}")
        sys.exit(1)

    rows = parse_input_csv(filepath, logger)

    # Summary
    by_fonte = {}
    by_societa = {}
    for r in rows:
        by_fonte[r["fonte"]] = by_fonte.get(r["fonte"], 0) + 1
        by_societa[r["societa_id"]] = by_societa.get(r["societa_id"], 0) + 1
    for k, n in sorted(by_fonte.items()):
        logger.info(f"  fonte={k}: {n} righe")
    for k, n in sorted(by_societa.items()):
        logger.info(f"  societa={k}: {n} righe")

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        for r in rows:
            logger.info(f"  {r['societa_id']} {r['voce_id']} {r['anno']}-{r['mese']:02d}: {r['importo']}")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    bq_client = bigquery.Client(project="hotelops-suite")
    existing = load_existing_hashes(bq_client, filepath.name, logger)
    new_rows = [r for r in rows if r["hash_riga"] not in existing]
    logger.info(f"Nuove righe: {len(new_rows)} (già presenti: {len(rows) - len(new_rows)})")

    write_to_bq(new_rows, bq_client, logger)
    logger.info("DONE")


if __name__ == "__main__":
    main()
