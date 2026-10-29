#!/usr/bin/env python3
"""DDL idempotente del dataset hotelops_previsioni (scenari di cassa salvati).

Va eseguito PRIMA del primo promote (filter_new_rows_by_hash fa SELECT sulla
canonical). Importi in centesimi interi; modelli in core.schemas.

Usage:
    python -m core.bq.load.create_previsioni_tables [--dry-run]
"""

from __future__ import annotations

import argparse
import logging

from core.bq.client import get_client
from core.config import (
    DATASET_PREVISIONI,
    P_PROGETTI_PAGAMENTI,
    P_SCENARI,
    P_SCENARIO_FLUSSI,
    PROJECT,
)

DDL_SCHEMA = (
    f"CREATE SCHEMA IF NOT EXISTS `{PROJECT}.{DATASET_PREVISIONI}` "
    'OPTIONS(location="EU")'
)

DDL_SCENARI = f"""
CREATE TABLE IF NOT EXISTS `{P_SCENARI}` (
    scenario_id       STRING NOT NULL,
    nome              STRING NOT NULL,
    creato_il         TIMESTAMP,
    autore            STRING,
    schema_doc        STRING,
    base              JSON,
    parametri         JSON,
    progetti_accesi   ARRAY<STRING>,
    note              STRING,
    raw_object_id     STRING,
    hash_riga         STRING NOT NULL,
    data_caricamento  TIMESTAMP NOT NULL
)
"""

DDL_FLUSSI = f"""
CREATE TABLE IF NOT EXISTS `{P_SCENARIO_FLUSSI}` (
    scenario_id       STRING NOT NULL,
    societa_id        STRING NOT NULL,
    mese              STRING NOT NULL,
    voce_id           STRING NOT NULL,
    importo_cent      INT64 NOT NULL,
    direzione         STRING NOT NULL,
    origine           STRING NOT NULL,
    raw_object_id     STRING,
    hash_riga         STRING NOT NULL,
    data_caricamento  TIMESTAMP NOT NULL
)
"""

DDL_PAGAMENTI = f"""
CREATE TABLE IF NOT EXISTS `{P_PROGETTI_PAGAMENTI}` (
    scenario_id         STRING NOT NULL,
    progetto_id         STRING NOT NULL,
    pagamento           STRING NOT NULL,
    mese                STRING NOT NULL,
    importo_netto_cent  INT64 NOT NULL,
    aliquota_iva        INT64 NOT NULL,
    stato               STRING NOT NULL,
    fornitore_id        STRING,
    societa_id          STRING NOT NULL,
    raw_object_id       STRING,
    hash_riga           STRING NOT NULL,
    data_caricamento    TIMESTAMP NOT NULL
)
"""

STATEMENTS = [DDL_SCHEMA, DDL_SCENARI, DDL_FLUSSI, DDL_PAGAMENTI]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    if args.dry_run:
        for ddl in STATEMENTS:
            print(ddl.strip() + ";\n")
        return
    client = get_client()
    for ddl in STATEMENTS:
        client.query(ddl).result()
    logging.info("OK %s", DATASET_PREVISIONI)


if __name__ == "__main__":
    main()
