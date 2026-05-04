#!/usr/bin/env python3
"""
Saldi banca fine mese (manuali certificati) → BigQuery ``f_saldi_banca_chiusura_mensile``.

Fonte: ``core/bq/dimensioni/d_saldi_banca_chiusura_mensile.csv``
WRITE_TRUNCATE sull'intera tabella (il CSV è la verità).

Usage:
    python -m core.bq.load.load_saldi_banca_chiusura_mensile
    python -m core.bq.load.load_saldi_banca_chiusura_mensile --dry-run
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime
from pathlib import Path

try:
    from google.cloud import bigquery

    HAS_BQ = True
except ImportError:
    HAS_BQ = False

from core.bq.client import get_client
from core.config import F_SALDI_BANCA_CHIUSURA_MENSILE
from core.schemas import SaldoBancaChiusuraMensileRow, validate_batch

DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[1] / "dimensioni" / "d_saldi_banca_chiusura_mensile.csv"
)

BQ_SCHEMA = (
    [
        bigquery.SchemaField("societa_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("data_riferimento", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("banca_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("saldo_eur", "FLOAT", mode="REQUIRED"),
        bigquery.SchemaField("note", "STRING"),
    ]
    if HAS_BQ
    else []
)


def setup_logger() -> logging.Logger:
    log = logging.getLogger("load_saldi_banca_chiusura")
    log.setLevel(logging.DEBUG)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def _parse_importo_eur(raw: str) -> float:
    """Italiano 52.799,65 o anglosassone 52799.65."""
    s = raw.strip()
    if not s:
        raise ValueError("importo vuoto")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def parse_csv(filepath: Path, logger: logging.Logger) -> list[dict]:
    rows_out: list[dict] = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            soc = (row.get("societa_id") or "").strip().upper()
            dr = (row.get("data_riferimento") or "").strip()
            bnk = (row.get("banca_id") or "").strip().upper()
            saldo_raw = (row.get("saldo_eur") or "").strip()
            if not soc or not dr or not bnk or not saldo_raw:
                continue
            try:
                saldo = _parse_importo_eur(saldo_raw)
            except ValueError:
                logger.warning(f"Saldo non numerico, riga saltata: {row}")
                continue
            datetime.strptime(dr, "%Y-%m-%d")  # validate
            rows_out.append(
                {
                    "societa_id": soc,
                    "data_riferimento": dr,
                    "banca_id": bnk,
                    "saldo_eur": saldo,
                    "note": (row.get("note") or "").strip() or None,
                }
            )
    logger.info(f"Righe parsate: {len(rows_out)}")
    return rows_out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Carica d_saldi_banca_chiusura_mensile.csv → f_saldi_banca_chiusura_mensile"
    )
    parser.add_argument("--file", default=str(DEFAULT_SOURCE), help="Path al CSV")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logger = setup_logger()
    path = Path(args.file)
    if not path.exists():
        logger.error(f"File non trovato: {path}")
        sys.exit(1)

    raw = parse_csv(path, logger)
    validate_batch(raw, SaldoBancaChiusuraMensileRow, "f_saldi_banca_chiusura_mensile")

    if args.dry_run:
        for r in raw:
            logger.info(f"  {r['societa_id']} {r['data_riferimento']} {r['banca_id']}: {r['saldo_eur']:,.2f}")
        logger.info("DRY RUN — nessuna scrittura")
        return

    if not HAS_BQ:
        logger.error("google-cloud-bigquery non installato")
        sys.exit(1)

    client = get_client()
    job_config = bigquery.LoadJobConfig(
        schema=BQ_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = client.load_table_from_json(raw, F_SALDI_BANCA_CHIUSURA_MENSILE, job_config=job_config)
    job.result()
    if job.errors:
        logger.error(f"BQ: {job.errors}")
        sys.exit(1)
    logger.info(f"Caricato {len(raw)} righe → {F_SALDI_BANCA_CHIUSURA_MENSILE}")


if __name__ == "__main__":
    main()
