"""One-shot migration: ALTER TABLE f_banche_movimenti ADD COLUMN raw_object_id STRING.

Idempotent: probes column existence via INFORMATION_SCHEMA before altering.
NULLABLE so historical rows (pre-Phase-4-FK) stay valid.
Run: python -m core.bq.migrations.2026_05_06_add_raw_object_id_f_banche_movimenti
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"
TABLE = "f_banche_movimenti"
COLUMN = "raw_object_id"


def column_exists() -> bool:
    from core.bq.client import get_client

    client = get_client()
    sql = f"""
    SELECT 1
    FROM `{PROJECT}.{DATASET}.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = '{TABLE}' AND column_name = '{COLUMN}'
    """
    return any(client.query(sql).result())


def run(dry_run: bool = False) -> None:
    if column_exists():
        log.info("Column %s.%s.%s already exists — no-op.", DATASET, TABLE, COLUMN)
        return

    sql = (
        f"ALTER TABLE `{PROJECT}.{DATASET}.{TABLE}` "
        f"ADD COLUMN {COLUMN} STRING "
        f'OPTIONS(description="FK to f_raw_objects.raw_object_id; NULL for pre-Phase-4-FK historical rows")'
    )
    if dry_run:
        log.info("[DRY RUN] would execute: %s", sql)
        return

    from core.bq.client import get_client

    client = get_client()
    client.query(sql).result()
    log.info("ALTER TABLE complete: added %s.%s.%s", DATASET, TABLE, COLUMN)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
