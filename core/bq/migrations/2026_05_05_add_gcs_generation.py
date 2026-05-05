"""One-shot migration: ALTER TABLE f_raw_objects ADD COLUMN gcs_generation INT64.

Idempotent: probes column existence via INFORMATION_SCHEMA before altering.
Run: python -m core.bq.migrations.2026_05_05_add_gcs_generation
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"
TABLE = "f_raw_objects"
COLUMN = "gcs_generation"


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
        f"ADD COLUMN {COLUMN} INT64 "
        f"OPTIONS(description=\"GCS object generation when raw_backend='gcs'; NULL otherwise\")"
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
