# Reviews Vertical Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `reviews/` vertical that scrapes guest reviews from 4 platforms via Apify, classifies them with Claude API, stores in BigQuery, sends email alerts for negatives, and provides a weekly report + Streamlit dashboard.

**Architecture:** Apify actors run in the cloud; we trigger via Python SDK and collect JSON. Reviews are normalized, deduplicated, classified via Claude Haiku, validated through Pydantic, and written to `f_reviews` (APPEND). Email alerts fire immediately for negatives (<=6/10). A weekly cron sends an HTML summary report. A Streamlit dashboard provides interactive exploration.

**Tech Stack:** `apify-client`, `anthropic` (Claude Haiku 4.5), `google-cloud-bigquery`, `google-api-python-client` (Gmail API), `streamlit`, `plotly`, `pydantic`

**Spec:** `docs/superpowers/specs/2026-04-06-reviews-vertical-design.md`

---

## File Structure

```
reviews/
  __init__.py          # Package marker
  config.py            # Apify actor IDs, property URLs, thresholds, recipients
  scrape.py            # Apify SDK: trigger actors per platform, collect JSON results
  ingest.py            # Normalize raw JSON → common schema, dedup, BQ write
  classify.py          # Claude API batch classification: categoria + sentiment + riassunto
  alert.py             # Email alert for negative reviews
  email.py             # Weekly HTML report generation + Gmail send
  app.py               # Streamlit dashboard
  cli_commands.py      # CLI handlers for `hotelops reviews`

core/config.py         # Add F_REVIEWS
core/schemas.py        # Add ReviewRow

cli.py                 # Add `reviews` subcommand

tests/
  test_reviews_schema.py    # ReviewRow validation tests
  test_reviews_ingest.py    # Normalization + dedup tests
  test_reviews_classify.py  # Classification prompt + parsing tests
  test_reviews_alert.py     # Alert threshold + email rendering tests
```

---

### Task 1: ReviewRow Schema + Config

**Files:**
- Modify: `core/schemas.py`
- Modify: `core/config.py`
- Create: `tests/test_reviews_schema.py`

- [ ] **Step 1: Write failing tests for ReviewRow**

```python
# tests/test_reviews_schema.py
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

    def test_testo_not_empty(self):
        with pytest.raises(ValueError):
            ReviewRow(**_valid_row(testo=""))

    def test_validate_batch_ok(self):
        rows = [_valid_row(), _valid_row(review_hash="xyz789")]
        result = validate_batch(rows, ReviewRow, context="test reviews")
        assert len(result) == 2

    def test_validate_batch_fail(self):
        rows = [_valid_row(), _valid_row(piattaforma="YELP")]
        with pytest.raises(SchemaViolationError):
            validate_batch(rows, ReviewRow, context="test reviews")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reviews_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'ReviewRow'`

- [ ] **Step 3: Implement ReviewRow in core/schemas.py**

Add at end of `core/schemas.py`, before `validate_batch`:

```python
# ── f_reviews ───────────────────────────────────────────────────────────────

PiattaformaReview = Literal["BOOKING", "TRIPADVISOR", "GOOGLE", "EXPEDIA"]
CategoriaNlp = Literal[
    "PULIZIA", "CIBO", "STAFF", "STRUTTURA", "POSIZIONE",
    "RUMORE", "PREZZO", "WIFI", "ALTRO",
]
SentimentNlp = Literal["POSITIVO", "NEGATIVO", "MISTO"]
TipoViaggio = Literal["COPPIA", "FAMIGLIA", "BUSINESS", "SOLO", "AMICI"]


class ReviewRow(BaseModel):
    """Schema for f_reviews — guest reviews from OTA platforms.

    Source: Apify scrapers (Booking, TripAdvisor, Google, Expedia).
    Pattern: APPEND + review_hash dedup.
    """
    review_hash: str
    piattaforma: PiattaformaReview
    review_id: str
    societa_id: SocietaId
    business_unit_id: BusinessUnitId
    punteggio_raw: float
    punteggio_norm: float
    testo: str
    testo_positivo: Optional[str] = None
    testo_negativo: Optional[str] = None
    titolo: Optional[str] = None
    lingua: str
    data_review: str  # ISO date
    data_soggiorno: Optional[str] = None  # ISO date
    reviewer_nome: Optional[str] = None
    reviewer_paese: Optional[str] = None
    tipo_viaggio: Optional[TipoViaggio] = None
    camera_tipo: Optional[str] = None
    url_review: Optional[str] = None
    categoria_nlp: Optional[CategoriaNlp] = None
    sentiment_nlp: Optional[SentimentNlp] = None
    riassunto_nlp: Optional[str] = None
    alert_inviato: bool = False
    data_ingest: str  # ISO timestamp

    @field_validator("review_hash")
    @classmethod
    def hash_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("review_hash vuoto")
        return v.strip()

    @field_validator("testo")
    @classmethod
    def testo_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("testo vuoto")
        return v.strip()

    @field_validator("punteggio_norm")
    @classmethod
    def norm_range(cls, v: float) -> float:
        if not 1.0 <= v <= 10.0:
            raise ValueError(f"punteggio_norm fuori range 1-10: {v}")
        return v
```

- [ ] **Step 4: Add F_REVIEWS to core/config.py**

Add after `F_PMS_STATISTICHE`:

```python
F_REVIEWS                       = _t("f_reviews")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_reviews_schema.py -v`
Expected: All 11 tests PASS

- [ ] **Step 6: Commit**

