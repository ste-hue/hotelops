"""Migration: add lineage_era column to f_raw_objects.

Idempotent — safe to re-run. Uses ADD COLUMN IF NOT EXISTS (supported by BigQuery).

Run once after deploying the Phase 4 / Track B changes:
    python -m core.bq.load.migrate_add_lineage_era

After this migration:
  - New rows written by register_raw_object get lineage_era='live'.
  - Existing rows (pre-Phase-4 smoke tests) will have lineage_era=NULL.
    Query with COALESCE(lineage_era, 'pre_phase4') to treat them as legacy.
"""

from __future__ import annotations

import logging

from core.bq.client import get_client

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"
TABLE = f"`{PROJECT}.{DATASET}.f_raw_objects`"

DDL = f"""
ALTER TABLE {TABLE}
ADD COLUMN IF NOT EXISTS lineage_era STRING
  OPTIONS(description="'live' for GCS-backed rows (Phase 4+); 'pre_phase4' for legacy file:// / drive:// rows")
"""


def migrate(dry_run: bool = False) -> None:
    if dry_run:
        log.info("[DRY-RUN] would execute: %s", DDL.strip())
        return
    client = get_client()
    try:
        client.query(DDL).result()
        log.info("✓ lineage_era column added to f_raw_objects")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            log.info("lineage_era column already exists — skipping")
        else:
            raise


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Add lineage_era to f_raw_objects")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
