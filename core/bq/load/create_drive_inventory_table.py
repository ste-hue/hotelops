#!/usr/bin/env python3
"""DDL idempotente per f_drive_inventory (fotografia giornaliera dell'albero Drive).

Grana: giorno × oggetto Drive. PARTITION BY snapshot_date, CLUSTER BY root_key, md5.
Lifecycle SNAPSHOT: atomic replacement of one complete DATE partition through
bq_write_validated; unique objects by (snapshot_date, file_id), roots included. Spec: docs/superpowers/specs/2026-10-17-drive-agent-friendly-design.md

Usage:
    python -m core.bq.load.create_drive_inventory_table
    python -m core.bq.load.create_drive_inventory_table --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys

from core.bq.client import get_client
from core.config import F_DRIVE_INVENTORY

DDL_F_DRIVE_INVENTORY = f"""
CREATE TABLE IF NOT EXISTS `{F_DRIVE_INVENTORY}` (
    snapshot_date        DATE NOT NULL,
    file_id              STRING NOT NULL,
    name                 STRING NOT NULL,
    mime_type            STRING NOT NULL,
    size_bytes           INT64,
    md5                  STRING,
    sha256               STRING,
    modified_time        TIMESTAMP,
    created_time         TIMESTAMP,
    owner_email          STRING,
    parent_id            STRING,
    path                 STRING NOT NULL,
    root_key             STRING NOT NULL,
    root_keys            ARRAY<STRING>,
    inventory_root_keys  ARRAY<STRING>,
    configured_roots     ARRAY<STRING>,
    in_inbox_root        BOOL,
    observer_email       STRING,
    observed_at          TIMESTAMP,
    observation_raw_object_id STRING,
    permissions_observed BOOL,
    is_folder            BOOL NOT NULL,
    is_shortcut          BOOL NOT NULL,
    shortcut_target_id   STRING,
    perm_anyone          BOOL NOT NULL,
    perm_outside_domain  ARRAY<STRING>,
    raw_object_id        STRING
)
PARTITION BY snapshot_date
CLUSTER BY root_key, md5;
"""
# Upgrade any previously created draft table without rewriting old observations.
# Old rows lack coverage/provenance and are excluded by v_drive_inventory_current.
for column, kind in {
    "root_keys": "ARRAY<STRING>",
    "inventory_root_keys": "ARRAY<STRING>",
    "configured_roots": "ARRAY<STRING>",
    "in_inbox_root": "BOOL",
    "observer_email": "STRING",
    "observed_at": "TIMESTAMP",
    "observation_raw_object_id": "STRING",
    "permissions_observed": "BOOL",
}.items():
    DDL_F_DRIVE_INVENTORY += (
        f"ALTER TABLE `{F_DRIVE_INVENTORY}` ADD COLUMN IF NOT EXISTS {column} {kind};\n"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Print DDL without executing")
    args = p.parse_args()

    log = logging.getLogger("create_drive_inventory_table")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log.info("DDL f_drive_inventory — idempotent (CREATE TABLE IF NOT EXISTS)")

    if args.dry_run:
        log.info(DDL_F_DRIVE_INVENTORY)
        return 0

    get_client().query(DDL_F_DRIVE_INVENTORY).result()
    log.info("OK f_drive_inventory creata/confermata")
    return 0


if __name__ == "__main__":
    sys.exit(main())
