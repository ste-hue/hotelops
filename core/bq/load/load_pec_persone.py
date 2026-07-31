#!/usr/bin/env python3
"""
PEC persone dimension loader — idempotente (WRITE_TRUNCATE).

Carica il CSV d_pec_persone → BigQuery d_pec_persone.
Rubrica indirizzo → persona per il corpus PEC (fonte: ricostruzione con
Stefano, sessione 2026-07-18 — dato statico, seedato a mano).

Usage:
    python -m core.bq.load.load_pec_persone
    python -m core.bq.load.load_pec_persone --dry-run
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
from core.config import D_PEC_PERSONE
from core.schemas import PecPersonaRow, validate_batch

DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[1] / "dimensioni" / "d_pec_persone.csv"
)

BQ_SCHEMA = (
    [
        bigquery.SchemaField("indirizzo", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("tipo_indirizzo", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("persona", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("generazione", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("ruolo", "STRING"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("load_pec_persone")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def parse_csv(filepath: Path, logger: logging.Logger) -> list[dict]:
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            indirizzo = row["indirizzo"].strip().lower()
            if not indirizzo:
                continue
            rows.append(
                {
                    "indirizzo": indirizzo,
                    "tipo_indirizzo": row["tipo_indirizzo"].strip(),
                    "persona": row["persona"].strip(),
                    "generazione": int(row["generazione"]),
                    "ruolo": row["ruolo"].strip() or None,
                }
            )
    logger.info("parse_csv: %d righe da %s", len(rows), filepath)
    return rows


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--file", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    log = setup_logger()

    rows = parse_csv(args.file, log)

    dup = [k for k, n in Counter(r["indirizzo"] for r in rows).items() if n > 1]
    if dup:
        log.error("indirizzi duplicati nel CSV: %s", dup)
        return 2

    validate_batch(rows, PecPersonaRow, context="d_pec_persone")
    per_persona = Counter(r["persona"] for r in rows)
    log.info(
        "validation OK: %d indirizzi, %d persone (%s)",
        len(rows),
        len(per_persona),
        ", ".join(f"{p}: {n}" for p, n in sorted(per_persona.items())),
    )

    if args.dry_run:
        log.info("[DRY RUN] nessuna scrittura su %s", D_PEC_PERSONE)
        return 0

    client = get_client()
    job = client.load_table_from_json(
        rows,
        D_PEC_PERSONE,
        job_config=bigquery.LoadJobConfig(
            schema=BQ_SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ),
    )
    job.result()
    log.info("caricate %d righe in %s (WRITE_TRUNCATE)", len(rows), D_PEC_PERSONE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
