"""DDL loader for the lineage tables.

Idempotent: CREATE TABLE IF NOT EXISTS for facts, CREATE OR REPLACE VIEW for the view.

Spec: §3.3, §4.2, §4.3, §4.4
"""

from __future__ import annotations

import logging
from pathlib import Path

from core.bq.client import get_client

log = logging.getLogger(__name__)

PROJECT = "hotelops-suite"
DATASET = "hotelops"

DDL_FACT_RAW_OBJECTS = f"""
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.f_raw_objects` (
  raw_object_id        STRING NOT NULL,
  content_hash         STRING NOT NULL,
  raw_uri              STRING NOT NULL,
  raw_backend          STRING NOT NULL,
  file_name_original   STRING NOT NULL,
  file_name_canonical  STRING,
  bytes_size           INT64 NOT NULL,
  source_name          STRING,
  detector_category    STRING,
  societa_id           STRING,
  business_unit_id     STRING,
  banca_id             STRING,
  intake_at            TIMESTAMP NOT NULL,
  intake_actor         STRING NOT NULL,
  pipeline_run_id      STRING,
  pipeline_name        STRING,
  file_sorgente        STRING,
  ingestion_ts         TIMESTAMP NOT NULL
)
PARTITION BY DATE(intake_at)
CLUSTER BY content_hash, source_name
"""

DDL_FACT_LINEAGE_EVENTS = f"""
CREATE TABLE IF NOT EXISTS `{PROJECT}.{DATASET}.f_lineage_events` (
  event_id          STRING NOT NULL,
  raw_object_id     STRING NOT NULL,
  event_type        STRING NOT NULL,
  event_at          TIMESTAMP NOT NULL,
  actor             STRING NOT NULL,
  pipeline_run_id   STRING,
  pipeline_name     STRING,
  from_status       STRING,
  to_status         STRING,
  payload_json      STRING,
  reason            STRING
)
PARTITION BY DATE(event_at)
CLUSTER BY raw_object_id, event_type
"""

_VIEW_SQL_PATH = (
    Path(__file__).resolve().parents[1] / "views" / "v_raw_objects_current.sql"
)
SQL_VIEW_RAW_OBJECTS_CURRENT = _VIEW_SQL_PATH.read_text(encoding="utf-8")


def create_lineage_tables(dry_run: bool = False) -> None:
    """Create the 2 fact tables + 1 view. Idempotent."""
    statements = [
        ("f_raw_objects", DDL_FACT_RAW_OBJECTS),
        ("f_lineage_events", DDL_FACT_LINEAGE_EVENTS),
        ("v_raw_objects_current", SQL_VIEW_RAW_OBJECTS_CURRENT),
    ]
    if dry_run:
        for name, sql in statements:
            log.info("[DRY-RUN] would execute DDL for %s", name)
        return
    client = get_client()
    for name, sql in statements:
        log.info("Creating %s ...", name)
        client.query(sql).result()
        log.info("✓ %s ready", name)


def main() -> None:
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    create_lineage_tables(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
