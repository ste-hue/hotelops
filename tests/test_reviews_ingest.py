"""Tests for reviews ingest: normalization and dedup."""

from reviews.ingest import (
    normalize_booking,
    normalize_tripadvisor,
    normalize_google,
    normalize_expedia,
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