```bash
git add core/schemas.py core/config.py tests/test_reviews_schema.py
git commit -m "feat(reviews): add ReviewRow schema + F_REVIEWS config"
```

---

### Task 2: Reviews Config

**Files:**
- Create: `reviews/__init__.py`
- Create: `reviews/config.py`

- [ ] **Step 1: Create reviews package**

```python
# reviews/__init__.py
```

- [ ] **Step 2: Create reviews/config.py**

```python
# reviews/config.py
"""Configuration for the reviews vertical."""

# Apify actor IDs
APIFY_ACTORS = {
    "BOOKING": "voyager/booking-reviews-scraper",
    "TRIPADVISOR": "automation-lab/tripadvisor-scraper",
    "GOOGLE": "compass/google-maps-reviews-scraper",
    "EXPEDIA": "memo23/expedia-scraper",
}

# Property URLs/IDs per platform per BU.
# Keys: business_unit_id -> piattaforma -> URL or place_id.
# Fill in actual URLs before first run.
PROPERTIES: dict[str, dict[str, str]] = {
    "HOTEL": {
        "BOOKING": "",      # e.g. https://www.booking.com/hotel/it/panorama-maiori.html
        "TRIPADVISOR": "",   # e.g. https://www.tripadvisor.com/Hotel_Review-...
        "GOOGLE": "",        # e.g. place_id:ChIJ...
        "EXPEDIA": "",       # e.g. https://www.expedia.com/...
    },
    # Add RESIDENCE, CVM, LIDO as needed
}

# Normalization: platform raw score -> 1-10 scale
SCORE_SCALE = {
    "BOOKING": 10.0,     # already 1-10
    "TRIPADVISOR": 5.0,  # 1-5 -> multiply by 2
    "GOOGLE": 5.0,       # 1-5 -> multiply by 2
    "EXPEDIA": 10.0,     # already 1-10
}

# Alert threshold (normalized 1-10)
ALERT_THRESHOLD = 6.0

# Email recipients
ALERT_RECIPIENTS = ["stefano@panoramagroup.it"]
REPORT_RECIPIENTS = ["stefano@panoramagroup.it"]

# Claude API model for NLP classification
NLP_MODEL = "claude-haiku-4-5-20251001"
NLP_BATCH_SIZE = 20  # reviews per API call
```

- [ ] **Step 3: Commit**

```bash
git add reviews/__init__.py reviews/config.py
git commit -m "feat(reviews): add reviews config — Apify actors, thresholds, recipients"
```

---

### Task 3: Scraper (Apify Integration)

**Files:**
- Create: `reviews/scrape.py`

- [ ] **Step 1: Implement reviews/scrape.py**

```python
# reviews/scrape.py
"""Trigger Apify actors and collect review results."""

from __future__ import annotations

import logging
from typing import Optional

from apify_client import ApifyClient

from reviews.config import APIFY_ACTORS, PROPERTIES

log = logging.getLogger(__name__)


def _get_client() -> ApifyClient:
    """Get Apify client. Expects APIFY_API_TOKEN env var."""
    import os
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise RuntimeError("APIFY_API_TOKEN env var not set")
    return ApifyClient(token)


def _build_input(piattaforma: str, bu: str, url: str) -> dict:
    """Build actor-specific run input from a property URL."""
    if piattaforma == "BOOKING":
        return {
            "startUrls": [{"url": url}],
            "maxReviews": 100,
            "sortBy": "f_recent_desc",
        }
    elif piattaforma == "TRIPADVISOR":
        return {
            "startUrls": [{"url": url}],
            "maxReviews": 100,
            "language": "ALL",
        }
    elif piattaforma == "GOOGLE":
        return {
            "startUrls": [{"url": url}],
            "maxReviews": 100,
            "language": "it",
        }
    elif piattaforma == "EXPEDIA":
        return {
            "startUrls": [{"url": url}],
            "maxReviews": 100,
        }
    else:
        raise ValueError(f"Unknown piattaforma: {piattaforma}")


def scrape_platform(
    piattaforma: str,
    bu: str | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """Scrape reviews for a platform (optionally filtered by BU).

    Returns list of raw JSON items from the Apify dataset.
    """
    actor_id = APIFY_ACTORS.get(piattaforma)
    if not actor_id:
        raise ValueError(f"No Apify actor for: {piattaforma}")

    bus = [bu] if bu else list(PROPERTIES.keys())
    all_items = []

    client = _get_client()

    for b in bus:
        url = PROPERTIES.get(b, {}).get(piattaforma)
        if not url:
            log.warning("No URL for %s / %s, skipping", b, piattaforma)
            continue

        run_input = _build_input(piattaforma, b, url)

        if dry_run:
            log.info("[DRY RUN] Would trigger %s for %s / %s", actor_id, b, piattaforma)
            continue

        log.info("Triggering %s for %s / %s ...", actor_id, b, piattaforma)
        run = client.actor(actor_id).call(run_input=run_input)

        dataset_id = run["defaultDatasetId"]
        items = list(client.dataset(dataset_id).iterate_items())
        log.info("Collected %d items for %s / %s", len(items), b, piattaforma)

        # Tag each item with BU for downstream processing
        for item in items:
            item["_bu"] = b
            item["_piattaforma"] = piattaforma

        all_items.extend(items)

    return all_items


def scrape_all(dry_run: bool = False) -> list[dict]:
    """Scrape all platforms, all BUs. Returns combined raw items."""
    all_items = []
    for piattaforma in APIFY_ACTORS:
        try:
            items = scrape_platform(piattaforma, dry_run=dry_run)
            all_items.extend(items)
        except Exception:
            log.exception("Failed to scrape %s", piattaforma)
    return all_items
```

