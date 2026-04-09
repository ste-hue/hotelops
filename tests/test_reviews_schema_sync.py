"""Contract test: reviews NLP enums must stay in sync across code + schema.

Context: on 2026-04-07 a rename ALTRO -> GENERICA was done in reviews/classify.py
and in 341 BQ rows, but core/schemas.py was forgotten. The drift silently broke
the cron on 2026-04-09 when a new review arrived with categoria=GENERICA.

This test ensures any future rename touches all three places at once.
"""

from typing import get_args

from core.schemas import CategoriaNlp, SentimentNlp
from reviews.classify import VALID_CATEGORIE, VALID_SENTIMENTI


def test_categoria_nlp_in_sync():
    """VALID_CATEGORIE in classify.py must match CategoriaNlp literal in schemas.py."""
    schema_values = set(get_args(CategoriaNlp))
    assert VALID_CATEGORIE == schema_values, (
        f"Drift detected!\n"
        f"  reviews/classify.py VALID_CATEGORIE: {sorted(VALID_CATEGORIE)}\n"
        f"  core/schemas.py    CategoriaNlp:    {sorted(schema_values)}\n"
        f"  only in classify.py: {VALID_CATEGORIE - schema_values}\n"
        f"  only in schemas.py:  {schema_values - VALID_CATEGORIE}"
    )


def test_sentiment_nlp_in_sync():
    """VALID_SENTIMENTI in classify.py must match SentimentNlp literal in schemas.py."""
    schema_values = set(get_args(SentimentNlp))
    assert VALID_SENTIMENTI == schema_values, (
        f"Drift detected!\n"
        f"  reviews/classify.py VALID_SENTIMENTI: {sorted(VALID_SENTIMENTI)}\n"
        f"  core/schemas.py    SentimentNlp:     {sorted(schema_values)}"
    )


def test_empty_testo_allowed():
    """Star-only reviews (no text) must be accepted.

    Google Maps and Booking both allow star-only reviews. A 1-star review
    without a comment is still a valid alert signal and must not be dropped.
    Regression test for bug found on 2026-04-09.
    """
    from core.schemas import ReviewRow

    row = {
        "review_hash": "abc123",
        "piattaforma": "GOOGLE",
        "review_id": "r1",
        "societa_id": "ORTI",
        "business_unit_id": "HOTEL",
        "punteggio_raw": 1.0,
        "punteggio_norm": 2.0,
        "testo": "",  # empty — the whole point of this test
        "lingua": "it",
        "data_review": "2026-04-09",
        "data_ingest": "2026-04-09T15:22:00",
    }
    # Should not raise
    ReviewRow(**row)
