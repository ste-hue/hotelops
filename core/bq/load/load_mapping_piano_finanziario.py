#!/usr/bin/env python3
"""
Mapping Piano Finanziario loader — idempotente (WRITE_TRUNCATE).

Carica il CSV di mappatura sotto-voci PF → codici Esolver in BQ.
Ogni riga collega una sotto-voce del PF Excel a:
  - FORNITORE: codice_fornitore (FK → d_anagrafica_fornitori)
  - CATEGORIA: cod_conto_pattern (pattern Esolver)

Usage:
    python -m core.bq.load.load_mapping_piano_finanziario
    python -m core.bq.load.load_mapping_piano_finanziario --dry-run
    python -m core.bq.load.load_mapping_piano_finanziario \\
        --file core/bq/dimensioni/d_mapping_piano_finanziario.csv
"""

import argparse
import csv
import logging
import sys
from pathlib import Path

from core.bq.client import get_client
from core.config import D_MAPPING_PIANO_FINANZIARIO
from core.schemas import MappingPianoFinanziarioRow, validate_batch

try:
    from google.cloud import bigquery

    HAS_BQ = True
except ImportError:
    HAS_BQ = False

DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "core"
    / "bq"
    / "dimensioni"
    / "d_mapping_piano_finanziario.csv"
)

BQ_SCHEMA = (
    [
        bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("voce_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("sotto_voce", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("tipo", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("codice_fornitore", "INTEGER"),
        bigquery.SchemaField("cod_conto_pattern", "STRING"),
        bigquery.SchemaField("nome_esolver", "STRING"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("ingest_mapping_piano_finanziario")
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
            # Skip comment lines and empty rows
            societa = row.get("societa_id", "").strip()
            if not societa or societa.startswith("#"):
                continue

            voce_id = row.get("voce_id", "").strip()
            sotto_voce = row.get("sotto_voce", "").strip()
            tipo = row.get("tipo", "").strip()
            if not voce_id or not sotto_voce or not tipo:
                logger.warning(f"Riga {i} incompleta, skip: {row}")
                continue

            cod_forn = row.get("codice_fornitore", "").strip()
            cod_conto = row.get("cod_conto_pattern", "").strip()
            nome = row.get("nome_esolver", "").strip()

            # Skip TODO placeholders
            if cod_conto in ("TODO", "TODO_BANCA"):
                cod_conto = None

            if nome == "TODO_NOME_ESOLVER":
                nome = None

            # Skip FORNITORE rows without codice — incomplete data
            if tipo == "FORNITORE" and not cod_forn:
                logger.warning(f"Riga {i} skip: FORNITORE senza codice — {sotto_voce}")
                continue

            rows.append(
                {
                    "societa_id": societa,
                    "voce_id": voce_id,
                    "sotto_voce": sotto_voce,
                    "tipo": tipo,
                    "codice_fornitore": int(cod_forn) if cod_forn else None,
                    "cod_conto_pattern": cod_conto or None,
                    "nome_esolver": nome or None,
                }
            )

    logger.info(f"Righe mappatura parsate: {len(rows)}")
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Load mapping piano finanziario → d_mapping_piano_finanziario"
    )
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
    by_voce = {}
    by_tipo = {}
    todos = 0
    for r in rows:
        v = r["voce_id"]
        by_voce[v] = by_voce.get(v, 0) + 1
        t = r["tipo"]
        by_tipo[t] = by_tipo.get(t, 0) + 1
        if r["tipo"] == "FORNITORE" and not r["codice_fornitore"]:
            todos += 1
        if r["tipo"] == "CATEGORIA" and not r["cod_conto_pattern"]:
            todos += 1

    logger.info("Per voce:")
    for v, n in sorted(by_voce.items()):
        logger.info(f"  {v}: {n} sotto-voci")
    logger.info(f"Per tipo: {by_tipo}")
    if todos:
        logger.warning(f"TODO incompleti: {todos} righe senza codice")

    validate_batch(
        rows, MappingPianoFinanziarioRow, context="mapping_piano_finanziario"
    )
    logger.info("Schema validation OK")

    if args.dry_run:
        logger.info("DRY RUN — nessuna scrittura")
        for r in rows:
            marker = (
                r["codice_fornitore"]
                if r["tipo"] == "FORNITORE"
                else r["cod_conto_pattern"]
            )
            logger.info(
                f"  {r['societa_id']} | {r['voce_id']:30s} | {r['sotto_voce']:35s} | {r['tipo']:10s} | {marker}"
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
    job = bq_client.load_table_from_json(
        rows, D_MAPPING_PIANO_FINANZIARIO, job_config=job_config
    )
    job.result()

    if job.errors:
        logger.error(f"BQ load errors: {job.errors}")
        sys.exit(1)

    logger.info(
        f"d_mapping_piano_finanziario caricato: {len(rows)} righe → {D_MAPPING_PIANO_FINANZIARIO}"
    )


if __name__ == "__main__":
    main()
