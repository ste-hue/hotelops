#!/usr/bin/env python3
"""DDL idempotente per f_produzione_pms (produzione giornaliera per classe).

Grana: giorno × struttura × classe, importo imponibile.
PARTITION BY data, CLUSTER BY business_unit_id, classe.
Lifecycle SNAPSHOT (natural_key business_unit_id, anno) — gestito dal parser.

Usage:
    python -m core.bq.load.create_produzione_table
    python -m core.bq.load.create_produzione_table --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys

from core.bq.client import get_client
from core.config import F_PRODUZIONE_PMS

DDL_F_PRODUZIONE_PMS = f"""
CREATE TABLE IF NOT EXISTS `{F_PRODUZIONE_PMS}` (
    societa_id           STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    data                 DATE NOT NULL,
    anno                 INT64 NOT NULL,
    mese                 INT64 NOT NULL,
    classe               STRING NOT NULL,
    importo_imponibile   NUMERIC NOT NULL,
    file_sorgente        STRING NOT NULL,
    hash_riga            STRING NOT NULL,
    raw_object_id        STRING,
    data_caricamento     TIMESTAMP NOT NULL
)
PARTITION BY data
CLUSTER BY business_unit_id, classe
"""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Print DDL without executing")
    args = p.parse_args()

    log = logging.getLogger("create_produzione_table")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log.info("DDL f_produzione_pms — idempotent (CREATE TABLE IF NOT EXISTS)")

    if args.dry_run:
        log.info(DDL_F_PRODUZIONE_PMS)
        return 0

    get_client().query(DDL_F_PRODUZIONE_PMS).result()
    log.info("OK f_produzione_pms creata/confermata")
    return 0


if __name__ == "__main__":
    sys.exit(main())
