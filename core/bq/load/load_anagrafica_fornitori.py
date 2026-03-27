#!/usr/bin/env python3
"""
Anagrafica Fornitori loader — idempotente (WRITE_TRUNCATE).

Carica l'export Esolver anagrafica fornitori (XLSX) → BigQuery d_anagrafica_fornitori.
Questa e' la fonte di verita' per l'identita' dei fornitori.

Usage:
    python -m core.bq.load.load_anagrafica_fornitori \\
        --file ~/Desktop/WORK/artifacts/anagraficafornitori.xlsx
    python -m core.bq.load.load_anagrafica_fornitori --dry-run \\
        --file ~/Desktop/WORK/artifacts/anagraficafornitori.xlsx
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from core.config import D_ANAGRAFICA_FORNITORI
from core.schemas import AnagraficaFornitoreRow, validate_batch

try:
    from google.cloud import bigquery
    HAS_BQ = True
except ImportError:
    HAS_BQ = False

BQ_SCHEMA = [
    bigquery.SchemaField("codice_fornitore",  "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("ragione_sociale",    "STRING",  mode="REQUIRED"),
    bigquery.SchemaField("partita_iva",        "STRING"),
    bigquery.SchemaField("codice_fiscale",     "STRING"),
    bigquery.SchemaField("comune",             "STRING"),
    bigquery.SchemaField("provincia",          "STRING"),
    bigquery.SchemaField("tipo_soggetto",      "STRING"),
    bigquery.SchemaField("stato_anagrafica",   "STRING"),
    bigquery.SchemaField("data_caricamento",   "STRING",  mode="REQUIRED"),
] if HAS_BQ else []


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_anagrafica_fornitori")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def parse_xlsx(filepath: Path, logger: logging.Logger) -> list[dict]:
    df = pd.read_excel(filepath)
    logger.info(f"Righe lette: {len(df)}, colonne: {list(df.columns)}")

    now = datetime.now(timezone.utc).isoformat()
    rows = []

    for _, r in df.iterrows():
        codice = r.get("Codice")
        rag_soc = r.get("Ragione sociale", "")
        if pd.isna(codice) or pd.isna(rag_soc) or not str(rag_soc).strip():
            continue

        rows.append({
            "codice_fornitore": int(codice),
            "ragione_sociale": str(rag_soc).strip(),
            "partita_iva": str(r.get("Partita IVA", "")).strip() or None,
            "codice_fiscale": str(r.get("Codice fiscale", "")).strip() or None,
            "comune": str(r.get("Comune", "")).strip() or None,
            "provincia": str(r.get("Provincia", "")).strip() or None,
            "tipo_soggetto": str(r.get("Tipo soggetto", "")).strip() or None,
            "stato_anagrafica": str(r.get("Stato anagrafica", "")).strip() or None,
            "data_caricamento": now,
        })

    # Clean up None-string artifacts from pandas
    for row in rows:
        for k, v in row.items():
            if v == "nan" or v == "None":
                row[k] = None

    logger.info(f"Fornitori validi: {len(rows)}")
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Load Esolver anagrafica fornitori → d_anagrafica_fornitori"
    )
    parser.add_argument("--file", required=True, help="Path al XLSX export Esolver")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no write")
    args = parser.parse_args()

    logger = setup_logger()
    filepath = Path(args.file).expanduser()
    if not filepath.exists():
        logger.error(f"File non trovato: {filepath}")
        sys.exit(1)

    rows = parse_xlsx(filepath, logger)
    validate_batch(rows, AnagraficaFornitoreRow, context="anagrafica_fornitori")
    logger.info("Schema validation OK")

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        for r in rows[:10]:
            logger.info(f"  {r['codice_fornitore']:>5} | {r['ragione_sociale']}")
        if len(rows) > 10:
            logger.info(f"  ... e altre {len(rows) - 10} righe")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    bq_client = bigquery.Client(project="hotelops-suite")
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = bq_client.load_table_from_json(rows, D_ANAGRAFICA_FORNITORI, job_config=job_config)
    job.result()

    if job.errors:
        logger.error(f"BQ load errors: {job.errors}")
        sys.exit(1)

    logger.info(f"d_anagrafica_fornitori caricato: {len(rows)} righe → {D_ANAGRAFICA_FORNITORI}")


if __name__ == "__main__":
    main()
