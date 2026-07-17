"""One-shot: ALTER f_pec_messages ADD entity_id STRING + backfill da societa_id.

Idempotente: probe INFORMATION_SCHEMA; il backfill tocca solo righe con
entity_id NULL. Le righe esistenti sono tutte INTUR (unica casella ingerita).
Run: python -m core.bq.migrations.2026_07_17_add_entity_id_f_pec_messages
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"
TABLE = "f_pec_messages"
COLUMN = "entity_id"


def column_exists() -> bool:
    from core.bq.client import get_client

    sql = f"""
    SELECT 1
    FROM `{PROJECT}.{DATASET}.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = '{TABLE}' AND column_name = '{COLUMN}'
    """
    return any(get_client().query(sql).result())


def run(dry_run: bool = False) -> None:
    from core.bq.client import get_client

    alter = (
        f"ALTER TABLE `{PROJECT}.{DATASET}.{TABLE}` "
        f"ADD COLUMN {COLUMN} STRING "
        f'OPTIONS(description="Soggetto giuridico (EntityId): INTUR|ORTI|VIGNA|STEFANO_PERSONALE. '
        f'Fonte: registry della sorgente (I-PEC-2)")'
    )
    backfill = (
        f"UPDATE `{PROJECT}.{DATASET}.{TABLE}` "
        f"SET {COLUMN} = societa_id WHERE {COLUMN} IS NULL AND societa_id IS NOT NULL"
    )
    if dry_run:
        log.info("[DRY RUN] %s ; %s", alter, backfill)
        return
    client = get_client()
    if column_exists():
        log.info("Colonna già presente — salto ALTER.")
    else:
        client.query(alter).result()
        log.info("ALTER ok: %s.%s", TABLE, COLUMN)
    job = client.query(backfill)
    job.result()
    log.info("Backfill ok: %s righe", job.num_dml_affected_rows)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
