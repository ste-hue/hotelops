"""Tests for Apify actor input builder.

Validates that _build_input emits parameters that match each actor's
actual input schema. The schema source of truth is `reviews.inspect_actors`
run against the live Apify API (snapshot taken 2026-04-10, see ADR 0003
follow-up).
"""

import pytest

from verticals.reviews.scrape import MAX_REVIEWS_PER_PROPERTY, _build_input


@pytest.fixture(autouse=True)
def _reset_bq_client_singleton():
    """Clear the cached BQ client so each test's patch is honoured."""
    import core.bq.client as bq_client_mod

    bq_client_mod._client = None
    yield
    bq_client_mod._client = None


def test_booking_uses_sortReviewsBy_not_reviewsSort():
    """voyager/booking-reviews-scraper schema: sortReviewsBy (not reviewsSort)."""
    inp = _build_input("BOOKING", "HOTEL", "https://example.com/hotel")
    assert "sortReviewsBy" in inp
    assert "reviewsSort" not in inp
    assert inp["maxReviewsPerHotel"] == MAX_REVIEWS_PER_PROPERTY
    assert inp["startUrls"] == [{"url": "https://example.com/hotel"}]


def test_tripadvisor_uses_maxItemsPerQuery_not_maxItems():
    """maxcopell/tripadvisor-reviews schema: maxItemsPerQuery (not maxItems)."""
    inp = _build_input("TRIPADVISOR", "HOTEL", "https://example.com/ta")
    assert inp["maxItemsPerQuery"] == MAX_REVIEWS_PER_PROPERTY
    assert "maxItems" not in inp


def test_tripadvisor_omits_language_field():
    """Old `language: ALL` is invalid; actor expects reviewsLanguages as array.
    For "all languages" behavior, omit the field entirely (actor default)."""
    inp = _build_input("TRIPADVISOR", "HOTEL", "https://example.com/ta")
    assert "language" not in inp
    # reviewsLanguages is the correct name IF we want to filter; omission = all
    assert "reviewsLanguages" not in inp


def test_expedia_uses_maxItems_only():
    """memo23/expedia-scraper schema: maxItems (no maxReviewsPerHotel,
    no maxReviews). This is the P0 fix — 226-item blowout on 2026-04-10."""
    inp = _build_input("EXPEDIA", "HOTEL", "https://example.com/expedia")
    assert inp["maxItems"] == MAX_REVIEWS_PER_PROPERTY
    assert "maxReviewsPerHotel" not in inp
    assert "maxReviews" not in inp


def test_expedia_startUrls_plain_strings():
    """memo23/expedia-scraper rebuilt 2026-05-17: startUrls editor changed to
    stringList — wants plain string URLs, not [{"url": ...}] objects. Old
    object form crashed the actor ("Provide at least one start URL")."""
    inp = _build_input("EXPEDIA", "HOTEL", "https://example.com/expedia")
    assert inp["startUrls"] == ["https://example.com/expedia"]


def test_google_unchanged():
    """compass/Google-Maps-Reviews-Scraper: maxReviews + reviewsSort both
    valid per live schema. Regression guard — don't accidentally break it."""
    inp = _build_input("GOOGLE", "HOTEL", "https://example.com/google")
    assert inp["maxReviews"] == MAX_REVIEWS_PER_PROPERTY
    assert inp["reviewsSort"] == "newest"
    assert inp["startUrls"] == [{"url": "https://example.com/google"}]


def test_trip_uses_hotelUrl_not_startUrls():
    """knagymate/trip-com-reviews-scraper schema: hotelUrl (string), maxReviews.
    Passing startUrls/totalLimit causes the actor to silently fall back to its
    schema defaults (Grand Hyatt Shanghai, 1000 reviews) — regression guard
    for the 2026-04-11 $3.38 exploration blowout."""
    inp = _build_input(
        "TRIP",
        "HOTEL",
        "https://www.trip.com/hotels/maiori-hotel-detail-774198/panorama/",
    )
    assert (
        inp["hotelUrl"]
        == "https://www.trip.com/hotels/maiori-hotel-detail-774198/panorama/"
    )
    assert inp["maxReviews"] == MAX_REVIEWS_PER_PROPERTY
    assert "startUrls" not in inp
    assert "totalLimit" not in inp


def test_unknown_platform_raises():
    import pytest

    with pytest.raises(ValueError, match="Unknown piattaforma"):
        _build_input("YELP", "HOTEL", "https://example.com/yelp")


def test_persist_apify_run_validates_and_inserts():
    """persist_apify_run should validate via schema and call insert_rows_json."""
    from unittest.mock import MagicMock, patch
    from verticals.reviews.scrape import persist_apify_run

    fake_client = MagicMock()
    fake_client.insert_rows_json.return_value = []

    with patch("google.cloud.bigquery.Client", return_value=fake_client):
        persist_apify_run(
            run_id="abc123",
            piattaforma="BOOKING",
            business_unit_id="HOTEL",
            actor_id="voyager/booking-reviews-scraper",
            n_items=15,
            cost_usd=0.075,
            cap_violated=False,
        )

    assert fake_client.insert_rows_json.called
    args = fake_client.insert_rows_json.call_args
    inserted_rows = args.args[1]
    assert len(inserted_rows) == 1
    row = inserted_rows[0]
    assert row["run_id"] == "abc123"
    assert row["piattaforma"] == "BOOKING"
    assert row["n_items"] == 15
    assert row["cost_usd"] == 0.075
    assert row["cap_violated"] is False
    assert "ts_run" in row


def test_persist_apify_run_accepts_none_cost():
    """cost_usd=None is valid (Apify doesn't always return usageTotalUsd)."""
    from unittest.mock import MagicMock, patch
    from verticals.reviews.scrape import persist_apify_run

    fake_client = MagicMock()
    fake_client.insert_rows_json.return_value = []

    with patch("google.cloud.bigquery.Client", return_value=fake_client):
        persist_apify_run(
            run_id="xyz",
            piattaforma="GOOGLE",
            business_unit_id="HOTEL",
            actor_id="compass/Google-Maps-Reviews-Scraper",
            n_items=0,
            cost_usd=None,
            cap_violated=False,
        )

    row = fake_client.insert_rows_json.call_args.args[1][0]
    assert row["cost_usd"] is None


def test_persist_apify_run_swallows_bq_errors():
    """BQ failures must never raise — costs are observability, not blocker."""
    from unittest.mock import MagicMock, patch
    from verticals.reviews.scrape import persist_apify_run

    fake_client = MagicMock()
    fake_client.insert_rows_json.side_effect = RuntimeError("BQ down")

    # Must NOT raise
    with patch("google.cloud.bigquery.Client", return_value=fake_client):
        persist_apify_run(
            run_id="r1",
            piattaforma="BOOKING",
            business_unit_id="HOTEL",
            actor_id="voyager/booking-reviews-scraper",
            n_items=5,
            cost_usd=0.025,
            cap_violated=False,
        )