- [ ] **Step 2: Commit**

```bash
git add reviews/scrape.py
git commit -m "feat(reviews): add Apify scraper — trigger + collect per platform"
```

---

### Task 4: Ingest (Normalize + Dedup + BQ Write)

**Files:**
- Create: `reviews/ingest.py`
- Create: `tests/test_reviews_ingest.py`

- [ ] **Step 1: Write failing tests for normalization**

```python
# tests/test_reviews_ingest.py
"""Tests for reviews ingest: normalization and dedup."""

import pytest
from reviews.ingest import normalize_booking, normalize_tripadvisor, normalize_google, normalize_expedia, dedup_reviews
from core.schemas import ReviewRow


def test_normalize_booking():
    raw = {
        "_bu": "HOTEL",
        "_piattaforma": "BOOKING",
        "reviewId": "rev_001",
        "reviewScore": 4.2,
        "reviewTitle": "Deludente",
        "reviewText": "Camera sporca.",
        "reviewPositiveText": "Posizione bella",
        "reviewNegativeText": "Camera sporca",
        "reviewDate": "2026-04-01",
        "stayDate": "2026-03-28",
        "reviewerName": "Mario",
        "reviewerCountry": "Italy",
        "tripType": "Couple",
        "roomType": "Double Room",
        "reviewUrl": "https://booking.com/review/001",
        "reviewLanguage": "it",
    }
    row = normalize_booking(raw, societa="ORTI")
    assert row["piattaforma"] == "BOOKING"
    assert row["punteggio_raw"] == 4.2
    assert row["punteggio_norm"] == 4.2  # Booking already 1-10
    assert row["business_unit_id"] == "HOTEL"
    assert row["testo"] == "Camera sporca."
    assert row["testo_positivo"] == "Posizione bella"
    # Validate through schema
    ReviewRow(**row)


def test_normalize_tripadvisor():
    raw = {
        "_bu": "HOTEL",
        "_piattaforma": "TRIPADVISOR",
        "id": "ta_001",
        "rating": 3,
        "title": "Nella media",
        "text": "Niente di speciale.",
        "publishedDate": "2026-04-01",
        "travelDate": "2026-03-20",
        "username": "Luigi",
        "userLocation": "Roma, Italia",
        "tripType": "Family",
        "language": "it",
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
        "reviewId": "exp_001",
        "ratingOverall": 7.5,
        "title": "Buono",
        "reviewText": "Buon soggiorno.",
        "submissionDate": "2026-04-01",
        "reviewerName": "Paolo",
        "reviewerCountry": "IT",
        "tripType": "Business",
        "language": "it",
        "reviewUrl": "https://expedia.com/review/001",
    }
    row = normalize_expedia(raw, societa="ORTI")
    assert row["punteggio_raw"] == 7.5
    assert row["punteggio_norm"] == 7.5  # Expedia already 1-10
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reviews_ingest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reviews.ingest'`

- [ ] **Step 3: Implement reviews/ingest.py**

```python
# reviews/ingest.py
"""Normalize raw Apify JSON to ReviewRow dicts, dedup, write to BQ."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from core.schemas import make_hash, validate_batch, ReviewRow

log = logging.getLogger(__name__)

# ── Trip type mapping ────────────────────────────────────────────────────────

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


# ── Normalizers per platform ─────────────────────────────────────────────────


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
        "punteggio_norm": score,  # already 1-10
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
    return {
        "review_hash": make_hash("TRIPADVISOR", review_id),
        "piattaforma": "TRIPADVISOR",
        "review_id": review_id,
        "societa_id": societa,
        "business_unit_id": item.get("_bu", "HOTEL"),
        "punteggio_raw": score,
        "punteggio_norm": score * 2,  # 1-5 -> 1-10
        "testo": item.get("text", ""),
        "testo_positivo": None,
        "testo_negativo": None,
        "titolo": item.get("title"),
        "lingua": item.get("language", ""),
        "data_review": item.get("publishedDate", ""),
        "data_soggiorno": item.get("travelDate"),
        "reviewer_nome": item.get("username"),
        "reviewer_paese": item.get("userLocation"),
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
        "punteggio_norm": score * 2,  # 1-5 -> 1-10
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
        "punteggio_norm": score,  # already 1-10
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

    # Filter out already-existing hashes
    hashes = [r["review_hash"] for r in rows]
    placeholders = ", ".join(f"'{h}'" for h in hashes)
    existing_sql = f"""
    SELECT review_hash FROM `{F_REVIEWS}`
    WHERE review_hash IN ({placeholders})
    """
    try:
        existing = {row.review_hash for row in client.query(existing_sql).result()}
    except Exception:
        existing = set()  # table may not exist yet

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reviews_ingest.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add reviews/ingest.py tests/test_reviews_ingest.py
git commit -m "feat(reviews): add ingest — normalize per platform + dedup + BQ write"
```

---

### Task 5: NLP Classification (Claude API)

**Files:**
- Create: `reviews/classify.py`
- Create: `tests/test_reviews_classify.py`

- [ ] **Step 1: Write failing tests for classification**

