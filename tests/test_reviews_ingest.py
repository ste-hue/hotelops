"""Tests for reviews ingest: normalization and dedup."""

from verticals.reviews.ingest import (
    normalize_booking,
    normalize_tripadvisor,
    normalize_google,
    normalize_expedia,
    normalize_trip,
    _extract_trip_hotel_id,
    dedup_reviews,
)
from core.schemas import ReviewRow


def test_normalize_booking():
    raw = {
        "_bu": "HOTEL",
        "_piattaforma": "BOOKING",
        "id": "2bf0bec7bcb96138",
        "rating": 4.2,
        "reviewTitle": "Deludente",
        "likedText": "Posizione bella",
        "dislikedText": "Camera sporca",
        "reviewDate": "2026-04-01T10:00:00.000Z",
        "checkInDate": "2026-03-28",
        "userName": "Mario",
        "userLocation": "Italy",
        "travelerType": "Couple",
        "roomInfo": "Double Room",
        "reviewLanguage": "it",
    }
    row = normalize_booking(raw, societa="ORTI")
    assert row["piattaforma"] == "BOOKING"
    assert row["punteggio_raw"] == 4.2
    assert row["punteggio_norm"] == 4.2  # Booking already 1-10
    assert row["business_unit_id"] == "HOTEL"
    assert row["testo"] == "Posizione bella Camera sporca"
    assert row["testo_positivo"] == "Posizione bella"
    assert row["data_review"] == "2026-04-01"
    # Booking non espone per-review URL: fallback sulla pagina hotel da config.
    assert row["url_review"] is not None
    assert "booking.com" in row["url_review"]
    assert row["url_review"].endswith("#tab-reviews")
    ReviewRow(**row)


def test_normalize_tripadvisor():
    raw = {
        "_bu": "HOTEL",
        "_piattaforma": "TRIPADVISOR",
        "id": "ta_001",
        "rating": 3,
        "title": "Nella media",
        "text": "Niente di speciale.",
        "publishedDate": "2026-04-01T10:00:00-04:00",
        "travelDate": "2026-03",
        "user": {"username": "Luigi", "userLocation": {"name": "Roma, Italia"}},
        "tripType": "Family",
        "lang": "it",
        "url": "https://tripadvisor.com/review/001",
    }
    row = normalize_tripadvisor(raw, societa="ORTI")
    assert row["punteggio_raw"] == 3.0
    assert row["punteggio_norm"] == 6.0  # 3/5 * 2 = 6
    ReviewRow(**row)


def test_normalize_google():
    raw = {
        "_bu": "HOTEL",
        "_piattaforma": "GOOGLE",
        "reviewId": "g_001",
        "stars": 2,
        "text": "Pessimo.",
        "publishedAtDate": "2026-04-01",
        "name": "Anna",
        "language": "it",
        "reviewUrl": "https://maps.google.com/review/001",
    }
    row = normalize_google(raw, societa="ORTI")
    assert row["punteggio_raw"] == 2.0
    assert row["punteggio_norm"] == 4.0  # 2/5 * 2 = 4
    ReviewRow(**row)


def test_normalize_expedia():
    raw = {
        "_bu": "HOTEL",
        "_piattaforma": "EXPEDIA",
        "reviewId": "68ee4a4308d40f1bac48499a",
        "reviewRating": 7.5,
        "reviewTitle": "Buono",
        "reviewText": "Buon soggiorno.",
        "reviewDate": "2026-04-01T00:00:00.000Z",
        "stayDate": "2026-03-28T00:00:00.000Z",
        "reviewerName": "Paolo",
        "locale": "it_IT",
        "hotelUrl": "https://www.expedia.com/h68690805",
    }
    row = normalize_expedia(raw, societa="ORTI")
    assert row["punteggio_raw"] == 7.5
    assert row["punteggio_norm"] == 7.5  # Expedia already 1-10
    assert row["lingua"] == "it"
    assert row["data_review"] == "2026-04-01"
    assert row["data_soggiorno"] == "2026-03-28"
    ReviewRow(**row)


