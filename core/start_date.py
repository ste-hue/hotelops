# core/start_date.py
"""Utility to compute the next start date for incremental loads.

Each data source may have a different BigQuery table and a different column
that stores the effective date of the record.  The `START_DATE_MAP`
dictionary maps a logical source name to a tuple of:

    (bigquery_table_fqn, date_column_name, fallback_date)

`fallback_date` is used when the table is empty (no previous loads).

The public function `get_next_start_date(source: str) -> datetime.date`:
- Looks up the mapping for the given source.
- Queries BigQuery for the maximum value of the date column.
- Returns the day after the max date, or the fallback if the table is empty.

This helper is used by the ingest pipelines for HotelCube, RistoCube and
Esolver to decide from which date to start loading new records.
"""

from __future__ import annotations

import datetime
from typing import Dict, Tuple

from core.bq.client import get_client

# Mapping: source -> (table FQN, date column, fallback start date)
# Adjust these entries as new sources are added.
START_DATE_MAP: Dict[str, Tuple[str, str, datetime.date]] = {
    # Existing HotelCube tables (example)
    "hotelcube_accodamenti": (
        "hotelops.f_accodamenti",
        "data_fine",  # column that holds the end date of the record
        datetime.date(2025, 1, 1),
    ),
    "hotelcube_pms": (
        "hotelops.f_pms_statistiche",
        "giorno",
        datetime.date(2025, 1, 1),
    ),
    # New sources – placeholders to be updated with real table/column names.
    "ristocube_sales": (
        "hotelops.f_ristocube_sales",
        "sale_date",
        datetime.date(2025, 1, 1),
    ),
    "esolver_transactions": (
        "hotelops.f_esolver_transactions",
        "transaction_date",
        datetime.date(2025, 1, 1),
    ),
    ,
    "generic": ("hotelops.generic_checkpoint", "timestamp", datetime.datetime(1970, 1, 1)),
}


def get_next_start_date(source: str) -> datetime.date:
    """Return the day after the most recent record for *source*.

    Parameters
    ----------
    source: str
        Logical source identifier, must be present in ``START_DATE_MAP``.

    Returns
    -------
    datetime.date
        The date to use for the next incremental load.
    """
    if source not in START_DATE_MAP:
        raise ValueError(f"Unknown source '{source}'. Available: {list(START_DATE_MAP)}")

    table_fqn, date_col, fallback = START_DATE_MAP[source]
    client = get_client()
    # Use BigQuery standard SQL to fetch the max date.
    query = f"SELECT MAX({date_col}) AS max_date FROM `{table_fqn}`"
    rows = list(client.query(query).result())
    max_date = rows[0].max_date if rows else None
    if max_date is None:
        # No data yet – start from fallback.
        return fallback
    # Ensure we return a pure date (BigQuery may give a datetime).
    if isinstance(max_date, datetime.datetime):
        max_date = max_date.date()
    # Next day after the most recent record.
    return max_date + datetime.timedelta(days=1)


def update_last_processed(source: str, dt: datetime.datetime) -> None:
    """Persist the last processed datetime for a generic source.
    Stores a simple JSON file `.ingest_state.json` at repo root.
    """
    import json
    from pathlib import Path
    state_file = Path(__file__).resolve().parent.parent / ".ingest_state.json"
    # Load existing state
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text())
        except Exception:
            data = {}
    else:
        data = {}
    data[source] = dt.isoformat()
    state_file.write_text(json.dumps(data, indent=2))



def list_available_sources() -> list[str]:
    """Return a list of logical source names known to the utility."""
    return list(START_DATE_MAP.keys())

# When run as a script, behave like a tiny CLI for quick lookup.
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Show next start date for a source")
    parser.add_argument("source", help="Logical source identifier")
    args = parser.parse_args()
    try:
        nxt = get_next_start_date(args.source)
        print(f"Next start date for {args.source}: {nxt.isoformat()}")
    except Exception as e:
        print(f"Error: {e}")
        raise
"""
