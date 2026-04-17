"""Invariant tests for v_budget_canonical.

These tests query live BigQuery. They are marked @pytest.mark.bq and skipped
when HOTELOPS_SKIP_BQ=1.

The RECOGNIZED_FONTI constant below is the authoritative declaration of which
fonti exist in f_budget_mensile. The SQL CASE in v_budget_canonical.sql must
list exactly these names. Any drift between the two is a bug — caught by
test_recognized_fonte_set.

Spec: docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md
"""

from __future__ import annotations

import pytest


RECOGNIZED_FONTI = {
    "STRUTTURALI",
    "MAPPATURA",
    "PERSONALE",
    "INCIDENZA",
    "CONS2025_F",
    "CONS2025_V",
    "CONS2025_IP",
    "CONS2025_X",
    "GASPAROTTO",
}


@pytest.mark.bq
def test_grain_uniqueness(bq_client):
    """T1: Exactly one row per (societa_id, anno, mese, cod_conto).

    Implicitly also covers 'no duplicate winners': if two rows share a grain,
    ROW_NUMBER produced two rn=1 candidates that the SQL didn't resolve.
    """
    sql = """
    SELECT societa_id, anno, mese, cod_conto, COUNT(*) AS n
    FROM `hotelops-suite.hotelops.v_budget_canonical`
    GROUP BY societa_id, anno, mese, cod_conto
    HAVING n > 1
    LIMIT 10
    """
    rows = list(bq_client.query(sql).result())
    assert not rows, (
        f"Grain violation in v_budget_canonical: {len(rows)} duplicate keys. "
        f"First: {dict(rows[0]) if rows else 'n/a'}"
    )
