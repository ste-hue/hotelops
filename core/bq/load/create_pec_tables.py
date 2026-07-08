#!/usr/bin/env python3
"""DDL idempotente per le 2 tabelle canonical del flusso PEC.

f_pec_messages / f_pec_allegati.
Lifecycle APPEND (dedup su hash_riga per messaggio, hash_riga per allegato)
— gestito dal parser ingest.flussi.ingest_pec.

Usage:
    python -m core.bq.load.create_pec_tables
    python -m core.bq.load.create_pec_tables --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.bq.client import get_client
from core.config import F_PEC_MESSAGES, F_PEC_ALLEGATI

DDL_MESSAGES = f"""
CREATE TABLE IF NOT EXISTS `{F_PEC_MESSAGES}` (
    msgid                STRING NOT NULL,
    source_folder        STRING NOT NULL,
    tipo                 STRING NOT NULL,
    ref_msgid            STRING,
    data_evento          DATETIME NOT NULL,
    data_certificata     BOOL NOT NULL,
    mittente             STRING,
    destinatari          STRING,
    n_destinatari        INT64 NOT NULL,
    subject              STRING,
    body_text            STRING,
    provider             STRING,
    casella              STRING NOT NULL,
    societa_id           STRING NOT NULL,
    n_allegati           INT64 NOT NULL,
    ha_postacert         BOOL NOT NULL,
    parse_warning        STRING,
    hash_riga            STRING NOT NULL,
    raw_object_id        STRING NOT NULL,
    data_caricamento     DATETIME NOT NULL
)
"""

DDL_ALLEGATI = f"""
CREATE TABLE IF NOT EXISTS `{F_PEC_ALLEGATI}` (
    msgid                STRING NOT NULL,
    nome_file            STRING NOT NULL,
    mime_type            STRING,
    size_bytes           INT64 NOT NULL,
    sha256               STRING NOT NULL,
    is_firmato           BOOL NOT NULL,
    gcs_uri              STRING,
    hash_riga            STRING NOT NULL,
    raw_object_id        STRING NOT NULL,
    data_caricamento     DATETIME NOT NULL
)
"""

ALL_DDL = {
    "f_pec_messages": DDL_MESSAGES,
    "f_pec_allegati": DDL_ALLEGATI,
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Print DDL without executing")
    args = p.parse_args()

    log = logging.getLogger("create_pec_tables")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.dry_run:
        for name, ddl in ALL_DDL.items():
            log.info("--- %s ---%s", name, ddl)
        return 0

    client = get_client()
    for name, ddl in ALL_DDL.items():
        client.query(ddl).result()
        log.info("OK %s creata/confermata", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
