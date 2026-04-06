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
# See reviews/PROPERTIES.md for full reference.
PROPERTIES: dict[str, dict[str, str]] = {
    "HOTEL": {
        "BOOKING": "https://www.booking.com/hotel/it/panorama-maiori.html",
        "TRIPADVISOR": "https://www.tripadvisor.it/Hotel_Review-g194806-d23514860-Reviews-Hotel_Panorama-Maiori_Amalfi_Coast_Province_of_Salerno_Campania.html",
        "GOOGLE": "https://www.google.com/maps/search/?api=1&query=Hotel%20Panorama&query_place_id=ChIJoUcAhEGVOxMRe-U7t45iyGE",
        "EXPEDIA": "https://www.expedia.com/Maiori-Hotels-HOTEL-PANORAMA.h68690805.Hotel-Information",
    },
    "RESIDENCE": {
        "BOOKING": "https://www.booking.com/hotel/it/panorama-residence.html",
        "TRIPADVISOR": "https://www.tripadvisor.it/Hotel_Review-g194806-d14975421-Reviews-Angelina_Residence-Maiori_Amalfi_Coast_Province_of_Salerno_Campania.html",
        "GOOGLE": "https://www.google.com/maps/search/?api=1&query=Angelina%20Residence&query_place_id=ChIJAQCQLUKVOxMROoGIbplDgGs",
        "EXPEDIA": "https://www.expedia.com/Maiori-Hotels-Angelina-Residence.h5205793.Hotel-Information",
    },
    "CVM": {
        "BOOKING": "https://www.booking.com/hotel/it/casa-vacanze-maiori.html",
        "TRIPADVISOR": "https://www.tripadvisor.it/Hotel_Review-g194806-d14140532-Reviews-Casa_Vacanze_Maiori-Maiori_Amalfi_Coast_Province_of_Salerno_Campania.html",
        "GOOGLE": "https://www.google.com/maps/search/?api=1&query=Holiday%20Maiori&query_place_id=ChIJScCVV0aVOxMR9WheVKthBUc",
        "EXPEDIA": "",  # Non trovato su Expedia
    },
    # LIDO: probabilmente non presente sulle OTA
}

# Normalization: platform raw score -> 1-10 scale
SCORE_SCALE = {
    "BOOKING": 10.0,  # already 1-10
    "TRIPADVISOR": 5.0,  # 1-5 -> multiply by 2
    "GOOGLE": 5.0,  # 1-5 -> multiply by 2
    "EXPEDIA": 10.0,  # already 1-10
}

# Alert threshold (normalized 1-10)
ALERT_THRESHOLD = 6.0

# Email recipients
ALERT_RECIPIENTS = ["stefano@panoramagroup.it"]
REPORT_RECIPIENTS = ["stefano@panoramagroup.it"]

# Claude API model for NLP classification
NLP_MODEL = "claude-haiku-4-5-20251001"
NLP_BATCH_SIZE = 20  # reviews per API call
