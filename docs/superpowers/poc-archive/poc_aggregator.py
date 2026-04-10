"""POC: Apify Hotel Review Aggregator (tri_angle/hotel-review-aggregator).

Goal: measure cost + output schema + coverage for a SINGLE property run
against a tight date window, so we can compare vs the current 4-actor
pipeline without spending real money.

Hard budget: $1. Single run, HOTEL only, 10-day window.
No writes to f_reviews, no classify, no email. JSON dump only.

Run:
  python -m reviews.poc_aggregator
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from apify_client import ApifyClient

log = logging.getLogger("poc_aggregator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ACTOR_SLUG = "tri_angle/hotel-review-aggregator"

# HOTEL Panorama Maiori. Extracted from reviews/config.py GOOGLE URL
# query_place_id parameter.
HOTEL_PLACE_ID = "ChIJoUcAhEGVOxMRe-U7t45iyGE"

# 10-day window. Conservative to bound cost since the actor has no maxItems cap.
REVIEWS_FROM_DATE = "2026-04-01"

# Our current providers, mapped to aggregator enum.
PROVIDERS = ["google-maps", "tripadvisor", "booking", "expedia"]

# Hard safety limits.
TIMEOUT_SECS = 120
MAX_SPEND_USD = 1.0

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "poc_output_hotel.json"


def main() -> int:
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        log.error("APIFY_API_TOKEN not set")
        return 1

    client = ApifyClient(token)

    run_input = {
        "startIds": [HOTEL_PLACE_ID],
        "providers": PROVIDERS,
        "reviewsFromDate": REVIEWS_FROM_DATE,
        "scrapeReviewPictures": False,
        "scrapeReviewResponses": False,
    }

    log.info("Starting aggregator run with input: %s", json.dumps(run_input))
    t0 = time.time()

    run = client.actor(ACTOR_SLUG).call(
        run_input=run_input,
        timeout_secs=TIMEOUT_SECS,
    )

    elapsed = time.time() - t0
    log.info("Run finished in %.1fs — status: %s", elapsed, run.get("status"))

    # Pull cost data
    run_detail = client.run(run["id"]).get()
    cost_usd = run_detail.get("usageTotalUsd")
    log.info("Cost: $%.4f (cap: $%.2f)", cost_usd or 0.0, MAX_SPEND_USD)

    if cost_usd is not None and cost_usd > MAX_SPEND_USD:
        log.error("BUDGET EXCEEDED: $%.4f > $%.2f", cost_usd, MAX_SPEND_USD)
        # Still proceed to dump what we got so the spend isn't wasted.

    # Pull all dataset items
    dataset_id = run["defaultDatasetId"]
    items = list(client.dataset(dataset_id).iterate_items())
    log.info("Collected %d items from dataset", len(items))

    # Per-provider breakdown
    by_provider: dict[str, int] = {}
    for it in items:
        p = it.get("provider", "unknown")
        by_provider[p] = by_provider.get(p, 0) + 1
    log.info("Breakdown: %s", by_provider)

    # Date range of returned items
    dates = sorted([it.get("reviewDate", "") for it in items if it.get("reviewDate")])
    if dates:
        log.info("Date range: %s → %s", dates[0], dates[-1])

    # Dump to JSON
    payload = {
        "actor": ACTOR_SLUG,
        "run_id": run["id"],
        "build_id": run.get("buildId"),
        "input": run_input,
        "status": run.get("status"),
        "elapsed_secs": round(elapsed, 1),
        "cost_usd": cost_usd,
        "n_items": len(items),
        "by_provider": by_provider,
        "items": items,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, default=str))
    log.info("Dumped %d items + metadata to %s", len(items), OUTPUT_PATH)

    return 0


if __name__ == "__main__":
    sys.exit(main())