```python
# tests/test_reviews_classify.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reviews_classify.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement reviews/classify.py**

```python
# reviews/classify.py
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
    # Try to extract JSON from response
    text = raw_text.strip()

    # Try to find JSON object in text
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

    # Try to find JSON array
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

    # Pad if Claude returned fewer results than expected
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
            # Leave NLP fields as None

        classified.extend(batch)

    return classified
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reviews_classify.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add reviews/classify.py tests/test_reviews_classify.py
git commit -m "feat(reviews): add NLP classification via Claude API — batch prompt + parsing"
```

---

### Task 6: Email Alert + Weekly Report

**Files:**
- Create: `reviews/alert.py`
- Create: `reviews/email.py`
- Create: `tests/test_reviews_alert.py`

- [ ] **Step 1: Write failing tests for alert logic**

```python
# tests/test_reviews_alert.py
"""Tests for review alert logic and email rendering."""

import pytest
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reviews_alert.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement reviews/alert.py**

```python
# reviews/alert.py
"""Email alerts for negative reviews."""

from __future__ import annotations

import logging

from reviews.config import ALERT_THRESHOLD, ALERT_RECIPIENTS

log = logging.getLogger(__name__)


def should_alert(row: dict) -> bool:
    """Return True if this review should trigger an alert."""
    if row.get("alert_inviato"):
        return False
    return row.get("punteggio_norm", 10.0) <= ALERT_THRESHOLD


def render_alert_body(row: dict) -> str:
    """Render plain-text email body for a negative review alert."""
    scala = 10 if row["piattaforma"] in ("BOOKING", "EXPEDIA") else 5
    return f"""Review negativa ricevuta

Piattaforma: {row["piattaforma"]}
Struttura: {row["business_unit_id"]}
Punteggio: {row["punteggio_raw"]}/{scala}
Data review: {row["data_review"]}
Categoria: {row.get("categoria_nlp") or "N/A"}
Reviewer: {row.get("reviewer_nome") or "Anonimo"} ({row.get("reviewer_paese") or "?"})

Riassunto: {row.get("riassunto_nlp") or "N/A"}

Testo completo:
{row.get("testo", "")}

Link: {row.get("url_review") or "N/A"}
"""


def render_alert_subject(row: dict) -> str:
    """Render email subject line for a negative review alert."""
    scala = 10 if row["piattaforma"] in ("BOOKING", "EXPEDIA") else 5
    return (
        f"Review negativa — {row['business_unit_id']} — "
        f"{row['piattaforma']} — {row['punteggio_raw']}/{scala}"
    )


def send_alerts(rows: list[dict], dry_run: bool = False) -> list[dict]:
    """Send email alerts for negative reviews. Returns list of alerted rows.

    Marks alert_inviato=True on rows that were alerted.
    """
    from reviews.email import send_email

    alerted = []
    for row in rows:
        if not should_alert(row):
            continue

        subject = render_alert_subject(row)
        body = render_alert_body(row)

        if dry_run:
            log.info("[DRY RUN] Would send alert: %s", subject)
        else:
            send_email(
                to=ALERT_RECIPIENTS,
                subject=subject,
                body=body,
            )
            row["alert_inviato"] = True
            log.info("Alert sent: %s", subject)

        alerted.append(row)

    return alerted
```

- [ ] **Step 4: Implement reviews/email.py**

