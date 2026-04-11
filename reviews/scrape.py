# reviews/scrape.py
"""Trigger Apify actors and collect review results."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apify_client import ApifyClient

from reviews.config import APIFY_ACTORS, PROPERTIES

log = logging.getLogger(__name__)


def persist_apify_run(
    run_id: str,
    piattaforma: str,
    business_unit_id: str,
    actor_id: str,
    n_items: int,
    cost_usd: float | None,
    cap_violated: bool,
) -> None:
    """Insert one row into f_apify_runs for cost observability.

    Best-effort: on BQ failure, log warning and continue. Losing a cost
    row must never block the review pipeline — costs are observability,
    not business data.
    """
    from google.cloud import bigquery
    from core.config import F_APIFY_RUNS, PROJECT
    from core.schemas import ApifyRunRow, validate_batch

    row = {
        "run_id": run_id,
        "piattaforma": piattaforma,
        "business_unit_id": business_unit_id,
        "actor_id": actor_id,
        "ts_run": datetime.now(timezone.utc).isoformat(),
        "n_items": n_items,
        "cost_usd": cost_usd,
        "cap_violated": cap_violated,
    }
    try:
        validate_batch([row], ApifyRunRow, context="f_apify_runs persist")
        client = bigquery.Client(project=PROJECT)
        errors = client.insert_rows_json(F_APIFY_RUNS, [row])
        if errors:
            log.warning("f_apify_runs insert errors: %s", errors)
    except Exception:
        log.exception("persist_apify_run failed for run_id=%s (non-fatal)", run_id)


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
    elif piattaforma == "TRIP":
        # knagymate/trip-com-reviews-scraper: hotelUrl is a STRING (not array).
        # Passing startUrls/totalLimit silently falls back to schema defaults
        # (Grand Hyatt Shanghai, 1000 reviews) — caused the 2026-04-11 $3.38
        # exploration blowout. Schema verified via inspect_actors.
        return {
            "hotelUrl": url,
            "maxReviews": n,
        }
    else:
        raise ValueError(f"Unknown piattaforma: {piattaforma}")


def scrape_platform(
    piattaforma: str,
    bu: str | None = None,
    dry_run: bool = False,
) -> tuple[list[dict], float]:
    """Scrape reviews for a platform (optionally filtered by BU).

    Returns (items, total_cost_usd): raw JSON items from the Apify dataset
    plus the summed usageTotalUsd across all actor calls in this invocation.
    Cost is 0.0 in dry_run or when Apify doesn't return usageTotalUsd.
    """
    actor_id = APIFY_ACTORS.get(piattaforma)
    if not actor_id:
        raise ValueError(f"No Apify actor for: {piattaforma}")

    bus = [bu] if bu else list(PROPERTIES.keys())
    all_items = []
    platform_cost_usd = 0.0

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

        # Cost observability: log Apify usage per run. `usageTotalUsd` is
        # included in the `.call()` response; fall back to a refetch if
        # missing (older SDK versions). Log-only for now — see task #15.
        run_cost_usd = run.get("usageTotalUsd")
        if run_cost_usd is None:
            try:
                run_cost_usd = client.run(run["id"]).get().get("usageTotalUsd")
            except Exception:
                log.debug("Could not fetch usageTotalUsd for run %s", run.get("id"))
        if run_cost_usd is not None:
            platform_cost_usd += float(run_cost_usd)

        log.info(
            "Collected %d items for %s / %s (cost=$%.4f)",
            len(items), b, piattaforma,
            float(run_cost_usd) if run_cost_usd is not None else 0.0,
        )

        # Observability: warn loudly if the actor ignored our cap.
        # This is how we caught the 2026-04-09 cost blowout.
        n_items_raw = len(items)
        cap_violated = n_items_raw > MAX_REVIEWS_PER_PROPERTY
        if cap_violated:
            log.warning(
                "CAP VIOLATED: %s/%s returned %d items, expected <= %d. "
                "Actor param likely wrong. Truncating to %d downstream.",
                piattaforma, b, n_items_raw, MAX_REVIEWS_PER_PROPERTY,
                MAX_REVIEWS_PER_PROPERTY,
            )
            items = items[:MAX_REVIEWS_PER_PROPERTY]

        # Persist run observability row (best-effort, never raises).
        # n_items = pre-truncation, so cost audits see the real blast radius.
        persist_apify_run(
            run_id=run["id"],
            piattaforma=piattaforma,
            business_unit_id=b,
            actor_id=actor_id,
            n_items=n_items_raw,
            cost_usd=float(run_cost_usd) if run_cost_usd is not None else None,
            cap_violated=cap_violated,
        )

        # Tag each item with BU for downstream processing
        for item in items:
            item["_bu"] = b
            item["_piattaforma"] = piattaforma

        all_items.extend(items)

    if not dry_run:
        log.info("APIFY COST %s: $%.4f", piattaforma, platform_cost_usd)

    return all_items, platform_cost_usd


def scrape_all(dry_run: bool = False) -> tuple[list[dict], float]:
    """Scrape all platforms, all BUs.

    Returns (items, total_cost_usd): combined raw items across platforms
    plus the summed usageTotalUsd. Cost is 0.0 in dry_run.
    """
    all_items = []
    total_cost = 0.0
    for piattaforma in APIFY_ACTORS:
        try:
            items, cost = scrape_platform(piattaforma, dry_run=dry_run)
            all_items.extend(items)
            total_cost += cost
        except Exception:
            log.exception("Failed to scrape %s", piattaforma)
    return all_items, total_cost
