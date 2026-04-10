"""Tests for ReviewRow schema validation."""

import pytest
from core.schemas import ReviewRow, validate_batch, SchemaViolationError


def _valid_row(**overrides) -> dict:
    base = {
        "review_hash": "abc123def456",
        "piattaforma": "BOOKING",
        "review_id": "rev_12345",
        "societa_id": "ORTI",
        "business_unit_id": "HOTEL",
        "punteggio_raw": 4.0,
        "punteggio_norm": 4.0,
        "testo": "Camera sporca, bagno con muffa.",
        "testo_positivo": None,
        "testo_negativo": "Camera sporca",
        "titolo": "Deludente",
        "lingua": "IT",
        "data_review": "2026-04-01",
        "data_soggiorno": "2026-03-28",
        "reviewer_nome": "Mario R.",
        "reviewer_paese": "IT",
        "tipo_viaggio": "COPPIA",
        "camera_tipo": "Doppia Standard",
        "url_review": "https://www.booking.com/review/123",
        "categoria_nlp": "PULIZIA",
        "sentiment_nlp": "NEGATIVO",
        "riassunto_nlp": "Camera sporca e bagno con muffa al check-in.",
        "alert_inviato": False,
        "data_ingest": "2026-04-01T10:00:00Z",
    }
    base.update(overrides)
    return base


class TestReviewRow:
    def test_valid_row(self):
        row = _valid_row()
        model = ReviewRow(**row)
        assert model.piattaforma == "BOOKING"
        assert model.punteggio_norm == 4.0

    def test_invalid_piattaforma(self):
        with pytest.raises(ValueError):
            ReviewRow(**_valid_row(piattaforma="YELP"))

    def test_punteggio_norm_range(self):
        with pytest.raises(ValueError):
            ReviewRow(**_valid_row(punteggio_norm=11.0))
        with pytest.raises(ValueError):
            ReviewRow(**_valid_row(punteggio_norm=0.0))

    def test_invalid_societa(self):
        with pytest.raises(ValueError):
            ReviewRow(**_valid_row(societa_id="ACME"))

    def test_invalid_categoria_nlp(self):
        with pytest.raises(ValueError):
            ReviewRow(**_valid_row(categoria_nlp="METEO"))

    def test_invalid_sentiment_nlp(self):
        with pytest.raises(ValueError):
            ReviewRow(**_valid_row(sentiment_nlp="FURIOSO"))

    def test_optional_fields_none(self):
        row = _valid_row(
            testo_positivo=None,
            testo_negativo=None,
            titolo=None,
            data_soggiorno=None,
            reviewer_nome=None,
            reviewer_paese=None,
            tipo_viaggio=None,
            camera_tipo=None,
            url_review=None,
            categoria_nlp=None,
            sentiment_nlp=None,
            riassunto_nlp=None,
        )
        model = ReviewRow(**row)
        assert model.testo_positivo is None

    def test_review_hash_not_empty(self):
        with pytest.raises(ValueError):
            ReviewRow(**_valid_row(review_hash=""))

    def test_testo_accepts_empty(self):
        # Star-only reviews (Google/Booking) have no text; schema allows empty.
        # Changed 2026-04-09 — see docs/procedures/reviews_pipeline.md.
        model = ReviewRow(**_valid_row(testo=""))
        assert model.testo == ""

    def test_validate_batch_ok(self):
        rows = [_valid_row(), _valid_row(review_hash="xyz789")]
        result = validate_batch(rows, ReviewRow, context="test reviews")
        assert len(result) == 2

    def test_validate_batch_fail(self):
        rows = [_valid_row(), _valid_row(piattaforma="YELP")]
        with pytest.raises(SchemaViolationError):
            validate_batch(rows, ReviewRow, context="test reviews")
