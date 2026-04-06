"""Tests for reviews NLP classification."""

import json
import pytest
from reviews.classify import parse_classification, build_prompt, VALID_CATEGORIE, VALID_SENTIMENTI


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
    assert result["categoria_nlp"] == "ALTRO"


def test_parse_invalid_json_returns_none():
    raw = "this is not json"
    result = parse_classification(raw)
    assert result["categoria_nlp"] is None
    assert result["sentiment_nlp"] is None
    assert result["riassunto_nlp"] is None


def test_build_prompt_single():
    reviews = [{"testo": "Camera sporca.", "piattaforma": "BOOKING", "punteggio_raw": 4.0}]
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
