"""v_raw_promotion_status — live BigQuery smoke on schema."""

from __future__ import annotations

import pytest


@pytest.mark.bq
def test_view_returns_expected_columns(bq_client):
    """View exists and exposes contract columns."""
    rows = list(
        bq_client.query(
            "SELECT * FROM `hotelops-suite.hotelops.v_raw_promotion_status` LIMIT 1"
        ).result()
    )
    if not rows:
        pytest.skip("view empty — no row to inspect schema")

    expected_cols = {
        "source_name",
        "status",
        "n_objects",
        "oldest_intake_at",
        "latest_intake_at",
    }
    actual_cols = set(rows[0].keys())
    missing = expected_cols - actual_cols
    assert not missing, f"v_raw_promotion_status missing columns: {missing}"
