"""Minimal reader for datahub CSV fact tables."""

import csv
from pathlib import Path


def read_facts(
    fact_path: Path,
    filters: dict[str, str] | None = None,
) -> list[dict]:
    """Read a CSV fact table, optionally filtering rows by exact column match."""
    if not fact_path.exists():
        raise FileNotFoundError(f"Fact table not found: {fact_path}")

    rows = []
    with open(fact_path, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if filters and not all(row.get(k) == v for k, v in filters.items()):
                continue
            rows.append(row)
    return rows
