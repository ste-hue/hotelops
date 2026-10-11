"""NLP classification of reviews via Claude API."""

from __future__ import annotations

import json
import logging

from core.ai_output import parse_json_batch
from verticals.reviews.config import NLP_BATCH_SIZE, NLP_MODEL

log = logging.getLogger(__name__)

VALID_CATEGORIE = {
    "PULIZIA",
    "CIBO",
    "STAFF",
    "STRUTTURA",
    "POSIZIONE",
    "RUMORE",
    "PREZZO",
    "WIFI",
    "GENERICA",
}
VALID_SENTIMENTI = {"POSITIVO", "NEGATIVO", "MISTO"}

SCORE_SCALES = {
    "BOOKING": 10,
    "TRIPADVISOR": 5,
    "GOOGLE": 5,
    "EXPEDIA": 10,
    "TRIP": 10,
}


def _empty_classification() -> dict:
    """Return the default empty classification payload."""
    return {"categoria_nlp": None, "sentiment_nlp": None, "riassunto_nlp": None}


def _normalize_classification_item(item) -> dict:
    """Normalize a raw model item into canonical NLP classification fields."""
    if not isinstance(item, dict):
        return _empty_classification()
    if "categoria" not in item or "sentiment" not in item:
        return _empty_classification()
    categoria = item.get("categoria", "")
    sentiment = item.get("sentiment", "")
    summary = item.get("riassunto")
    if (
        not isinstance(categoria, str)
        or not isinstance(sentiment, str)
        or (summary is not None and not isinstance(summary, str))
    ):
        return _empty_classification()
    categoria = categoria.upper()
    if categoria not in VALID_CATEGORIE:
        categoria = "GENERICA"

    sentiment = sentiment.upper()
    if sentiment not in VALID_SENTIMENTI:
        sentiment = None

    return {
        "categoria_nlp": categoria,
        "sentiment_nlp": sentiment,
        "riassunto_nlp": summary,
    }


def build_prompt(reviews: list[dict]) -> str:
    """Build classification prompt for one or more reviews."""
    if len(reviews) == 1:
        r = reviews[0]
        scala = SCORE_SCALES.get(r["piattaforma"], 10)
        return f"""Sei un analista hotel. Classifica questa review.

Piattaforma: {r["piattaforma"]}
Punteggio: {r["punteggio_raw"]}/{scala}
Testo: {r["testo"]}

Rispondi SOLO con JSON valido:
{{"categoria": "PULIZIA|CIBO|STAFF|STRUTTURA|POSIZIONE|RUMORE|PREZZO|WIFI|GENERICA", "sentiment": "POSITIVO|NEGATIVO|MISTO", "riassunto": "max 1 frase in italiano"}}"""

    lines = [
        "Sei un analista hotel. Classifica ciascuna delle seguenti review.",
        "Per OGNUNA rispondi con una riga JSON. Rispondi SOLO con un array JSON valido.",
        f"Categorie valide: {', '.join(sorted(VALID_CATEGORIE))}",
        f"Sentiment validi: {', '.join(sorted(VALID_SENTIMENTI))}",
        "",
    ]
    for i, r in enumerate(reviews, 1):
        scala = SCORE_SCALES.get(r["piattaforma"], 10)
        lines.append(f"Review {i}:")
        lines.append(f"  Piattaforma: {r['piattaforma']}")
        lines.append(f"  Punteggio: {r['punteggio_raw']}/{scala}")
        lines.append(f"  Testo: {r['testo']}")
        lines.append("")

    lines.append(
        "Rispondi con un JSON array, un oggetto per review: "
        '[{"categoria": "...", "sentiment": "...", "riassunto": "..."}]'
    )
    return "\n".join(lines)


def parse_classification(raw_text: str) -> dict:
    """Parse Claude's response into classification fields.

    Returns dict with keys: categoria_nlp, sentiment_nlp, riassunto_nlp.
    Falls back gracefully on parse errors.
    """
    text = raw_text.strip()

    start = text.find("{")
    if start < 0:
        log.warning("No JSON found in classification response")
        return _empty_classification()

    try:
        data, _ = json.JSONDecoder().raw_decode(text, start)
    except json.JSONDecodeError:
        log.warning("Invalid JSON in classification response")
        return _empty_classification()

    result = _normalize_classification_item(data)
    if result["categoria_nlp"] == "GENERICA" and data.get(
        "categoria", ""
    ).upper() not in {
        "GENERICA",
        "",
    }:
        log.warning(
            "Invalid category in classification response, falling back to GENERICA",
        )
    return result


def parse_batch_classification(raw_text: str, count: int) -> list[dict]:
    """Parse Claude's batch response (JSON array) into list of classification dicts."""
    data = parse_json_batch(raw_text, count)
    if any(item is None for item in data):
        log.warning(
            "Invalid or unaligned classification batch; rejected slots stay empty"
        )
    return [_normalize_classification_item(item) for item in data]


def classify_reviews(rows: list[dict]) -> list[dict]:
    """Classify reviews via Claude API. Mutates rows in place, adding NLP fields.

    Batches reviews into groups of NLP_BATCH_SIZE for efficiency.
    """
    import anthropic

    client = anthropic.Anthropic()
    classified = []

    for i in range(0, len(rows), NLP_BATCH_SIZE):
        batch = rows[i : i + NLP_BATCH_SIZE]
        prompt = build_prompt(batch)

        try:
            response = client.messages.create(
                model=NLP_MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = response.content[0].text

            if len(batch) == 1:
                classifications = [parse_classification(response_text)]
            else:
                classifications = parse_batch_classification(response_text, len(batch))

            for row, cls in zip(batch, classifications):
                row.update(cls)

        except Exception:
            log.exception(
                "Claude API classification failed for batch %d-%d", i, i + len(batch)
            )

        classified.extend(batch)

    return classified
