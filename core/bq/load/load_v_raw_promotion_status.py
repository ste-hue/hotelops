"""Deploy v_raw_promotion_status from repo SQL."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

SQL_PATH = Path(__file__).resolve().parents[1] / "views" / "v_raw_promotion_status.sql"


def run() -> None:
    from core.bq.client import get_client

    sql = SQL_PATH.read_text(encoding="utf-8")
    client = get_client()
    client.query(sql).result()
    log.info("v_raw_promotion_status materialized.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run()


if __name__ == "__main__":
    main()
