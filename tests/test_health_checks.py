"""Tests for watermark + pipeline staleness checks."""

from unittest.mock import MagicMock, patch

import pytest


class FakeBQRow(dict):
    """Minimal stand-in for google.cloud.bigquery.Row.

    Real BQ Row instances are dict-convertible via `dict(row)`; a plain
    dict subclass gives us the same semantics without pulling in the SDK.
    """

    pass


def _fake_query_client(rows: list[dict]) -> MagicMock:
    fake = MagicMock()
    fake.query.return_value.result.return_value = iter([FakeBQRow(r) for r in rows])
    return fake


@pytest.fixture(autouse=True)
def _reset_bq_client_singleton():
    """Clear the cached BQ client so each test's patch is honoured."""
    import core.bq.client as bq_client_mod

    bq_client_mod._client = None
    yield
    bq_client_mod._client = None


def test_check_watermark_staleness_returns_stale_keys():
    """Given a BQ client that yields one stale row, return one dict
    with piattaforma + days_stale populated."""
    from core.pipeline_run import check_watermark_staleness

    fake_client = _fake_query_client(
        [
            {
                "piattaforma": "GOOGLE",
                "business_unit_id": "HOTEL",
                "watermark": "2026-03-03",
                "days_stale": 39,
            }
        ]
    )

    with patch("google.cloud.bigquery.Client", return_value=fake_client):
        result = check_watermark_staleness(threshold_days=21)

    assert len(result) == 1
    assert result[0]["piattaforma"] == "GOOGLE"
    assert result[0]["business_unit_id"] == "HOTEL"
    assert result[0]["days_stale"] == 39
    assert result[0]["watermark"] == "2026-03-03"


def test_check_watermark_staleness_empty_when_fresh():
    from core.pipeline_run import check_watermark_staleness

    fake_client = _fake_query_client([])
    with patch("google.cloud.bigquery.Client", return_value=fake_client):
        result = check_watermark_staleness(threshold_days=21)
    assert result == []


def test_check_pipeline_staleness_returns_stale_pipelines():
    from core.pipeline_run import check_pipeline_staleness

    fake_client = _fake_query_client(
        [
            {
                "pipeline_name": "reviews_scrape",
                "last_ok": "2026-04-08T06:00:00Z",
                "hours_since": 52,
            }
        ]
    )
    with patch("google.cloud.bigquery.Client", return_value=fake_client):
        result = check_pipeline_staleness(threshold_hours=36)

    assert len(result) == 1
    assert result[0]["pipeline_name"] == "reviews_scrape"
    assert result[0]["hours_since"] == 52
