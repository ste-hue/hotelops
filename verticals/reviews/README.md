# Reviews Vertical

Centralizza le guest reviews da 4 piattaforme OTA, classifica con NLP, alert immediato per negative, report settimanale.

## Come funziona

```
Apify (cloud)                    hotelops
─────────────                    ────────────────────────
booking-reviews-scraper    <──   reviews/scrape.py (trigger + collect)
tripadvisor-reviews        <──       |
google-maps-reviews        <──       v
expedia-scraper            <──   reviews/ingest.py (normalize + dedup)
                                     |
                                     v
                                 reviews/classify.py (Claude Haiku NLP)
                                     |  categoria + sentiment + riassunto
                                     v
                                 BigQuery: f_reviews (APPEND)
                                     |
                                     v
                                 reviews/alert.py (email se score <= 6/10)
```

## Pipeline giornaliero

```bash
# Scrape tutte le piattaforme + classifica + alert
hotelops reviews --scrape

# Solo una piattaforma
hotelops reviews --scrape --only booking

# Preview senza scraping reale
hotelops reviews --scrape --dry-run
```

Ogni run:
1. Triggera gli Apify actors nel cloud per ogni property/piattaforma
2. Normalizza i JSON in formato comune (punteggio 1-10, campi standard)
3. Dedup per `review_hash` (MD5 di piattaforma + review_id)
4. Classifica con Claude Haiku: categoria, sentiment, riassunto
5. Scrive in BigQuery `f_reviews` (APPEND, skip duplicati)
6. Se `punteggio_norm <= 6.0` -> email alert immediata

## Report settimanale

```bash
hotelops reviews --report
```

Email HTML con:
- Punteggio medio per piattaforma (trend vs settimana precedente)
- Totale reviews e % negative
- Top categorie problematiche
- Lista reviews negative con riassunto

## Dashboard

```bash
streamlit run reviews/app.py
```

Filtri: anno, piattaforma, BU, sentiment. KPI cards, trend mensile, breakdown categorie, tabella drill-down.

## Scheduling (automazione)

In produzione, Cloud Scheduler avvia due Cloud Run Jobs in `hotelops-suite`
(`europe-west1`):

| Job | Comando | Schedule (Europe/Rome) | Configurazione nel repo |
|---|---|---|---|
| `reviews-scrape` | `python -m cli reviews --scrape` | Ogni giorno alle 07:00 | [`scripts/cloud/20_reviews_scrape.sh`](../../scripts/cloud/20_reviews_scrape.sh) |
| `reviews-report` | `python -m cli reviews --report` | Lunedì alle 08:00 | [`scripts/cloud/30_reviews_report.sh`](../../scripts/cloud/30_reviews_report.sh) |

I job usano l'immagine batch `Dockerfile.jobs`, i secret runtime da Secret
Manager e il service account `hotelops-jobs@`. Gli script di configurazione
sono il riferimento per job, permessi e trigger; non copiare credenziali o
comandi di deploy da questa guida. Per esecuzioni manuali/locali, usa i comandi
`hotelops reviews` sopra.

## Piattaforme e Actors

| Piattaforma | Apify Actor | Costo ~1K rev | Reviews Hotel | Reviews Residence |
|---|---|---|---|---|
| Booking | `voyager/booking-reviews-scraper` | $2.00 | 664 | da verificare |
| TripAdvisor | `maxcopell/tripadvisor-reviews` | $5.00 | verificato | da verificare |
| Google | `compass/google-maps-reviews-scraper` | $0.60 | verificato | verificato |
| Expedia | `memo23/expedia-scraper` | $2.50 | 285 | da verificare |

**Costo totale stimato:** < $5/mese (poche centinaia di reviews per property).

## URLs configurate

Vedi `reviews/config.py` per la mappa completa. Status:

| BU | Booking | TripAdvisor | Google | Expedia |
|---|---|---|---|---|
| HOTEL | OK | OK | OK | OK |
| RESIDENCE | OK | OK | OK | OK |
| CVM | TODO | TODO | TODO | TODO |
| LIDO | N/A | N/A | TODO | N/A |

## Normalizzazione punteggio

| Piattaforma | Scala raw | Normalizzazione |
|---|---|---|
| Booking | 1-10 | passthrough |
| TripAdvisor | 1-5 | x 2 |
| Google | 1-5 | x 2 |
| Expedia | 1-10 | passthrough |

**Soglia alert:** `punteggio_norm <= 6.0`

## NLP Classification

Modello: Claude Haiku 4.5 (`claude-haiku-4-5-20251001`)

Categorie: PULIZIA, CIBO, STAFF, STRUTTURA, POSIZIONE, RUMORE, PREZZO, WIFI, ALTRO
Sentiment: POSITIVO, NEGATIVO, MISTO

Batch di 20 reviews per chiamata API. Costo: ~$0.01 per 100 reviews.

## Env vars

```bash
APIFY_API_TOKEN=apify_api_...    # Da https://console.apify.com/account/integrations
ANTHROPIC_API_KEY=sk-ant-...     # Per Claude API (classificazione NLP)
```

Salvare in `.env` nella root del progetto (gitignored).

## File structure

```
reviews/
  __init__.py
  config.py          # Actor IDs, URLs, thresholds, recipients
  scrape.py          # Apify SDK: trigger + collect
  ingest.py          # Normalize + dedup + BQ write
  classify.py        # Claude API: batch NLP classification
  alert.py           # Email alert per review negative
  email.py           # Report settimanale HTML + Gmail API
  app.py             # Streamlit dashboard
  cli_commands.py    # CLI handlers
  README.md          # Questo file
  PROPERTIES.md      # Reference tecnico actors + URLs
```

## CLI completo

```bash
hotelops reviews                           # Ultime 30 reviews, media, negative
hotelops reviews --scrape                  # Scrape tutte le piattaforme
hotelops reviews --scrape --only booking   # Solo Booking
hotelops reviews --scrape --dry-run        # Preview
hotelops reviews --stats                   # Stats mese corrente
hotelops reviews --stats --mese 3          # Stats mese specifico
hotelops reviews --alert                   # Review con alert inviato
hotelops reviews --report                  # Invia report settimanale
streamlit run reviews/app.py               # Dashboard interattiva
```
