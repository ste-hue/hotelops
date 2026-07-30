#!/usr/bin/env python3
"""DDL idempotente per f_menu_engineering (pre-crea PRIMA del primo promote —
lezione chicken-egg PEC: filter_new_rows_by_hash esplode su tabella inesistente).

Usage:
    python -m core.bq.load.create_menu_engineering_table [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.bq.client import get_client
from core.config import F_MENU_ENGINEERING

DDL = f"""
CREATE TABLE IF NOT EXISTS `{F_MENU_ENGINEERING}` (
    hash_riga            STRING NOT NULL,
    societa_id           STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    snapshot_date        DATE NOT NULL,
    sala                 STRING NOT NULL,
    piatto               STRING NOT NULL,
    descrizione          STRING,
    tipo                 STRING,
    m_class              STRING,
    prezzo_unitario      FLOAT64,
    costo_unitario       FLOAT64,
    quantita             FLOAT64,
    incidenza_pct        FLOAT64,
    costo_totale         FLOAT64,
    listino              FLOAT64,
    vendita              FLOAT64,
    importo_addebitato   FLOAT64,
    importo_fatturato    FLOAT64,
    file_sorgente        STRING NOT NULL,
    raw_object_id        STRING,
    data_caricamento     TIMESTAMP NOT NULL
)
"""

log = logging.getLogger("create_menu_engineering_table")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.dry_run:
        log.info("[DRY-RUN]\n%s", DDL)
        return 0
    get_client().query(DDL).result()
    log.info("OK %s", F_MENU_ENGINEERING)
    return 0


if __name__ == "__main__":
    sys.exit(main())
