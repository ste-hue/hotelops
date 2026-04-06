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
            "maxItems": 100,
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
