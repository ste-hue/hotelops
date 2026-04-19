"""Normalize raw Apify JSON to ReviewRow dicts, dedup, write to BQ."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from core.bq.client import get_client
from core.schemas import make_hash, validate_batch, ReviewRow
from reviews.config import PROPERTIES

log = logging.getLogger(__name__)

_TRIP_TYPE_MAP = {
    "couple": "COPPIA",
    "couples": "COPPIA",
    "family": "FAMIGLIA",
    "business": "BUSINESS",
    "solo": "SOLO",
    "friends": "AMICI",
    "group": "AMICI",
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
    review_id = str(item.get("id", ""))
    score = float(item.get("rating", 0))
    liked = item.get("likedText") or ""
    disliked = item.get("dislikedText") or ""
    testo = f"{liked} {disliked}".strip() or item.get("reviewTitle") or ""
    bu = item.get("_bu", "HOTEL")
    # Booking non espone deep-link per singola review: fallback sulla pagina
    # hotel (+ anchor #tab-reviews) così l'email alert ha almeno un link
    # utile invece di "N/A".
    hotel_url = PROPERTIES.get(bu, {}).get("BOOKING")
    url_review = f"{hotel_url}#tab-reviews" if hotel_url else None
    return {
        "review_hash": make_hash("BOOKING", review_id),
        "piattaforma": "BOOKING",
        "review_id": review_id,
        "societa_id": societa,
        "business_unit_id": bu,
        "punteggio_raw": score,
        "punteggio_norm": score,
        "testo": testo,
        "testo_positivo": liked or None,
        "testo_negativo": disliked or None,
        "titolo": item.get("reviewTitle"),
        "lingua": item.get("reviewLanguage", ""),
        "data_review": (item.get("reviewDate") or "")[:10],
        "data_soggiorno": item.get("checkInDate"),
        "reviewer_nome": item.get("userName"),
        "reviewer_paese": item.get("userLocation"),
        "tipo_viaggio": _map_trip_type(item.get("travelerType")),
        "camera_tipo": item.get("roomInfo"),
        "url_review": url_review,
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
    score = float(item.get("stars") or 0)
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
        "data_review": (item.get("publishedAtDate") or "")[:10],
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
    score = float(item.get("reviewRating", 0))
    locale = item.get("locale", "")
    lingua = locale.split("_")[0] if locale else ""
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
        "titolo": item.get("reviewTitle") or None,
        "lingua": lingua,
        "data_review": (item.get("reviewDate") or "")[:10],
        "data_soggiorno": (item.get("stayDate") or "")[:10] or None,
        "reviewer_nome": item.get("reviewerName"),
        "reviewer_paese": None,
        "tipo_viaggio": None,
        "camera_tipo": None,
        "url_review": item.get("hotelUrl"),
        "categoria_nlp": None,
        "sentiment_nlp": None,
        "riassunto_nlp": None,
        "alert_inviato": False,
        "data_ingest": _ts_now(),
    }


_TRIP_HOTEL_ID_RE = re.compile(r"hotel-detail-(\d+)/")


def _extract_trip_hotel_id(url: str | None) -> str:
    """Extract hotel ID from a Trip.com detail URL.

    Example: https://www.trip.com/hotels/maiori-hotel-detail-774198/panorama/
    → "774198". Returns empty string if the URL doesn't match.
    """
    if not url:
        return ""
    m = _TRIP_HOTEL_ID_RE.search(url)
    return m.group(1) if m else ""


def normalize_trip(item: dict, societa: str = "ORTI") -> dict:
    """Normalize a knagymate/trip-com-reviews-scraper item.

    Notes on the actor's output schema (verified 2026-04-11):
    - `rating` is already on a 1-10 scale (ratingMax=10), no rescale.
    - `id` is per-review; combined with the hotel ID (extracted from the
      property URL) to form a stable review_hash. The item itself doesn't
      carry the hotel ID, so we recover it from PROPERTIES[bu]["TRIP"].
    - Reviews are anonymous: no author name.
    - `createDate` is "YYYY-MM-DD HH:MM:SS" — slice first 10 chars.
    - `content` is the original-language text; `translatedContent` is the
      Trip.com auto-translation. Prefer original for IT/EN, fall back to
      the translation otherwise so Claude NLP has something to read.
    - No per-review URL — fall back to the hotel page for the alert link.
    """
    bu = item.get("_bu", "HOTEL")
    hotel_url = PROPERTIES.get(bu, {}).get("TRIP") or ""
    hotel_id = _extract_trip_hotel_id(hotel_url)

    review_id = str(item.get("id", ""))
    score = float(item.get("rating") or 0)
    lang = (item.get("language") or "").lower()

    content = (item.get("content") or "").strip()
    translated = (item.get("translatedContent") or "").strip()
    if lang in ("it", "en") and content:
        testo = content
    else:
        testo = translated or content

    return {
        "review_hash": make_hash("TRIP", f"{hotel_id}|{review_id}"),
        "piattaforma": "TRIP",
        "review_id": review_id,
        "societa_id": societa,
        "business_unit_id": bu,
        "punteggio_raw": score,
        "punteggio_norm": score,  # already 1-10
        "testo": testo,
        "testo_positivo": None,
        "testo_negativo": None,
        "titolo": item.get("commentLevel"),
        "lingua": lang,
        "data_review": (item.get("createDate") or "")[:10],
        "data_soggiorno": (item.get("checkInDate") or "")[:10] or None,
        "reviewer_nome": None,  # Trip.com reviews are anonymous
        "reviewer_paese": None,
        "tipo_viaggio": _map_trip_type(
            item.get("travelTypeText") or item.get("travelType")
        ),
        "camera_tipo": item.get("roomTypeName"),
        "url_review": hotel_url or None,
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
    "TRIP": normalize_trip,
}


def normalize_items(raw_items: list[dict], societa: str = "ORTI") -> list[dict]:
    """Normalize a list of raw Apify items to ReviewRow dicts.

    Drops items with missing/invalid score (punteggio_norm outside 1-10).
    Such items are noise: no alert signal, no KPI value.
    """
    rows = []
    dropped_no_score = 0
    for item in raw_items:
        piattaforma = item.get("_piattaforma")
        normalizer = NORMALIZERS.get(piattaforma)
        if not normalizer:
            log.warning("No normalizer for piattaforma=%s, skipping", piattaforma)
            continue
        try:
            row = normalizer(item, societa=societa)
        except Exception:
            log.exception("Failed to normalize item from %s", piattaforma)
            continue

        norm = row.get("punteggio_norm", 0)
        if not (1.0 <= norm <= 10.0):
            dropped_no_score += 1
            continue
        rows.append(row)

    if dropped_no_score:
        log.warning(
            "Dropped %d reviews with invalid score (missing stars)",
            dropped_no_score,
        )
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
    from core.config import F_REVIEWS

    if not rows:
        log.info("No rows to load.")
        return 0

    validate_batch(rows, ReviewRow, context="reviews ingest")

    if dry_run:
        log.info("[DRY RUN] Would insert %d rows into %s", len(rows), F_REVIEWS)
        return 0

    client = get_client()

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


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def filter_by_watermark(
    watermarks: dict[tuple[str, str], str],
    items: list[dict],
    cap: int,
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Drop items with data_review <= watermark for their (piattaforma, bu) key.

    Args:
        watermarks: dict (piattaforma, business_unit_id) -> 'YYYY-MM-DD'.
                    Missing key means no watermark → all items for that key pass.
        items: normalized review dicts.
        cap: per-key cap used to detect suspected gaps.

    Returns:
        (kept_items, gap_keys). gap_keys lists (piattaforma, bu) pairs where
        len(kept) == cap — possible gap, caller should emit a warning email.

    Malformed data_review (not YYYY-MM-DD) is dropped with a warning log.
    Pure function; no BQ access.
    """
    kept: list[dict] = []
    per_key_count: dict[tuple[str, str], int] = {}
    dropped_malformed = 0

    for item in items:
        data = item.get("data_review") or ""
        if not _ISO_DATE.match(data):
            dropped_malformed += 1
            continue

        key = (item.get("piattaforma"), item.get("business_unit_id"))
        wm = watermarks.get(key)
        if wm is not None and data <= wm:
            continue

        kept.append(item)
        per_key_count[key] = per_key_count.get(key, 0) + 1

    if dropped_malformed:
        log.warning(
            "filter_by_watermark: dropped %d items with malformed data_review",
            dropped_malformed,
        )

    gap_keys = [k for k, n in per_key_count.items() if n == cap]
    return kept, gap_keys