def _trip_raw(**overrides) -> dict:
    base = {
        "_bu": "HOTEL",
        "_piattaforma": "TRIP",
        "id": "t_001",
        "rating": 8.5,
        "content": "Ottimo soggiorno, staff gentile.",
        "translatedContent": "Great stay, kind staff.",
        "language": "it",
        "createDate": "2025-10-15 12:34:56",
        "checkInDate": "2025-10-10",
        "roomTypeName": "Camera doppia",
        "travelType": "couple",
        "travelTypeText": "Couple",
        "commentLevel": "Recommended",
        "usefulCount": 2,
    }
    base.update(overrides)
    return base


def test_extract_trip_hotel_id():
    url = "https://www.trip.com/hotels/maiori-hotel-detail-774198/panorama/"
    assert _extract_trip_hotel_id(url) == "774198"
    assert _extract_trip_hotel_id("https://it.trip.com/hotels/maiori-hotel-detail-3094414/angelina-residence/") == "3094414"
    assert _extract_trip_hotel_id(None) == ""
    assert _extract_trip_hotel_id("https://other.site/x") == ""


def test_normalize_trip_italian_uses_content():
    """IT language: use content (original) not translatedContent."""
    row = normalize_trip(_trip_raw(), societa="ORTI")
    assert row["piattaforma"] == "TRIP"
    assert row["punteggio_raw"] == 8.5
    assert row["punteggio_norm"] == 8.5  # already 1-10
    assert row["business_unit_id"] == "HOTEL"
    assert row["testo"] == "Ottimo soggiorno, staff gentile."
    assert row["lingua"] == "it"
    assert row["data_review"] == "2025-10-15"
    assert row["data_soggiorno"] == "2025-10-10"
    assert row["reviewer_nome"] is None
    assert row["camera_tipo"] == "Camera doppia"
    assert row["tipo_viaggio"] == "COPPIA"
    assert row["titolo"] == "Recommended"
    assert "trip.com" in (row["url_review"] or "")
    ReviewRow(**row)


def test_normalize_trip_non_latin_falls_back_to_translation():
    """Chinese review: content is CJK, fall back to translatedContent."""
    row = normalize_trip(_trip_raw(language="zh", content="很好的酒店", translatedContent="Great hotel"))
    assert row["testo"] == "Great hotel"
    assert row["lingua"] == "zh"


def test_normalize_trip_english_uses_content():
    """EN language: prefer original content over translation."""
    row = normalize_trip(_trip_raw(language="en", content="Lovely place", translatedContent="Posto delizioso"))
    assert row["testo"] == "Lovely place"


def test_normalize_trip_no_translation_keeps_content():
    """Non-IT/EN language, no translation available: keep the original."""
    row = normalize_trip(_trip_raw(language="zh", content="很好", translatedContent=""))
    assert row["testo"] == "很好"


def test_normalize_trip_review_hash_stable():
    """Same hotel_id + review_id → same hash across runs."""
    row1 = normalize_trip(_trip_raw())
    row2 = normalize_trip(_trip_raw())
    assert row1["review_hash"] == row2["review_hash"]


def test_normalize_trip_review_hash_isolated_from_other_hotels():
    """Same review_id across different hotels must produce different hashes."""
    hotel_row = normalize_trip(_trip_raw(_bu="HOTEL"))
    residence_row = normalize_trip(_trip_raw(_bu="RESIDENCE"))
    assert hotel_row["review_hash"] != residence_row["review_hash"]


def test_normalize_trip_score_passthrough():
    """Trip.com rating is already on 1-10 scale (ratingMax=10), no rescale."""
    row = normalize_trip(_trip_raw(rating=5.0))
    assert row["punteggio_raw"] == 5.0
    assert row["punteggio_norm"] == 5.0


def test_normalize_trip_travel_type_mapping():
    """travelTypeText maps through the same _TRIP_TYPE_MAP as other platforms."""
    row = normalize_trip(_trip_raw(travelTypeText="Family", travelType="family"))
    assert row["tipo_viaggio"] == "FAMIGLIA"


def test_dedup_reviews():
    rows = [
        {"review_hash": "aaa", "piattaforma": "BOOKING", "testo": "one"},
        {"review_hash": "aaa", "piattaforma": "BOOKING", "testo": "one dupe"},
        {"review_hash": "bbb", "piattaforma": "GOOGLE", "testo": "two"},
    ]
    result = dedup_reviews(rows)
    assert len(result) == 2
    hashes = {r["review_hash"] for r in result}
    assert hashes == {"aaa", "bbb"}
