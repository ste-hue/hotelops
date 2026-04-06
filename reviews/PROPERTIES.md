# Reviews Vertical — Property & Scraper Reference

## Cos'e' un Actor Apify?

Un **Actor** e' un programma che gira nel cloud di Apify. Tu gli dai un URL (es. la pagina Booking dell'hotel) e lui fa lo scraping delle reviews, restituendoti un JSON pulito con testo, punteggio, data, etc. Paghi pochi centesimi per run. Non devi mantenere nessun codice di scraping.

**Come funziona il flusso:**
1. `reviews/scrape.py` chiama l'API Apify con l'URL della property
2. Apify lancia l'Actor nel suo cloud, fa lo scraping
3. Noi raccogliamo il JSON risultante
4. `reviews/ingest.py` normalizza i dati in formato comune
5. `reviews/classify.py` classifica con Claude API (categoria + sentiment)
6. Salva tutto in BigQuery (`f_reviews`)
7. Se punteggio <= 6/10: email alert immediata

## Actors che usiamo

| Piattaforma | Actor Apify | Costo ~1K reviews | Runs totali | Note |
|---|---|---|---|---|
| Booking.com | `voyager/booking-reviews-scraper` | $2.00 | 1.56M | Testo + pro/contro separati |
| TripAdvisor | `maxcopell/tripadvisor-reviews` | $5.00 | 6.2M | Standard de facto |
| Google | `compass/google-maps-reviews-scraper` | $0.60 | 94M | Il piu' usato in assoluto |
| Expedia | `memo23/expedia-scraper` | $2.50 | 1.5K | Piu' piccolo ma funziona |

## Property URLs

### HOTEL — Hotel Panorama (Maiori)

| Piattaforma | URL | Status |
|---|---|---|
| Booking | https://www.booking.com/hotel/it/panorama-maiori.html | OK |
| TripAdvisor | https://www.tripadvisor.it/Hotel_Review-g194806-d23514860-Reviews-Hotel_Panorama-Maiori_Amalfi_Coast_Province_of_Salerno_Campania.html | OK |
| Google | TODO — mandare link Google Maps con place_id | Da fare |
| Expedia | https://www.expedia.com/Maiori-Hotels-HOTEL-PANORAMA.h68690805.Hotel-Information | OK |

### RESIDENCE — Angelina Residence (Maiori)

| Piattaforma | URL | Status |
|---|---|---|
| Booking | https://www.booking.com/hotel/it/panorama-residence.html | OK |
| TripAdvisor | https://www.tripadvisor.it/Hotel_Review-g194806-d14975421-Reviews-Angelina_Residence-Maiori_Amalfi_Coast_Province_of_Salerno_Campania.html | OK |
| Google | TODO — mandare link Google Maps con place_id | Da fare |
| Expedia | https://www.expedia.com/Maiori-Hotels-Angelina-Residence.h5205793.Hotel-Information | OK |

### CVM — Casa Vacanze Maiori

| Piattaforma | URL | Status |
|---|---|---|
| Booking | TODO | Da verificare se ha pagina propria |
| TripAdvisor | TODO | Da verificare |
| Google | TODO | Da verificare |
| Expedia | TODO | Da verificare |

### LIDO — Spiaggia

Probabilmente non presente sulle OTA (non si "prenota" una spiaggia). Ha reviews su Google Maps? Da verificare.

## Env vars necessarie

```bash
export APIFY_API_TOKEN="..."      # Da https://console.apify.com/account/integrations
export ANTHROPIC_API_KEY="..."    # Per Claude API (classificazione NLP)
```

## Costi stimati

- **Apify:** < $5/anno (poche centinaia di reviews per property)
- **Claude API (Haiku):** < $1/anno per classificazione
- **Totale:** < $6/anno
