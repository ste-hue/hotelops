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


@pytest.mark.bq
def test_recognized_fonte_set(bq_client):
    """T2: Every fonte in f_budget_mensile must be in RECOGNIZED_FONTI.

    This protects against silent rank-NULL fallthrough. If this fails, a new
    fonte was added without updating the precedence rule.
    """
    sql = """
    SELECT DISTINCT fonte
    FROM `hotelops-suite.hotelops.f_budget_mensile`
    """
    found = {r["fonte"] for r in bq_client.query(sql).result()}
    unknown = found - RECOGNIZED_FONTI
    assert not unknown, (
        f"Unrecognized fonti in f_budget_mensile: {unknown}.\n"
        f"To fix:\n"
        f"  1. Decide each fonte's precedence rank.\n"
        f"  2. Add to RECOGNIZED_FONTI in tests/test_budget_canonical.py.\n"
        f"  3. Add to the CASE in core/bq/views/v_budget_canonical.sql.\n"
        f"  4. Redeploy the view.\n"
    )


# Format: (societa, anno, mese, cod_conto, expected_fonte, rationale)
# Expected fonte must be one of RECOGNIZED_FONTI.
KNOWN_WINNERS = [
    ("ORTI", 2026, 1, "670101", "PERSONALE",
     "payroll — PERSONALE > INCIDENZA > GASPAROTTO"),
    ("ORTI", 2026, 1, "651101", "STRUTTURALI",
     "fitto ORTI→INTUR — STRUTTURALI > GASPAROTTO"),
    ("ORTI", 2026, 1, "479101", "CONS2025_IP",
     "oneri 47 — CONS2025_IP > GASPAROTTO"),
    ("ORTI", 2026, 1, "57091301", "MAPPATURA",
     "MAPPATURA wins via exact-code precedence"),
]


@pytest.mark.bq
@pytest.mark.parametrize(
    "societa,anno,mese,cod_conto,expected_fonte,rationale", KNOWN_WINNERS
)
def test_deterministic_winner(
    bq_client, societa, anno, mese, cod_conto, expected_fonte, rationale,
):
    """T3: Known overlapping accounts resolve to the expected fonte."""
    from google.cloud.bigquery import ScalarQueryParameter, QueryJobConfig

    sql = """
    SELECT fonte
    FROM `hotelops-suite.hotelops.v_budget_canonical`
    WHERE societa_id = @s AND anno = @a AND mese = @m AND cod_conto = @c
    """
    job_config = QueryJobConfig(query_parameters=[
        ScalarQueryParameter("s", "STRING", societa),
        ScalarQueryParameter("a", "INT64", anno),
        ScalarQueryParameter("m", "INT64", mese),
        ScalarQueryParameter("c", "STRING", cod_conto),
    ])
    rows = list(bq_client.query(sql, job_config=job_config).result())
    assert len(rows) == 1, (
        f"Expected exactly 1 row for ({societa}, {anno}, {mese}, {cod_conto}), "
        f"got {len(rows)}"
    )
    assert rows[0]["fonte"] == expected_fonte, (
        f"For ({societa}, {anno}, {mese}, {cod_conto}): "
        f"expected fonte={expected_fonte} ({rationale}), got {rows[0]['fonte']}"
    )


@pytest.mark.bq
def test_category_level_suppression_drops_gasparotto_siblings(bq_client):
    """T3 (variant): A GASPAROTTO sibling code in 'Costo del Personale' must
    be suppressed by PERSONALE/INCIDENZA category-level coverage, even when
    PERSONALE has no row at the exact cod_conto.

    cod_conto 670111 is a GASPAROTTO row in 'Costo del Personale' that was
    correctly category-suppressed (n_in_canonical = 0 verified during plan exec).
    """
    suppressed_cod_conto = "670111"

    from google.cloud.bigquery import ScalarQueryParameter, QueryJobConfig

    sql = """
    SELECT COUNT(*) AS n
    FROM `hotelops-suite.hotelops.v_budget_canonical`
    WHERE cod_conto = @c AND fonte = 'GASPAROTTO' AND anno = 2026
    """
    job_config = QueryJobConfig(query_parameters=[
        ScalarQueryParameter("c", "STRING", suppressed_cod_conto),
    ])
    n = next(bq_client.query(sql, job_config=job_config).result())["n"]
    assert n == 0, (
        f"GASPAROTTO row for {suppressed_cod_conto} should be suppressed by "
        f"category-level rule (PERSONALE/INCIDENZA covers 'Costo del Personale'), "
        f"but {n} GASPAROTTO rows survived."
    )


@pytest.mark.bq
def test_canonical_never_expands_raw(bq_client):
    """T4: Canonical row count ≤ raw row count at the (societa, anno, mese)
    scope. Dedup must reduce or preserve, never invent.
    """
    sql = """
    WITH raw AS (
      SELECT societa_id, anno, mese, COUNT(*) AS n_raw
      FROM `hotelops-suite.hotelops.f_budget_mensile`
      GROUP BY societa_id, anno, mese
    ),
    canon AS (
      SELECT societa_id, anno, mese, COUNT(*) AS n_canon
      FROM `hotelops-suite.hotelops.v_budget_canonical`
      GROUP BY societa_id, anno, mese
    )
    SELECT
      r.societa_id, r.anno, r.mese, r.n_raw, COALESCE(c.n_canon, 0) AS n_canon
    FROM raw r
    LEFT JOIN canon c USING (societa_id, anno, mese)
    WHERE COALESCE(c.n_canon, 0) > r.n_raw
    LIMIT 10
    """
    rows = list(bq_client.query(sql).result())
    assert not rows, (
        f"Dedup expanded rows in {len(rows)} (societa, anno, mese) scopes. "
        f"First: {dict(rows[0]) if rows else 'n/a'}"
    )
