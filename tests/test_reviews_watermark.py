"""Tests for watermark-based review filtering."""

from unittest.mock import MagicMock, patch

import pytest

from reviews.ingest import filter_by_watermark


@pytest.fixture(autouse=True)
def _reset_bq_client_singleton():
    """Clear the cached BQ client so each test's patch is honoured."""
    import core.bq.client as bq_client_mod

    bq_client_mod._client = None
    yield
    bq_client_mod._client = None


def _item(piattaforma, bu, data_review, review_id="x"):
    return {
        "piattaforma": piattaforma,
        "business_unit_id": bu,
        "data_review": data_review,
        "review_id": review_id,
        "punteggio_norm": 8.0,
    }


def test_filter_empty_watermark_keeps_all():
    items = [
        _item("BOOKING", "HOTEL", "2026-04-05", "a"),
        _item("BOOKING", "HOTEL", "2026-03-01", "b"),
    ]
    kept, gap_keys = filter_by_watermark({}, items, cap=15)
    assert len(kept) == 2
    assert gap_keys == []


def test_filter_drops_items_at_or_before_watermark():
    watermarks = {("BOOKING", "HOTEL"): "2026-04-01"}
    items = [
        _item("BOOKING", "HOTEL", "2026-04-05", "new"),
        _item("BOOKING", "HOTEL", "2026-04-01", "boundary"),  # equal → drop
        _item("BOOKING", "HOTEL", "2026-03-15", "old"),
    ]
    kept, _ = filter_by_watermark(watermarks, items, cap=15)
    assert [k["review_id"] for k in kept] == ["new"]


def test_filter_unknown_key_keeps_all_for_that_key():
    watermarks = {("BOOKING", "HOTEL"): "2026-04-01"}
    items = [
        _item("GOOGLE", "HOTEL", "2024-01-01", "g1"),  # no watermark for GOOGLE
    ]
    kept, _ = filter_by_watermark(watermarks, items, cap=15)
    assert len(kept) == 1


def test_filter_drops_malformed_date():
    items = [
        _item("BOOKING", "HOTEL", "2026-04-05T12:00Z", "bad"),
        _item("BOOKING", "HOTEL", "", "empty"),
        _item("BOOKING", "HOTEL", "2026-04-05", "good"),
    ]
    kept, _ = filter_by_watermark({}, items, cap=15)
    assert [k["review_id"] for k in kept] == ["good"]


def test_filter_gap_detection_when_all_items_new():
    watermarks = {("BOOKING", "HOTEL"): "2026-03-01"}
    items = [
        _item("BOOKING", "HOTEL", f"2026-04-{i:02d}", str(i)) for i in range(1, 16)
    ]
    assert len(items) == 15
    kept, gap_keys = filter_by_watermark(watermarks, items, cap=15)
    assert len(kept) == 15
    assert gap_keys == [("BOOKING", "HOTEL")]


def test_filter_no_gap_when_below_cap():
    watermarks = {("BOOKING", "HOTEL"): "2026-03-01"}
    items = [
        _item("BOOKING", "HOTEL", f"2026-04-{i:02d}", str(i)) for i in range(1, 15)
    ]
    assert len(items) == 14
    kept, gap_keys = filter_by_watermark(watermarks, items, cap=15)
    assert len(kept) == 14
    assert gap_keys == []


def test_filter_multiple_keys_independent_gap():
    watermarks = {
        ("BOOKING", "HOTEL"): "2026-03-01",
        ("GOOGLE", "HOTEL"): "2026-03-01",
    }
    items = [
        _item("BOOKING", "HOTEL", f"2026-04-{i:02d}", f"b{i}") for i in range(1, 16)
    ] + [_item("GOOGLE", "HOTEL", "2026-04-05", "g1")]
    kept, gap_keys = filter_by_watermark(watermarks, items, cap=15)
    assert len(kept) == 16
    assert gap_keys == [("BOOKING", "HOTEL")]


def test_read_watermarks_returns_dict(monkeypatch):
    fake_client = MagicMock()

    # First query: watermarks
    watermark_rows = [
        MagicMock(
            piattaforma="BOOKING", business_unit_id="HOTEL", watermark="2026-04-06"
        ),
        MagicMock(
            piattaforma="GOOGLE", business_unit_id="HOTEL", watermark="2026-03-03"
        ),
    ]
    # Second query: malformed count
    malformed_rows = [
        MagicMock(piattaforma="GOOGLE", n_malformed=42),
    ]

    fake_client.query.side_effect = [
        MagicMock(result=MagicMock(return_value=iter(watermark_rows))),
        MagicMock(result=MagicMock(return_value=iter(malformed_rows))),
    ]

    with patch("google.cloud.bigquery.Client", return_value=fake_client):
        from reviews.ingest import read_watermarks

        result = read_watermarks()

    assert result == {
        ("BOOKING", "HOTEL"): "2026-04-06",
        ("GOOGLE", "HOTEL"): "2026-03-03",
    }
    # Two queries issued: watermark + malformed audit
    assert fake_client.query.call_count == 2


def test_read_watermarks_empty(monkeypatch):
    fake_client = MagicMock()
    fake_client.query.side_effect = [
        MagicMock(result=MagicMock(return_value=iter([]))),
        MagicMock(result=MagicMock(return_value=iter([]))),
    ]
    with patch("google.cloud.bigquery.Client", return_value=fake_client):
        from reviews.ingest import read_watermarks

        assert read_watermarks() == {}


def test_regression_old_negative_review_blocked_by_watermark():
    """
    Bug 2026-04-10: alert.py sent mail for a Zuzana review from Jul 2025
    because alert_inviato was never persisted. With the watermark gate,
    an old negative review already in f_reviews (reflected in the
    watermark) must NOT be re-alerted — it's dropped at the filter
    stage, never reaches classify/load/alert.
    """
    # watermark says "we've seen up to 2026-04-06 on BOOKING/HOTEL"
    watermarks = {("BOOKING", "HOTEL"): "2026-04-06"}

    # actor re-returns an old negative review (pre-watermark)
    items = [
        {
            "piattaforma": "BOOKING",
            "business_unit_id": "HOTEL",
            "data_review": "2025-07-15",
            "review_id": "zuzana",
            "punteggio_norm": 4.0,
        }
    ]

    kept, gap_keys = filter_by_watermark(watermarks, items, cap=15)
    assert kept == []  # blocked — no alert possible downstream
    assert gap_keys == []  # not a gap either, just stale
