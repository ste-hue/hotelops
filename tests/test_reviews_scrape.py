"""Tests for Apify actor input builder.

Validates that _build_input emits parameters that match each actor's
actual input schema. The schema source of truth is `reviews.inspect_actors`
run against the live Apify API (snapshot taken 2026-04-10, see ADR 0003
follow-up).
"""

from reviews.scrape import MAX_REVIEWS_PER_PROPERTY, _build_input


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


def test_google_unchanged():
    """compass/Google-Maps-Reviews-Scraper: maxReviews + reviewsSort both
    valid per live schema. Regression guard — don't accidentally break it."""
    inp = _build_input("GOOGLE", "HOTEL", "https://example.com/google")
    assert inp["maxReviews"] == MAX_REVIEWS_PER_PROPERTY
    assert inp["reviewsSort"] == "newest"
    assert inp["startUrls"] == [{"url": "https://example.com/google"}]


def test_unknown_platform_raises():
    import pytest
    with pytest.raises(ValueError, match="Unknown piattaforma"):
        _build_input("YELP", "HOTEL", "https://example.com/yelp")
