#!/usr/bin/env python3
"""
Categorie gestionali loader — d_categorie_gestionali.

Classificazione gestionale a dieci categorie dei conti CE (Ricavi, Personale,
Commerciali, Acquisti operativi, Utenze, Manutenzioni, Amministrativi,
Affitti e canoni, Imposte, Finanziari, Investimenti) + flag intercompany.
Decisa il 2026-10-27 per il CE gestionale del CdG; affianca `d_categorie_conti`
(categoria_ce di Gasparotto, caricata da xlsx con WRITE_TRUNCATE) senza toccarla.

Source: CSV in repo (`core/bq/dimensioni/d_categorie_gestionali.csv`), un conto
per riga; un conto nuovo nel bilancino senza riga qui esce dalla vista
`v_ce_mensile_bilancino` come categoria_gestionale NULL (fail-visible).

Usage:
    python -m core.bq.load.load_categorie_gestionali --dry-run
    python -m core.bq.load.load_categorie_gestionali
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

BQ_TABLE = f"{PROJECT}.hotelops.d_categorie_gestionali"

DEFAULT_FILE = (
    Path(__file__).resolve().parents[2]
    / "bq"
    / "dimensioni"
    / "d_categorie_gestionali.csv"
)

CATEGORIE = frozenset(
    {
        "Ricavi",
        "Personale",
        "Commerciali",
        "Acquisti operativi",
        "Utenze",
        "Manutenzioni",
        "Amministrativi",
        "Affitti e canoni",
        "Imposte",
        "Finanziari",
        "Investimenti",
    }
)

BQ_SCHEMA = (
    [
        bigquery.SchemaField("codice_conto", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("descrizione", "STRING"),
        bigquery.SchemaField("categoria_gestionale", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("is_intercompany", "BOOLEAN", mode="REQUIRED"),
        bigquery.SchemaField("nota", "STRING"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("load_categorie_gestionali")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))
        log.addHandler(h)
    return log


def parse_csv(filepath: Path, logger: logging.Logger) -> list[dict]:
    rows = []
    seen: set[str] = set()
    with open(filepath, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            codice = row["codice_conto"].strip()
            cat = row["categoria_gestionale"].strip()
            if not codice:
                continue
            if codice in seen:
                raise ValueError(f"codice_conto duplicato: {codice}")
            if cat not in CATEGORIE:
                raise ValueError(f"{codice}: categoria sconosciuta '{cat}'")
            seen.add(codice)
            rows.append(
                {
                    "codice_conto": codice,
                    "descrizione": row["descrizione"].strip() or None,
                    "categoria_gestionale": cat,
                    "is_intercompany": row["is_intercompany"].strip().lower() == "true",
                    "nota": row["nota"].strip() or None,
                }
            )
    logger.info(f"  Conti classificati: {len(rows)}")
    by_cat: dict[str, int] = {}
    for r in rows:
        by_cat[r["categoria_gestionale"]] = by_cat.get(r["categoria_gestionale"], 0) + 1
    for cat, n in sorted(by_cat.items()):
        logger.info(f"    {cat:<20s} {n:>3d}")
    logger.info(f"    intercompany: {sum(r['is_intercompany'] for r in rows)}")
    return rows


def load_to_bq(rows: list[dict], logger: logging.Logger) -> None:
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
    parser = argparse.ArgumentParser(
        description="d_categorie_gestionali CSV → BigQuery"
    )
    parser.add_argument("--file", default=str(DEFAULT_FILE), help="Path al CSV")
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
        logger.error("Nessun conto estratto")
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
