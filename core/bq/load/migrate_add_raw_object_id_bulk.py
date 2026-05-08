"""Bulk migration: add raw_object_id column to all canonical fact tables.

Idempotent — safe to re-run.  BigQuery's ALTER TABLE ADD COLUMN IF NOT EXISTS
is supported since ~2022; we catch any "already exists" errors for safety.

Run ONCE after deploying Phase 4 / Track C changes:
    python -m core.bq.load.migrate_add_raw_object_id_bulk

Tables migrated:
    f_banche_movimenti          (already has raw_object_id from Phase 4 pilot)
    f_movimenti_contabili
    f_budget_mensile
    f_piano_finanziario_input
    f_saldi_banca_snapshot
    f_partite_aperte_fornitori
    f_coperti_giornalieri
    f_bilancino
    f_accodamenti
    f_consumi_economato

Also runs the lineage_era migration for f_raw_objects.
"""

from __future__ import annotations

import logging

from core.bq.client import get_client

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"

# Tables that need raw_object_id added (raw_object_id was already added to
# f_banche_movimenti in Phase 4 pilot — still safe to include, IF NOT EXISTS handles it).
RAW_OBJECT_ID_TABLES = [
    "f_banche_movimenti",
    "f_movimenti_contabili",
    "f_budget_mensile",
    "f_piano_finanziario_input",
    "f_saldi_banca_snapshot",
    "f_partite_aperte_fornitori",
    "f_coperti_giornalieri",
    "f_bilancino",
    "f_accodamenti",
    "f_consumi_economato",
]


def _alter_add_if_needed(
    client, table: str, column: str, col_type: str, description: str, dry_run: bool
) -> bool:
    """Add column to table.  Returns True if action taken, False if already present."""
    ddl = (
        f"ALTER TABLE `{PROJECT}.{DATASET}.{table}` "
        f"ADD COLUMN IF NOT EXISTS {column} {col_type} "
        f"OPTIONS(description=\"{description}\")"
    )
    if dry_run:
        log.info("[DRY-RUN] %s", ddl)
        return True
    try:
        client.query(ddl).result()
        log.info("✓ %s.%s added", table, column)
        return True
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
            log.info("  %s.%s already present — skip", table, column)
            return False
        raise


def migrate(dry_run: bool = False) -> None:
    client = get_client()

    # 1. Add raw_object_id to all canonical fact tables
    for table in RAW_OBJECT_ID_TABLES:
        _alter_add_if_needed(
            client,
            table,
            "raw_object_id",
            "STRING",
            "FK to f_raw_objects.raw_object_id (Phase 4 lineage FK; NULL = pre-lineage era)",
            dry_run,
        )

    # 2. Add lineage_era to f_raw_objects (delegate to existing migration)
    from core.bq.load.migrate_add_lineage_era import migrate as migrate_era
    migrate_era(dry_run=dry_run)

    log.info("✓ Bulk migration complete")


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(
        description="Add raw_object_id to canonical fact tables + lineage_era to f_raw_objects"
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
