#!/usr/bin/env python3
"""DDL idempotente per f_stampa_cassa (HotelCube «Stampa Cassa», incassi per documento).

Va eseguito PRIMA del primo promote: filter_new_rows_by_hash fa SELECT sulla
canonical e su una tabella inesistente il promote esce VALIDATE_FAIL (trappola
chicken-egg, PEC 2026-07-08). Lifecycle APPEND, dedup hash_riga, parser
ingest.flussi.ingest_stampa_cassa.

Usage:
    python -m core.bq.load.create_stampa_cassa_table [--dry-run]
"""

from __future__ import annotations

import argparse
import logging

from core.bq.client import get_client
from core.config import F_STAMPA_CASSA

DDL = f"""
CREATE TABLE IF NOT EXISTS `{F_STAMPA_CASSA}` (
    societa_id        STRING NOT NULL,
    business_unit_id  STRING NOT NULL,
    location_id       STRING,
    oggetto_id        STRING,
    funzione_id       STRING,
    data              DATE NOT NULL,
    ora               STRING,
    data_ora          DATETIME,
    operatore         STRING,
    camera            STRING,
    ospite            STRING,
    pagante           STRING,
    numero_doc        STRING NOT NULL,
    anno_doc          INT64,
    serie_doc         STRING,
    numero            INT64,
    importo           FLOAT64 NOT NULL,
    totale_doc        FLOAT64,
    sezione           STRING NOT NULL,
    metodo_pagamento  STRING,
    is_acconto        BOOL NOT NULL,
    occorrenza        INT64 NOT NULL,
    raw_object_id     STRING,
    file_sorgente     STRING NOT NULL,
    hash_riga         STRING NOT NULL,
    data_caricamento  TIMESTAMP NOT NULL
)
PARTITION BY data
CLUSTER BY business_unit_id, sezione
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.dry_run:
        print(DDL)
        return
    get_client().query(DDL).result()
    logging.info("OK %s", F_STAMPA_CASSA)


if __name__ == "__main__":
    main()
