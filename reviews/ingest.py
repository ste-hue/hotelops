"""Normalize raw Apify JSON to ReviewRow dicts, dedup, write to BQ."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from core.schemas import make_hash, validate_batch, ReviewRow

log = logging.getLogger(__name__)

_TRIP_TYPE_MAP = {
    "couple": "COPPIA",
    "family": "FAMIGLIA",
    "business": "BUSINESS",
    "solo": "SOLO",
    "friends": "AMICI",
    "coppia": "COPPIA",
    "famiglia": "FAMIGLIA",
    "affari": "BUSINESS",
    "amici": "AMICI",
}


def _map_trip_type(raw: str | None) -> str | None:
    if not raw:
        return None
    return _TRIP_TYPE_MAP.get(raw.lower().strip())


def _ts_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_booking(item: dict, societa: str = "ORTI") -> dict:
    review_id = str(item.get("reviewId", ""))
    score = float(item.get("reviewScore", 0))
    return {
        "review_hash": make_hash("BOOKING", review_id),
        "piattaforma": "BOOKING",
        "review_id": review_id,
        "societa_id": societa,
        "business_unit_id": item.get("_bu", "HOTEL"),
        "punteggio_raw": score,
        "punteggio_norm": score,
        "testo": item.get("reviewText") or item.get("reviewTitle") or "",
        "testo_positivo": item.get("reviewPositiveText"),
        "testo_negativo": item.get("reviewNegativeText"),
        "titolo": item.get("reviewTitle"),
        "lingua": item.get("reviewLanguage", ""),
        "data_review": item.get("reviewDate", ""),
        "data_soggiorno": item.get("stayDate"),
        "reviewer_nome": item.get("reviewerName"),
        "reviewer_paese": item.get("reviewerCountry"),
        "tipo_viaggio": _map_trip_type(item.get("tripType")),
        "camera_tipo": item.get("roomType"),
        "url_review": item.get("reviewUrl"),
        "categoria_nlp": None,
        "sentiment_nlp": None,
        "riassunto_nlp": None,
        "alert_inviato": False,
        "data_ingest": _ts_now(),
    }


def normalize_tripadvisor(item: dict, societa: str = "ORTI") -> dict:
    review_id = str(item.get("id", ""))
    score = float(item.get("rating", 0))
    user = item.get("user") or {}
    user_loc = (user.get("userLocation") or {}).get("name")
    pub_date = (item.get("publishedDate") or "")[:10]
    travel_date = item.get("travelDate")
    return {
        "review_hash": make_hash("TRIPADVISOR", review_id),
        "piattaforma": "TRIPADVISOR",
        "review_id": review_id,
        "societa_id": societa,
        "business_unit_id": item.get("_bu", "HOTEL"),
        "punteggio_raw": score,
        "punteggio_norm": score * 2,
        "testo": item.get("text", ""),
        "testo_positivo": None,
        "testo_negativo": None,
        "titolo": item.get("title"),
        "lingua": item.get("lang", ""),
        "data_review": pub_date,
        "data_soggiorno": travel_date,
        "reviewer_nome": user.get("username"),
        "reviewer_paese": user_loc,
        "tipo_viaggio": _map_trip_type(item.get("tripType")),
        "camera_tipo": None,
        "url_review": item.get("url"),
        "categoria_nlp": None,
        "sentiment_nlp": None,
        "riassunto_nlp": None,
        "alert_inviato": False,
        "data_ingest": _ts_now(),
    }


def normalize_google(item: dict, societa: str = "ORTI") -> dict:
    review_id = str(item.get("reviewId", ""))
    score = float(item.get("stars", 0))
    return {
        "review_hash": make_hash("GOOGLE", review_id),
        "piattaforma": "GOOGLE",
        "review_id": review_id,
        "societa_id": societa,
        "business_unit_id": item.get("_bu", "HOTEL"),
        "punteggio_raw": score,
        "punteggio_norm": score * 2,
        "testo": item.get("text") or item.get("textTranslated") or "",
        "testo_positivo": None,
        "testo_negativo": None,
        "titolo": None,
        "lingua": item.get("language", ""),
        "data_review": item.get("publishedAtDate", ""),
        "data_soggiorno": None,
        "reviewer_nome": item.get("name"),
        "reviewer_paese": None,
        "tipo_viaggio": None,
        "camera_tipo": None,
        "url_review": item.get("reviewUrl"),
        "categoria_nlp": None,
        "sentiment_nlp": None,
        "riassunto_nlp": None,
        "alert_inviato": False,
        "data_ingest": _ts_now(),
    }


def normalize_expedia(item: dict, societa: str = "ORTI") -> dict:
    review_id = str(item.get("reviewId", ""))
    score = float(item.get("ratingOverall", 0))
    return {
        "review_hash": make_hash("EXPEDIA", review_id),
        "piattaforma": "EXPEDIA",
        "review_id": review_id,
        "societa_id": societa,
        "business_unit_id": item.get("_bu", "HOTEL"),
        "punteggio_raw": score,
        "punteggio_norm": score,
        "testo": item.get("reviewText", ""),
        "testo_positivo": None,
        "testo_negativo": None,
        "titolo": item.get("title"),
        "lingua": item.get("language", ""),
        "data_review": item.get("submissionDate", ""),
        "data_soggiorno": None,
        "reviewer_nome": item.get("reviewerName"),
        "reviewer_paese": item.get("reviewerCountry"),
        "tipo_viaggio": _map_trip_type(item.get("tripType")),
        "camera_tipo": None,
        "url_review": item.get("reviewUrl"),
        "categoria_nlp": None,
        "sentiment_nlp": None,
        "riassunto_nlp": None,
        "alert_inviato": False,
        "data_ingest": _ts_now(),
    }


NORMALIZERS = {
    "BOOKING": normalize_booking,
    "TRIPADVISOR": normalize_tripadvisor,
    "GOOGLE": normalize_google,
    "EXPEDIA": normalize_expedia,
}


def normalize_items(raw_items: list[dict], societa: str = "ORTI") -> list[dict]:
    """Normalize a list of raw Apify items to ReviewRow dicts."""
    rows = []
    for item in raw_items:
        piattaforma = item.get("_piattaforma")
        normalizer = NORMALIZERS.get(piattaforma)
        if not normalizer:
            log.warning("No normalizer for piattaforma=%s, skipping", piattaforma)
            continue
        try:
            rows.append(normalizer(item, societa=societa))
        except Exception:
            log.exception("Failed to normalize item from %s", piattaforma)
    return rows


def dedup_reviews(rows: list[dict]) -> list[dict]:
    """Remove duplicate reviews by review_hash (keep first occurrence)."""
    seen = set()
    result = []
    for row in rows:
        h = row["review_hash"]
        if h not in seen:
            seen.add(h)
            result.append(row)
    return result


def load_to_bq(
    rows: list[dict],
    dry_run: bool = False,
) -> int:
    """Write review rows to f_reviews in BigQuery (APPEND, dedup by hash).

    Returns number of rows inserted.
    """
    from google.cloud import bigquery
    from core.config import F_REVIEWS, PROJECT

    if not rows:
        log.info("No rows to load.")
        return 0

    validate_batch(rows, ReviewRow, context="reviews ingest")

    if dry_run:
        log.info("[DRY RUN] Would insert %d rows into %s", len(rows), F_REVIEWS)
        return 0

    client = bigquery.Client(project=PROJECT)

    hashes = [r["review_hash"] for r in rows]
    placeholders = ", ".join(f"'{h}'" for h in hashes)
    existing_sql = f"""
    SELECT review_hash FROM `{F_REVIEWS}`
    WHERE review_hash IN ({placeholders})
    """
    try:
        existing = {row.review_hash for row in client.query(existing_sql).result()}
    except Exception:
        existing = set()

    new_rows = [r for r in rows if r["review_hash"] not in existing]
    if not new_rows:
        log.info("All %d reviews already in BQ, nothing to insert.", len(rows))
        return 0

    errors = client.insert_rows_json(F_REVIEWS, new_rows)
    if errors:
        log.error("BQ insert errors: %s", errors)
        raise RuntimeError(f"BQ insert failed: {errors}")

    log.info("Inserted %d new reviews into %s", len(new_rows), F_REVIEWS)
    return len(new_rows)