```python
# reviews/email.py
"""Email sending (Gmail API) and weekly report rendering."""

from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from reviews.config import REPORT_RECIPIENTS

log = logging.getLogger(__name__)


def _get_gmail_service():
    """Get Gmail API service using gcloud application default credentials."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from google.auth.transport.requests import Request
    from google.auth import default

    creds, project = default(scopes=["https://www.googleapis.com/auth/gmail.send"])
    return build("gmail", "v1", credentials=creds)


def send_email(
    to: list[str],
    subject: str,
    body: str,
    html: str | None = None,
) -> None:
    """Send email via Gmail API."""
    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(html, "html"))
    else:
        msg = MIMEText(body, "plain")

    msg["To"] = ", ".join(to)
    msg["Subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    service = _get_gmail_service()
    service.users().messages().send(
        userId="me",
        body={"raw": raw},
    ).execute()

    log.info("Email sent to %s: %s", to, subject)


def render_weekly_report(
    rows: list[dict],
    date_start: str,
    date_end: str,
) -> str:
    """Render weekly review report as HTML.

    Args:
        rows: All reviews in the period.
        date_start: ISO date string (monday of previous week).
        date_end: ISO date string (sunday of previous week).
    """
    total = len(rows)
    if total == 0:
        return f"""<html><body>
        <h2>Reviews settimanali — {date_start} / {date_end}</h2>
        <p>Nessuna review ricevuta questa settimana.</p>
        </body></html>"""

    avg_score = sum(r.get("punteggio_norm", 0) for r in rows) / total
    negatives = [r for r in rows if r.get("punteggio_norm", 10) <= 6.0]

    # Count by platform
    by_platform = {}
    for r in rows:
        p = r.get("piattaforma", "?")
        by_platform.setdefault(p, []).append(r)

    # Count by category
    by_cat = {}
    for r in rows:
        cat = r.get("categoria_nlp") or "N/A"
        by_cat[cat] = by_cat.get(cat, 0) + 1
    top_cats = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[:5]

    # Build HTML
    platform_rows = ""
    for p, rev_list in sorted(by_platform.items()):
        p_avg = sum(r.get("punteggio_norm", 0) for r in rev_list) / len(rev_list)
        platform_rows += f"<tr><td>{p}</td><td>{len(rev_list)}</td><td>{p_avg:.1f}</td></tr>"

    cat_rows = ""
    for cat, count in top_cats:
        cat_rows += f"<tr><td>{cat}</td><td>{count}</td></tr>"

    neg_rows = ""
    for r in negatives:
        neg_rows += (
            f"<tr>"
            f"<td>{r.get('piattaforma')}</td>"
            f"<td>{r.get('business_unit_id')}</td>"
            f"<td>{r.get('punteggio_norm', 0):.0f}/10</td>"
            f"<td>{r.get('categoria_nlp') or 'N/A'}</td>"
            f"<td>{r.get('riassunto_nlp') or r.get('testo', '')[:80]}</td>"
            f"</tr>"
        )

    return f"""<html><body style="font-family: Arial, sans-serif; max-width: 700px; margin: auto;">
<h2>Reviews settimanali — {date_start} / {date_end}</h2>

<table style="margin-bottom: 20px;">
<tr><td><strong>Totale review:</strong></td><td>{total}</td></tr>
<tr><td><strong>Punteggio medio:</strong></td><td>{avg_score:.1f}/10</td></tr>
<tr><td><strong>Review negative (<=6):</strong></td><td>{len(negatives)}</td></tr>
</table>

<h3>Per piattaforma</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">
<tr style="background: #1F4E79; color: white;">
<th>Piattaforma</th><th># Review</th><th>Media</th>
</tr>
{platform_rows}
</table>

<h3>Top categorie</h3>
<table border="1" cellpadding="6" cellspacing="0" style="border-collapse: collapse;">
<tr style="background: #1F4E79; color: white;">
<th>Categoria</th><th># Menzioni</th>
</tr>
{cat_rows}
</table>

{"<h3>Review negative</h3>" if negatives else ""}
{"<table border='1' cellpadding='6' cellspacing='0' style='border-collapse: collapse;'><tr style='background: #C0392B; color: white;'><th>Piattaforma</th><th>BU</th><th>Score</th><th>Categoria</th><th>Riassunto</th></tr>" + neg_rows + "</table>" if negatives else "<p>Nessuna review negativa questa settimana!</p>"}

</body></html>"""


def send_weekly_report(
    rows: list[dict],
    date_start: str,
    date_end: str,
    dry_run: bool = False,
) -> None:
    """Generate and send the weekly review report."""
    html = render_weekly_report(rows, date_start, date_end)
    subject = f"Reviews settimanali — {date_start} / {date_end}"
    plain = f"Reviews settimanali: {len(rows)} review, vedi HTML per dettagli."

    if dry_run:
        log.info("[DRY RUN] Would send weekly report: %s", subject)
        return

    send_email(
        to=REPORT_RECIPIENTS,
        subject=subject,
        body=plain,
        html=html,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_reviews_alert.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Commit**

```bash
git add reviews/alert.py reviews/email.py tests/test_reviews_alert.py
git commit -m "feat(reviews): add email alerts + weekly HTML report"
```

---

### Task 7: CLI Commands

**Files:**
- Create: `reviews/cli_commands.py`
- Modify: `cli.py`

- [ ] **Step 1: Implement reviews/cli_commands.py**

```python
# reviews/cli_commands.py
"""CLI handlers for hotelops reviews subcommand."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def cmd_reviews(args):
    """Main reviews CLI handler — dispatches to sub-actions."""
    if args.scrape:
        _cmd_scrape(args)
    elif args.alert:
        _cmd_alert(args)
    elif args.report:
        _cmd_report(args)
    elif args.stats:
        _cmd_stats(args)
    else:
        _cmd_summary(args)


def _cmd_summary(args):
    """Show latest reviews summary."""
    from google.cloud import bigquery
    from core.config import F_REVIEWS, PROJECT

    client = bigquery.Client(project=PROJECT)

    sql = f"""
    SELECT piattaforma, business_unit_id, punteggio_norm, punteggio_raw,
           categoria_nlp, sentiment_nlp, riassunto_nlp, data_review
    FROM `{F_REVIEWS}`
    ORDER BY data_ingest DESC
    LIMIT 30
    """
    rows = [dict(r) for r in client.query(sql).result()]

    if not rows:
        print("  Nessuna review trovata.")
        return

    avg = sum(r["punteggio_norm"] for r in rows) / len(rows)
    neg = sum(1 for r in rows if r["punteggio_norm"] <= 6.0)

    print(f"\n  Ultime {len(rows)} reviews — Media: {avg:.1f}/10 — Negative: {neg}")
    print(f"  {'Data':<12s} {'Piatt.':<14s} {'BU':<10s} {'Score':>6s} {'Categoria':<12s} {'Riassunto'}")
    print(f"  {'─' * 12} {'─' * 14} {'─' * 10} {'─' * 6} {'─' * 12} {'─' * 30}")

    for r in rows:
        score = f"{r['punteggio_norm']:.0f}/10"
        cat = r.get("categoria_nlp") or "—"
        riassunto = (r.get("riassunto_nlp") or "")[:40]
        print(
            f"  {r['data_review']!s:<12s} {r['piattaforma']:<14s} "
            f"{r['business_unit_id']:<10s} {score:>6s} {cat:<12s} {riassunto}"
        )


def _cmd_scrape(args):
    """Trigger manual scrape."""
    from reviews.scrape import scrape_platform, scrape_all
    from reviews.ingest import normalize_items, dedup_reviews, load_to_bq
    from reviews.classify import classify_reviews
    from reviews.alert import send_alerts

    platform = args.only.upper() if args.only else None

    print(f"\n  Scraping {'all platforms' if not platform else platform}...")

    if platform:
        raw = scrape_platform(platform, dry_run=args.dry_run)
    else:
        raw = scrape_all(dry_run=args.dry_run)

    if args.dry_run:
        print(f"  [DRY RUN] Would process {len(raw)} raw items")
        return

    print(f"  Collected {len(raw)} raw items")

    rows = normalize_items(raw)
    rows = dedup_reviews(rows)
    print(f"  Normalized: {len(rows)} unique reviews")

    rows = classify_reviews(rows)
    print(f"  Classified: {len(rows)} reviews")

    inserted = load_to_bq(rows)
    print(f"  Loaded to BQ: {inserted} new reviews")

    alerted = send_alerts(rows)
    print(f"  Alerts sent: {len(alerted)}")


def _cmd_alert(args):
    """Show reviews that triggered alerts."""
    from google.cloud import bigquery
    from core.config import F_REVIEWS, PROJECT

    client = bigquery.Client(project=PROJECT)

    sql = f"""
    SELECT piattaforma, business_unit_id, punteggio_norm, punteggio_raw,
           categoria_nlp, riassunto_nlp, data_review, url_review
    FROM `{F_REVIEWS}`
    WHERE alert_inviato = TRUE
    ORDER BY data_ingest DESC
    LIMIT 20
    """
    rows = [dict(r) for r in client.query(sql).result()]

    if not rows:
        print("  Nessun alert inviato.")
        return

    print(f"\n  Ultimi {len(rows)} alert:")
    for r in rows:
        print(
            f"  {r['data_review']!s} | {r['piattaforma']} | "
            f"{r['punteggio_norm']:.0f}/10 | {r.get('categoria_nlp') or '—'} | "
            f"{(r.get('riassunto_nlp') or '')[:50]}"
        )


def _cmd_stats(args):
    """Show review statistics for a month."""
    from google.cloud import bigquery
    from core.config import F_REVIEWS, PROJECT

    client = bigquery.Client(project=PROJECT)
    anno = args.anno or 2026
    mese_filter = f"AND EXTRACT(MONTH FROM data_review) = {args.mese}" if args.mese else ""

    sql = f"""
    SELECT
      piattaforma,
      COUNT(*) AS n,
      ROUND(AVG(punteggio_norm), 1) AS media,
      COUNTIF(punteggio_norm <= 6) AS negative
    FROM `{F_REVIEWS}`
    WHERE EXTRACT(YEAR FROM PARSE_DATE('%Y-%m-%d', data_review)) = {anno}
    {mese_filter}
    GROUP BY piattaforma
    ORDER BY piattaforma
    """
    rows = [dict(r) for r in client.query(sql).result()]

    if not rows:
        print(f"  Nessun dato per {anno}" + (f" mese {args.mese}" if args.mese else ""))
        return

    total_n = sum(r["n"] for r in rows)
    total_neg = sum(r["negative"] for r in rows)
    overall_avg = sum(r["media"] * r["n"] for r in rows) / total_n

    print(f"\n  Review Stats — {anno}" + (f" mese {args.mese}" if args.mese else " YTD"))
    print(f"  Totale: {total_n} | Media: {overall_avg:.1f}/10 | Negative: {total_neg}")
    print(f"  {'Piattaforma':<14s} {'#':>5s} {'Media':>7s} {'Neg':>5s}")
    print(f"  {'─' * 14} {'─' * 5} {'─' * 7} {'─' * 5}")
    for r in rows:
        print(f"  {r['piattaforma']:<14s} {r['n']:>5d} {r['media']:>6.1f} {r['negative']:>5d}")


def _cmd_report(args):
    """Manually trigger weekly report."""
    from datetime import date, timedelta
    from google.cloud import bigquery
    from core.config import F_REVIEWS, PROJECT
    from reviews.email import send_weekly_report

    today = date.today()
    end = today - timedelta(days=today.weekday() + 1)  # last Sunday
    start = end - timedelta(days=6)  # last Monday

    client = bigquery.Client(project=PROJECT)
    sql = f"""
    SELECT *
    FROM `{F_REVIEWS}`
    WHERE data_review BETWEEN '{start.isoformat()}' AND '{end.isoformat()}'
    ORDER BY data_review
    """
    rows = [dict(r) for r in client.query(sql).result()]

    print(f"  Report {start.isoformat()} — {end.isoformat()}: {len(rows)} reviews")
    send_weekly_report(rows, start.isoformat(), end.isoformat(), dry_run=args.dry_run)
    if not args.dry_run:
        print("  Email inviata.")
    else:
        print("  [DRY RUN] Email non inviata.")
```

- [ ] **Step 2: Add reviews subcommand to cli.py**

Add import at top of `cli.py` (after existing imports):

```python
from reviews.cli_commands import cmd_reviews
```

Add parser after the `reconcile` parser block (before `args = parser.parse_args()`):

```python
    # reviews
    p_reviews = sub.add_parser("reviews", help="Reviews ospiti: scrape, alert, stats")
    p_reviews.add_argument("--scrape", action="store_true", help="Trigger scrape manuale")
    p_reviews.add_argument("--only", type=str, help="Solo questa piattaforma (booking, tripadvisor, google, expedia)")
    p_reviews.add_argument("--alert", action="store_true", help="Mostra review con alert")
    p_reviews.add_argument("--stats", action="store_true", help="Statistiche review")
    p_reviews.add_argument("--mese", type=int, help="Mese per stats")
    p_reviews.add_argument("--anno", type=int, default=2026)
    p_reviews.add_argument("--report", action="store_true", help="Invia report settimanale")
    p_reviews.add_argument("--dry-run", action="store_true", help="Preview senza azioni")
```

Add to `handlers` dict:

```python
        "reviews": cmd_reviews,
```

- [ ] **Step 3: Commit**

```bash
git add reviews/cli_commands.py cli.py
git commit -m "feat(reviews): add CLI — hotelops reviews [--scrape|--alert|--stats|--report]"
```

---

### Task 8: Streamlit Dashboard

**Files:**
- Create: `reviews/app.py`

- [ ] **Step 1: Implement reviews/app.py**

```python
# reviews/app.py
"""Reviews Dashboard — Streamlit app for guest review analysis."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from core import config as cfg

