# reviews/scrape.py
"""Trigger Apify actors and collect review results."""

from __future__ import annotations

import logging

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


# Hard cap per property per run. Even if actor ignores the param,
# we log a warning and the dedup layer throws away the excess.
MAX_REVIEWS_PER_PROPERTY = 15


def _build_input(piattaforma: str, bu: str, url: str) -> dict:
    """Build actor-specific run input from a property URL.

    Each actor has its own parameter naming — see reviews/PROPERTIES.md.
    Target: get the last MAX_REVIEWS_PER_PROPERTY reviews sorted by newest.
    """
    # Param names verified against live Apify actor schemas via
    # `python -m reviews.inspect_actors` on 2026-04-10. See ADR 0003
    # "Scoperta collaterale: param names Apify".
    n = MAX_REVIEWS_PER_PROPERTY
    if piattaforma == "BOOKING":
        # voyager/booking-reviews-scraper 0.99: sortReviewsBy (not reviewsSort)
        return {
            "startUrls": [{"url": url}],
            "maxReviewsPerHotel": n,
            "sortReviewsBy": "f_recent_desc",
        }
    elif piattaforma == "TRIPADVISOR":
        # maxcopell/tripadvisor-reviews 0.99: maxItemsPerQuery (not maxItems).
        # reviewsLanguages is an array; omit for "all languages" default.
        return {
            "startUrls": [{"url": url}],
            "maxItemsPerQuery": n,
        }
    elif piattaforma == "GOOGLE":
        # compass/Google-Maps-Reviews-Scraper 1.0: maxReviews + reviewsSort OK
        return {
            "startUrls": [{"url": url}],
            "maxReviews": n,
            "reviewsSort": "newest",
        }
    elif piattaforma == "EXPEDIA":
        # memo23/expedia-scraper 0.0: maxItems is the ONLY cap param.
        # The old maxReviewsPerHotel/maxReviews were both silently ignored,
        # causing the 2026-04-10 blowout (226 items for a 15-cap request).
        return {
            "startUrls": [{"url": url}],
            "maxItems": n,
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

        # Observability: warn loudly if the actor ignored our cap.
        # This is how we caught the 2026-04-09 cost blowout.
        if len(items) > MAX_REVIEWS_PER_PROPERTY:
            log.warning(
                "CAP VIOLATED: %s/%s returned %d items, expected <= %d. "
                "Actor param likely wrong. Truncating to %d downstream.",
                piattaforma, b, len(items), MAX_REVIEWS_PER_PROPERTY,
                MAX_REVIEWS_PER_PROPERTY,
            )
            items = items[:MAX_REVIEWS_PER_PROPERTY]

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
