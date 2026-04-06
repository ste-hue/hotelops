"""Tests for review alert logic and email rendering."""

from reviews.alert import should_alert, render_alert_body
from reviews.email import render_weekly_report


def test_should_alert_negative():
    row = {"punteggio_norm": 4.0, "alert_inviato": False}
    assert should_alert(row) is True


def test_should_alert_threshold_boundary():
    row = {"punteggio_norm": 6.0, "alert_inviato": False}
    assert should_alert(row) is True


def test_should_not_alert_positive():
    row = {"punteggio_norm": 8.0, "alert_inviato": False}
    assert should_alert(row) is False


def test_should_not_alert_already_sent():
    row = {"punteggio_norm": 3.0, "alert_inviato": True}
    assert should_alert(row) is False


def test_render_alert_body():
    row = {
        "piattaforma": "BOOKING",
        "business_unit_id": "HOTEL",
        "punteggio_raw": 4.0,
        "punteggio_norm": 4.0,
        "data_review": "2026-04-01",
        "categoria_nlp": "PULIZIA",
        "reviewer_nome": "Mario R.",
        "reviewer_paese": "IT",
        "riassunto_nlp": "Camera sporca al check-in.",
        "testo": "La camera era sporca, bagno con muffa.",
        "url_review": "https://booking.com/review/001",
    }
    body = render_alert_body(row)
    assert "BOOKING" in body
    assert "HOTEL" in body
    assert "PULIZIA" in body
    assert "Camera sporca" in body
    assert "booking.com/review/001" in body


def test_render_weekly_report():
    rows = [
        {
            "piattaforma": "BOOKING",
            "business_unit_id": "HOTEL",
            "punteggio_norm": 4.0,
            "punteggio_raw": 4.0,
            "categoria_nlp": "PULIZIA",
            "sentiment_nlp": "NEGATIVO",
            "riassunto_nlp": "Sporco.",
            "data_review": "2026-04-01",
        },
        {
            "piattaforma": "GOOGLE",
            "business_unit_id": "HOTEL",
            "punteggio_norm": 9.0,
            "punteggio_raw": 4.5,
            "categoria_nlp": "STAFF",
            "sentiment_nlp": "POSITIVO",
            "riassunto_nlp": "Personale gentile.",
            "data_review": "2026-04-02",
        },
    ]
    html = render_weekly_report(rows, "2026-03-31", "2026-04-06")
    assert "BOOKING" in html
    assert "GOOGLE" in html
    assert "6.5" in html  # average of 4.0 and 9.0
    assert "1" in html  # 1 negative
