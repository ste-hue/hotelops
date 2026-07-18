"""One-shot: ALTER f_pec_messages ALTER societa_id DROP NOT NULL.

Le entity non contabili (VIGNA, STEFANO_PERSONALE) hanno societa_id NULL by
design (I-PEC-2: entity_id è la chiave, societa_id solo per ORTI/INTUR).
La colonna era REQUIRED dal DDL originale mono-casella: il load job rifiutava
le righe NULL → VALIDATE_FAIL su tutti i promote PERSONALE/VIGNA (2026-07-17).

Idempotente: probe INFORMATION_SCHEMA su is_nullable.
Run: python -m core.bq.migrations.2026_07_18_drop_not_null_societa_id_f_pec_messages
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"
TABLE = "f_pec_messages"
COLUMN = "societa_id"


def column_is_nullable() -> bool:
    from core.bq.client import get_client

    sql = f"""
    SELECT is_nullable
    FROM `{PROJECT}.{DATASET}.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = '{TABLE}' AND column_name = '{COLUMN}'
    """
    rows = list(get_client().query(sql).result())
    if not rows:
        raise RuntimeError(f"Colonna {TABLE}.{COLUMN} inesistente")
    return rows[0].is_nullable == "YES"


def run(dry_run: bool = False) -> None:
    from core.bq.client import get_client

    alter = (
        f"ALTER TABLE `{PROJECT}.{DATASET}.{TABLE}` "
        f"ALTER COLUMN {COLUMN} DROP NOT NULL"
    )
    if dry_run:
        log.info("[DRY RUN] %s", alter)
        return
    if column_is_nullable():
        log.info("Colonna già NULLABLE — salto ALTER.")
        return
    get_client().query(alter).result()
    log.info("ALTER ok: %s.%s ora NULLABLE", TABLE, COLUMN)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
