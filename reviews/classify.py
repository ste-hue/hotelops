"""NLP classification of reviews via Claude API."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from reviews.config import NLP_MODEL, NLP_BATCH_SIZE

log = logging.getLogger(__name__)

VALID_CATEGORIE = {
    "PULIZIA", "CIBO", "STAFF", "STRUTTURA", "POSIZIONE",
    "RUMORE", "PREZZO", "WIFI", "ALTRO",
}
VALID_SENTIMENTI = {"POSITIVO", "NEGATIVO", "MISTO"}

SCORE_SCALES = {
    "BOOKING": 10,
    "TRIPADVISOR": 5,
    "GOOGLE": 5,
    "EXPEDIA": 10,
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
{{"categoria": "PULIZIA|CIBO|STAFF|STRUTTURA|POSIZIONE|RUMORE|PREZZO|WIFI|ALTRO", "sentiment": "POSITIVO|NEGATIVO|MISTO", "riassunto": "max 1 frase in italiano"}}"""

    lines = [
        "Sei un analista hotel. Classifica ciascuna delle seguenti review.",
        "Per OGNUNA rispondi con una riga JSON. Rispondi SOLO con un array JSON valido.",
        f'Categorie valide: {", ".join(sorted(VALID_CATEGORIE))}',
        f'Sentiment validi: {", ".join(sorted(VALID_SENTIMENTI))}',
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
        'Rispondi con un JSON array, un oggetto per review: '
        '[{"categoria": "...", "sentiment": "...", "riassunto": "..."}]'
    )
    return "\n".join(lines)


def parse_classification(raw_text: str) -> dict:
    """Parse Claude's response into classification fields.

    Returns dict with keys: categoria_nlp, sentiment_nlp, riassunto_nlp.
    Falls back gracefully on parse errors.
    """
    text = raw_text.strip()

    json_match = re.search(r'\{[^{}]*\}', text)
    if not json_match:
        log.warning("No JSON found in classification response: %s", text[:200])
        return {"categoria_nlp": None, "sentiment_nlp": None, "riassunto_nlp": None}

    try:
        data = json.loads(json_match.group())
    except json.JSONDecodeError:
        log.warning("Invalid JSON in classification response: %s", text[:200])
        return {"categoria_nlp": None, "sentiment_nlp": None, "riassunto_nlp": None}

    categoria = data.get("categoria", "").upper()
    if categoria not in VALID_CATEGORIE:
        log.warning("Invalid categoria '%s', falling back to ALTRO", categoria)
        categoria = "ALTRO"

    sentiment = data.get("sentiment", "").upper()
    if sentiment not in VALID_SENTIMENTI:
        sentiment = None

    riassunto = data.get("riassunto")

    return {
        "categoria_nlp": categoria,
        "sentiment_nlp": sentiment,
        "riassunto_nlp": riassunto,
    }


def parse_batch_classification(raw_text: str, count: int) -> list[dict]:
    """Parse Claude's batch response (JSON array) into list of classification dicts."""
    text = raw_text.strip()

    array_match = re.search(r'\[.*\]', text, re.DOTALL)
    if not array_match:
        log.warning("No JSON array in batch response, falling back to single parse")
        return [parse_classification(text)] * count

    try:
        data = json.loads(array_match.group())
    except json.JSONDecodeError:
        log.warning("Invalid JSON array in batch response")
        return [{"categoria_nlp": None, "sentiment_nlp": None, "riassunto_nlp": None}] * count

    results = []
    for item in data:
        cat = item.get("categoria", "").upper()
        if cat not in VALID_CATEGORIE:
            cat = "ALTRO"
        sent = item.get("sentiment", "").upper()
        if sent not in VALID_SENTIMENTI:
            sent = None
        results.append({
            "categoria_nlp": cat,
            "sentiment_nlp": sent,
            "riassunto_nlp": item.get("riassunto"),
        })

    while len(results) < count:
        results.append({"categoria_nlp": None, "sentiment_nlp": None, "riassunto_nlp": None})

    return results[:count]


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
            log.exception("Claude API classification failed for batch %d-%d", i, i + len(batch))

        classified.extend(batch)

    return classified