PIATTAFORME = ["BOOKING", "TRIPADVISOR", "GOOGLE", "EXPEDIA"]


@st.cache_resource
def get_bq():
    from google.cloud import bigquery
    return bigquery.Client(project=cfg.PROJECT)


@st.cache_data(ttl=300, show_spinner=False)
def load_reviews(
    anno: int,
    piattaforme: list[str] | None = None,
    bu: str | None = None,
    _bq=None,
) -> pd.DataFrame:
    bq = _bq or get_bq()
    filters = [f"EXTRACT(YEAR FROM PARSE_DATE('%Y-%m-%d', data_review)) = {anno}"]
    if piattaforme:
        plist = ", ".join(f"'{p}'" for p in piattaforme)
        filters.append(f"piattaforma IN ({plist})")
    if bu:
        filters.append(f"business_unit_id = '{bu}'")

    where = " AND ".join(filters)
    sql = f"""
    SELECT *
    FROM `{cfg.F_REVIEWS}`
    WHERE {where}
    ORDER BY data_review DESC
    """
    df = bq.query(sql).to_dataframe()
    if "data_review" in df.columns:
        df["data_review"] = pd.to_datetime(df["data_review"])
    return df


def main():
    st.set_page_config(
        page_title="Reviews Dashboard",
        page_icon="⭐",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── Sidebar ──────────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⭐ Reviews Dashboard")
        anno = st.selectbox("Anno", [2025, 2026, 2027], index=1)
        piattaforme = st.multiselect("Piattaforme", PIATTAFORME, default=PIATTAFORME)
        bu = st.selectbox("Business Unit", ["Tutte", "HOTEL", "RESIDENCE", "CVM", "LIDO"])
        sentiment_filter = st.selectbox(
            "Sentiment", ["Tutti", "POSITIVO", "NEGATIVO", "MISTO"]
        )

        st.divider()
        if st.button("🔄 Ricarica da BQ", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    bq = get_bq()
    bu_filter = bu if bu != "Tutte" else None

    with st.spinner("Caricamento reviews..."):
        df = load_reviews(anno, piattaforme or None, bu_filter, _bq=bq)

    if df.empty:
        st.warning("Nessuna review trovata con questi filtri.")
        return

    if sentiment_filter != "Tutti":
        df = df[df["sentiment_nlp"] == sentiment_filter]

    # ── KPI Cards ────────────────────────────────────────────────────────────
    avg_score = df["punteggio_norm"].mean()
    n_total = len(df)
    n_negative = (df["punteggio_norm"] <= 6.0).sum()
    pct_neg = n_negative / n_total * 100 if n_total > 0 else 0

    # Worst platform
    by_plat = df.groupby("piattaforma")["punteggio_norm"].mean()
    worst_plat = by_plat.idxmin() if not by_plat.empty else "—"

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Punteggio medio", f"{avg_score:.1f}/10")
    col2.metric("Review totali", n_total)
    col3.metric("% Negative", f"{pct_neg:.0f}%")
    col4.metric("Piattaforma peggiore", worst_plat)

    st.divider()

    # ── Trend Chart ──────────────────────────────────────────────────────────
    st.subheader("Trend punteggio medio mensile")
    df["mese"] = df["data_review"].dt.to_period("M").astype(str)
    monthly = df.groupby(["mese", "piattaforma"])["punteggio_norm"].mean().reset_index()
    if not monthly.empty:
        fig = px.line(
            monthly,
            x="mese",
            y="punteggio_norm",
            color="piattaforma",
            markers=True,
            labels={"punteggio_norm": "Media", "mese": "Mese"},
        )
        fig.update_layout(yaxis_range=[1, 10], height=350)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── Category Breakdown ───────────────────────────────────────────────────
    st.subheader("Categorie")
    cat_counts = df["categoria_nlp"].value_counts().reset_index()
    cat_counts.columns = ["Categoria", "Count"]
    if not cat_counts.empty:
        fig2 = px.bar(
            cat_counts,
            x="Count",
            y="Categoria",
            orientation="h",
            color="Categoria",
        )
        fig2.update_layout(height=300, showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # ── Review Table ─────────────────────────────────────────────────────────
    st.subheader("Dettaglio review")

    display_cols = [
        "data_review", "piattaforma", "business_unit_id",
        "punteggio_norm", "categoria_nlp", "sentiment_nlp", "riassunto_nlp",
    ]
    available_cols = [c for c in display_cols if c in df.columns]
    show_df = df[available_cols].copy()
    show_df = show_df.rename(columns={
        "data_review": "Data",
        "piattaforma": "Piattaforma",
        "business_unit_id": "BU",
        "punteggio_norm": "Score",
        "categoria_nlp": "Categoria",
        "sentiment_nlp": "Sentiment",
        "riassunto_nlp": "Riassunto",
    })

    st.dataframe(show_df, hide_index=True, use_container_width=True, height=400)

    # ── Drill-down ───────────────────────────────────────────────────────────
    if st.checkbox("Mostra testo completo review"):
        for _, row in df.head(10).iterrows():
            score = f"{row['punteggio_norm']:.0f}/10"
            label = f"{row['data_review'].date()} | {row['piattaforma']} | {score}"
            with st.expander(label):
                if row.get("testo_positivo"):
                    st.markdown(f"**Pro:** {row['testo_positivo']}")
                if row.get("testo_negativo"):
                    st.markdown(f"**Contro:** {row['testo_negativo']}")
                st.markdown(f"**Testo:** {row.get('testo', '')}")
                if row.get("url_review"):
                    st.markdown(f"[Vai alla review]({row['url_review']})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add reviews app to cli.py app launcher**

In `cli.py`, update the `apps` dict in `cmd_app`:

```python
    apps = {
        "pf": "condges/app.py",
        "scadenzario": "condges/app_scadenzario.py",
        "reviews": "reviews/app.py",
    }
```

- [ ] **Step 3: Commit**

```bash
git add reviews/app.py cli.py
git commit -m "feat(reviews): add Streamlit dashboard — KPIs, trends, categories, drill-down"
```

---

### Task 9: Create BQ Table + Install Dependencies

**Files:**
- (No new files — BQ DDL + pip)

- [ ] **Step 1: Create f_reviews table in BigQuery**

Run:

```bash
bq query --use_legacy_sql=false '
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.f_reviews` (
  review_hash STRING NOT NULL,
  piattaforma STRING NOT NULL,
  review_id STRING NOT NULL,
  societa_id STRING NOT NULL,
  business_unit_id STRING NOT NULL,
  punteggio_raw FLOAT64 NOT NULL,
  punteggio_norm FLOAT64 NOT NULL,
  testo STRING NOT NULL,
  testo_positivo STRING,
  testo_negativo STRING,
  titolo STRING,
  lingua STRING,
  data_review STRING NOT NULL,
  data_soggiorno STRING,
  reviewer_nome STRING,
  reviewer_paese STRING,
  tipo_viaggio STRING,
  camera_tipo STRING,
  url_review STRING,
  categoria_nlp STRING,
  sentiment_nlp STRING,
  riassunto_nlp STRING,
  alert_inviato BOOL DEFAULT FALSE,
  data_ingest TIMESTAMP NOT NULL
)
'
```

Expected: `Table created`

- [ ] **Step 2: Install new dependencies**

Run:

```bash
pip install apify-client anthropic google-api-python-client
```

- [ ] **Step 3: Update setup.cfg / pyproject.toml with new deps**

Add to the reviews optional group:

```
[options.extras_require]
reviews =
    apify-client
    anthropic
    google-api-python-client
```

- [ ] **Step 4: Commit**

```bash
git add setup.cfg  # or pyproject.toml
git commit -m "feat(reviews): add BQ table DDL + dependencies"
```

---

### Task 10: End-to-End Integration Test + CLAUDE.md Update

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run all tests**

Run: `pytest tests/test_reviews_*.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run lint**

Run: `ruff check reviews/ tests/test_reviews_*.py && ruff format reviews/ tests/test_reviews_*.py`
Expected: No errors

- [ ] **Step 3: Smoke test CLI**

Run: `hotelops reviews --help`
Expected: Shows reviews subcommand help with --scrape, --alert, --stats, --report options

- [ ] **Step 4: Update CLAUDE.md with reviews vertical docs**

Add a `reviews/` section to the Architecture block, a `reviews` CLI section, and `f_reviews` to the tables list. Add reviews vertical description to Project Overview.

Key additions:
- Architecture: `reviews/` directory description
- Commands: `hotelops reviews` variants
- BigQuery Tables: `f_reviews` fact table
- Dependencies: `apify-client`, `anthropic`, `google-api-python-client`

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add reviews vertical to CLAUDE.md"
```

---

### Task 11: Configure Property URLs + First Run

**Files:**
- Modify: `reviews/config.py`

- [ ] **Step 1: Fill in actual property URLs**

Update `PROPERTIES` dict in `reviews/config.py` with real URLs for Hotel Panorama across all 4 platforms. Ask user for the URLs if not known.

- [ ] **Step 2: Set environment variables**

```bash
export APIFY_API_TOKEN="<token from apify.com/account/integrations>"
export ANTHROPIC_API_KEY="<key>"
```

- [ ] **Step 3: First dry-run**

Run: `hotelops reviews --scrape --dry-run`
Expected: Shows what would be scraped without actually doing it

- [ ] **Step 4: First real run**

Run: `hotelops reviews --scrape`
Expected: Scrapes reviews, classifies, loads to BQ, sends alerts for negatives

- [ ] **Step 5: Verify data in BQ**

Run:

```bash
bq query --use_legacy_sql=false 'SELECT piattaforma, COUNT(*) n, ROUND(AVG(punteggio_norm),1) avg FROM `hotelops-suite.hotelops.f_reviews` GROUP BY 1'
```

- [ ] **Step 6: Commit config with URLs**

```bash
git add reviews/config.py
git commit -m "feat(reviews): configure property URLs for first run"
```
