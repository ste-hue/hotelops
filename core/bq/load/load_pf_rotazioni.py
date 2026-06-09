#!/usr/bin/env python3
"""Archivio rotazioni PF — tiene OGNI rotazione, taggata per file_sorgente.

Carica i Piano Finanziario (parsati dal parser esistente) in `f_pf_rotazioni`.
La chiave hash include `file_sorgente` → nessuna vintage sovrascrive l'altra:
marzo, aprile, maggio… coesistono. Tabella SEPARATA da `f_piano_finanziario_input`
(la cassa live NON si muove). Idempotente: ricaricare lo stesso file lo rimpiazza
(DELETE per file_sorgente + INSERT).

Usage:
    python -m core.bq.load.load_pf_rotazioni ORTI_PF_2026_03.xlsx ORTI_PF_2026-05.xlsx
    python -m core.bq.load.load_pf_rotazioni --dry-run *.xlsx
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import bigquery

from core.bq.client import get_client
from core.config import PROJECT
from ingest.flussi.ingest_piano_finanziario_xlsx import (
    parse_piano_finanziario,
    setup_logger,
)

BQ_TABLE = f"{PROJECT}.hotelops.f_pf_rotazioni"

SCHEMA = [
    bigquery.SchemaField("hash_riga", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("societa_id", "STRING"),
    bigquery.SchemaField("voce_id", "STRING"),
    bigquery.SchemaField("anno", "INTEGER"),
    bigquery.SchemaField("mese", "INTEGER"),
    bigquery.SchemaField("importo", "FLOAT64"),
    bigquery.SchemaField("fonte", "STRING"),
    bigquery.SchemaField("file_sorgente", "STRING"),
    bigquery.SchemaField("data_caricamento", "TIMESTAMP"),
]


def _hash(r: dict) -> str:
    key = (
        f"{r['societa_id']}|{r['voce_id']}|{r['anno']}|"
        f"{r['mese']}|{r['fonte']}|{r['file_sorgente']}"
    )
    return hashlib.md5(key.encode()).hexdigest()


def build_rows(paths: list[Path], logger) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    out: list[dict] = []
    for p in paths:
        for r in parse_piano_finanziario(p, None, logger):
            out.append(
                {
                    "hash_riga": _hash(r),
                    "societa_id": r["societa_id"],
                    "voce_id": r["voce_id"],
                    "anno": r["anno"],
                    "mese": r["mese"],
                    "importo": r.get("importo"),
                    "fonte": r.get("fonte", "PIANO_FINANZIARIO"),
                    "file_sorgente": r["file_sorgente"],
                    "data_caricamento": now,
                }
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="Path ai file PF xlsx")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logger = setup_logger()

    paths = [Path(f).expanduser() for f in args.files]
    rows = build_rows(paths, logger)
    per_file = Counter(r["file_sorgente"] for r in rows)
    logger.info(f"Totale: {len(rows)} righe su {len(paths)} file")
    for f, n in sorted(per_file.items()):
        logger.info(f"  {f}: {n} righe")

    if args.dry_run:
        logger.info("DRY-RUN — nessuna scrittura.")
        return

    client = get_client()
    client.create_table(bigquery.Table(BQ_TABLE, schema=SCHEMA), exists_ok=True)

    # Idempotenza: rimpiazza per-file (DELETE file_sorgente + INSERT).
    file_names = sorted(per_file)
    in_list = ", ".join(f"'{n}'" for n in file_names)
    client.query(
        f"DELETE FROM `{BQ_TABLE}` WHERE file_sorgente IN ({in_list})"
    ).result()

    job = client.load_table_from_json(
        rows,
        BQ_TABLE,
        job_config=bigquery.LoadJobConfig(
            schema=SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        ),
    )
    job.result()
    logger.info(f"✓ {len(rows)} righe in {BQ_TABLE}")


if __name__ == "__main__":
    main()
