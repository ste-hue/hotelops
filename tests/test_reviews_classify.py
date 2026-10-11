"""Tests for reviews NLP classification."""

from verticals.reviews.classify import (
    build_prompt,
    parse_batch_classification,
    parse_classification,
)


def test_parse_valid_json():
    raw = '{"categoria": "PULIZIA", "sentiment": "NEGATIVO", "riassunto": "Camera sporca."}'
    result = parse_classification(raw)
    assert result["categoria_nlp"] == "PULIZIA"
    assert result["sentiment_nlp"] == "NEGATIVO"
    assert result["riassunto_nlp"] == "Camera sporca."


def test_parse_extracts_json_from_text():
    raw = 'Here is the result:\n```json\n{"categoria": "CIBO", "sentiment": "POSITIVO", "riassunto": "Ottima colazione."}\n```'
    result = parse_classification(raw)
    assert result["categoria_nlp"] == "CIBO"


def test_parse_invalid_categoria_falls_back():
    raw = '{"categoria": "METEO", "sentiment": "POSITIVO", "riassunto": "Bel tempo."}'
    result = parse_classification(raw)
    assert result["categoria_nlp"] == "GENERICA"


def test_parse_invalid_json_returns_none():
    raw = "this is not json"
    result = parse_classification(raw)
    assert result["categoria_nlp"] is None
    assert result["sentiment_nlp"] is None
    assert result["riassunto_nlp"] is None


def test_build_prompt_single():
    reviews = [
        {"testo": "Camera sporca.", "piattaforma": "BOOKING", "punteggio_raw": 4.0}
    ]
    prompt = build_prompt(reviews)
    assert "Camera sporca." in prompt
    assert "BOOKING" in prompt


def test_build_prompt_batch():
    reviews = [
        {"testo": "Ottimo.", "piattaforma": "GOOGLE", "punteggio_raw": 5.0},
        {"testo": "Pessimo.", "piattaforma": "BOOKING", "punteggio_raw": 2.0},
    ]
    prompt = build_prompt(reviews)
    assert "Review 1:" in prompt
    assert "Review 2:" in prompt


def test_parse_batch_classification_success():
    raw = """[
      {"categoria":"WIFI","sentiment":"NEGATIVO","riassunto":"Connessione lenta."},
      {"categoria":"PREZZO","sentiment":"POSITIVO","riassunto":"Buon rapporto qualità-prezzo."}
    ]"""
    result = parse_batch_classification(raw, count=2)
    assert len(result) == 2
    assert result[0]["categoria_nlp"] == "WIFI"
    assert result[1]["categoria_nlp"] == "PREZZO"


def test_parse_batch_classification_pads_missing_items():
    raw = '[{"categoria":"STAFF","sentiment":"POSITIVO","riassunto":"Gentili."}]'
    result = parse_batch_classification(raw, count=2)
    assert len(result) == 2
    # A missing item could be anywhere in the batch: alignment is unknown.
    assert result[0]["categoria_nlp"] is None
    assert result[1]["categoria_nlp"] is None


def test_single_object_cannot_classify_multiple_reviews():
    raw = '{"categoria":"STAFF","sentiment":"POSITIVO","riassunto":"One review."}'
    result = parse_batch_classification(raw, count=3)
    assert all(r["categoria_nlp"] is None for r in result)
    result[0]["categoria_nlp"] = "WIFI"
    assert result[1]["categoria_nlp"] is None


def test_malformed_item_does_not_shift_or_drop_other_reviews():
    result = parse_batch_classification(
        '[null, {"categoria":"WIFI","sentiment":"NEGATIVO","riassunto":"Slow."}]',
        2,
    )
    assert result[0]["categoria_nlp"] is None
    assert result[1]["categoria_nlp"] == "WIFI"


def test_invalid_field_types_do_not_raise_or_reach_storage():
    for raw in [
        "{}",
        '{"categoria":"STAFF"}',
        '{"categoria":null,"sentiment":"POSITIVO"}',
        '{"categoria":["STAFF"],"sentiment":"POSITIVO"}',
        '{"categoria":"STAFF","sentiment":{}}',
        '{"categoria":"STAFF","sentiment":"POSITIVO","riassunto":[]}',
    ]:
        assert parse_classification(raw)["categoria_nlp"] is None


def test_malformed_response_is_not_copied_to_logs(caplog):
    parse_classification("PRIVATE_REVIEW_CONTENT not JSON")
    assert "PRIVATE_REVIEW_CONTENT" not in caplog.text