def read_watermarks() -> dict[tuple[str, str], str]:
    """Read per-(piattaforma, business_unit_id) watermark from f_reviews.

    Watermark = MAX(data_review) filtered by LENGTH(data_review)=10 to guard
    against format drift (the pre-fix Google rows with ISO timestamps).
    Also issues a second audit query to log how many rows are excluded by
    the LENGTH guard, so the drift stays visible until backfill.

    Raises on BQ error — caller must abort the run (never proceed with an
    involuntarily empty watermark).
    """
    from core.config import F_REVIEWS

    client = get_client()

    # Safe: F_REVIEWS is an internal config constant (core.config), not user input.
    wm_sql = f"""
    SELECT piattaforma, business_unit_id, MAX(data_review) AS watermark
    FROM `{F_REVIEWS}`
    WHERE LENGTH(data_review) = 10
    GROUP BY piattaforma, business_unit_id
    """
    result = {
        (row.piattaforma, row.business_unit_id): row.watermark
        for row in client.query(wm_sql).result()
    }

    audit_sql = f"""
    SELECT piattaforma, COUNT(*) AS n_malformed
    FROM `{F_REVIEWS}`
    WHERE LENGTH(data_review) <> 10
    GROUP BY piattaforma
    """
    for row in client.query(audit_sql).result():
        log.warning(
            "WATERMARK EXCLUDED %d malformed data_review rows on %s",
            row.n_malformed,
            row.piattaforma,
        )

    log.info("read_watermarks: %d keys", len(result))
    return result
