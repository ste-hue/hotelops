#!/usr/bin/env python3
"""
DDL idempotente per le 3 tabelle Projects (event-sourced Step 1).

Crea (CREATE TABLE IF NOT EXISTS):
- d_progetti                (SNAPSHOT)
- f_progetto_voci           (SNAPSHOT)
- f_progetto_eventi         (APPEND, PARTITION BY DATE(data_evento))

Usage:
    python -m core.bq.load.create_progetti_tables
    python -m core.bq.load.create_progetti_tables --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.bq.client import get_client
from core.config import D_PROGETTI, F_PROGETTO_EVENTI, F_PROGETTO_VOCI

DDL_D_PROGETTI = f"""
CREATE TABLE IF NOT EXISTS `{D_PROGETTI}` (
    progetto_id          STRING NOT NULL,
    nome                 STRING NOT NULL,
    societa_owner_id     STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    struttura            STRING,
    budget_cap_eur       NUMERIC NOT NULL,
    data_inizio          DATE NOT NULL,
    data_fine_prevista   DATE,
    stato                STRING NOT NULL,
    owner                STRING NOT NULL,
    drive_root_url       STRING,
    data_caricamento     TIMESTAMP NOT NULL
)
"""

DDL_F_PROGETTO_VOCI = f"""
CREATE TABLE IF NOT EXISTS `{F_PROGETTO_VOCI}` (
    voce_id              STRING NOT NULL,
    progetto_id          STRING NOT NULL,
    codice_interno       STRING NOT NULL,
    descrizione          STRING NOT NULL,
    categoria            STRING NOT NULL,
    qta                  NUMERIC,
    unita                STRING,
    fornitore_id         STRING,
    societa_pagante_id   STRING NOT NULL,
    note                 STRING,
    data_caricamento     TIMESTAMP NOT NULL
)
"""

DDL_F_PROGETTO_EVENTI = f"""
CREATE TABLE IF NOT EXISTS `{F_PROGETTO_EVENTI}` (
    evento_id            STRING NOT NULL,
    voce_id              STRING NOT NULL,
    progetto_id          STRING NOT NULL,
    tipo_evento          STRING NOT NULL,
    data_evento          DATE NOT NULL,
    data_registrazione   TIMESTAMP NOT NULL,
    importo_eur          NUMERIC,
    fornitore_id         STRING,
    metadata             JSON NOT NULL,
    file_sorgente        STRING
)
PARTITION BY data_evento
CLUSTER BY progetto_id, voce_id, tipo_evento
"""

DDL_STATEMENTS = [
    ("d_progetti", DDL_D_PROGETTI),
    ("f_progetto_voci", DDL_F_PROGETTO_VOCI),
    ("f_progetto_eventi", DDL_F_PROGETTO_EVENTI),
]


def setup_logger() -> logging.Logger:
    log = logging.getLogger("create_progetti_tables")
    log.setLevel(logging.INFO)
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    log.addHandler(h)
    return log


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Print DDL without executing")
    args = p.parse_args()

    log = setup_logger()
    log.info("DDL projects tables — idempotent (CREATE TABLE IF NOT EXISTS)")

    if args.dry_run:
        for name, ddl in DDL_STATEMENTS:
            log.info(f"--- {name} ---")
            print(ddl)
        return 0

    client = get_client()
    for name, ddl in DDL_STATEMENTS:
        log.info(f"Creating {name}...")
        job = client.query(ddl)
        job.result()  # blocks until complete
        log.info(f"  ✓ {name}")

    log.info("All 3 tables ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
