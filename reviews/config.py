# reviews/config.py
"""Configuration for the reviews vertical."""

# Apify actor IDs
APIFY_ACTORS = {
    "BOOKING": "voyager/booking-reviews-scraper",
    "TRIPADVISOR": "maxcopell/tripadvisor-reviews",
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
