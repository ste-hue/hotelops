#!/usr/bin/env python3
"""DDL idempotente per le 3 tabelle canonical del vertical spiaggia.

f_spiaggia_reservations / f_spiaggia_cash_flows / f_spiaggia_spots.
Lifecycle SNAPSHOT full-replace (natural_key societa_id) — gestito dal parser
ingest.flussi.ingest_spiaggia.

Usage:
    python -m core.bq.load.create_spiaggia_tables
    python -m core.bq.load.create_spiaggia_tables --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys

from core.bq.client import get_client
from core.config import (
    F_SPIAGGIA_CASH_FLOWS,
    F_SPIAGGIA_RESERVATIONS,
    F_SPIAGGIA_SPOTS,
)

DDL_RESERVATIONS = f"""
CREATE TABLE IF NOT EXISTS `{F_SPIAGGIA_RESERVATIONS}` (
    societa_id           STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    location_id          STRING,
    oggetto_id           STRING,
    funzione_id          STRING,
    id                   INT64 NOT NULL,
    license_code         STRING,
    spot_type            STRING,
    spot_name            STRING,
    status               INT64,
    seasonal             BOOL,
    deleted              BOOL,
    online               BOOL,
    hotel                STRING,
    hotel_room           STRING,
    start_date           DATE,
    end_date             DATE,
    beds                 INT64,
    chairs               INT64,
    first_name           STRING,
    last_name            STRING,
    email                STRING,
    phone                STRING,
    list_total           FLOAT64,
    paid_total           FLOAT64,
    gross_booking_value  FLOAT64,
    discount             FLOAT64,
    channel              STRING,
    invoice_number       STRING,
    invoice_company      STRING,
    utm_source           STRING,
    utm_medium           STRING,
    utm_campaign         STRING,
    created_at           TIMESTAMP,
    updated_at           TIMESTAMP,
    raw_object_id        STRING,
    file_sorgente        STRING NOT NULL,
    hash_riga            STRING NOT NULL,
    data_caricamento     TIMESTAMP NOT NULL
)
CLUSTER BY spot_name
"""

DDL_CASH_FLOWS = f"""
CREATE TABLE IF NOT EXISTS `{F_SPIAGGIA_CASH_FLOWS}` (
    societa_id           STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    location_id          STRING,
    oggetto_id           STRING,
    funzione_id          STRING,
    id                   INT64 NOT NULL,
    reservation_id       INT64,
    method               INT64,
    method_label         STRING,
    amount               FLOAT64,
    date                 DATE,
    receipt_id           INT64,
    invoice_id           INT64,
    deleted              BOOL,
    created_at           TIMESTAMP,
    updated_at           TIMESTAMP,
    raw_object_id        STRING,
    file_sorgente        STRING NOT NULL,
    hash_riga            STRING NOT NULL,
    data_caricamento     TIMESTAMP NOT NULL
)
CLUSTER BY reservation_id
"""

DDL_SPOTS = f"""
CREATE TABLE IF NOT EXISTS `{F_SPIAGGIA_SPOTS}` (
    societa_id           STRING NOT NULL,
    business_unit_id     STRING NOT NULL,
    location_id          STRING,
    oggetto_id           STRING,
    funzione_id          STRING,
    id                   INT64 NOT NULL,
    uuid                 STRING,
    name                 STRING,
    type                 STRING,
    sector               INT64,
    price_list_id        INT64,
    pos_x                INT64,
    pos_y                INT64,
    element_type         STRING,
    raw_object_id        STRING,
    file_sorgente        STRING NOT NULL,
    hash_riga            STRING NOT NULL,
    data_caricamento     TIMESTAMP NOT NULL
)
"""

ALL_DDL = {
    "f_spiaggia_reservations": DDL_RESERVATIONS,
    "f_spiaggia_cash_flows": DDL_CASH_FLOWS,
    "f_spiaggia_spots": DDL_SPOTS,
}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Print DDL without executing")
    args = p.parse_args()

    log = logging.getLogger("create_spiaggia_tables")
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
