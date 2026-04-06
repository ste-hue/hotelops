# Reviews Vertical -- Design Spec

**Date:** 2026-04-06
**Status:** Draft
**Author:** Stefano + Claude

## Problem

Le reviews degli ospiti arrivano su 4 piattaforme diverse (Booking, TripAdvisor, Google, Expedia). Oggi nessuno le legge sistematicamente -- entrarci una per una e' una palla, e fare analisi NLP a fine anno e' troppo tardi. Serve un sistema nervoso: centralizzare tutto, segnalare subito le negative, dare visibilita' continua.

## Goals

1. **Centralizzare** tutte le reviews in un unico posto (BigQuery)
2. **Alert immediato** via email quando arriva una review negativa (<=6/10 o <=3/5)
3. **Classificare automaticamente** ogni review (categoria + sentiment) via Claude API
4. **Report settimanale** via email con trend e review negative
5. **Dashboard** Streamlit per analisi interattiva

## Non-Goals (per ora)

- WhatsApp/NanoClaw alert (futuro, quando c'e' un gruppo dedicato)
- Benchmark competitivo vs altri hotel
- Risposta automatica alle review
- Social media monitoring

## Architecture

### Vertical structure

```
reviews/
  scrape.py          # Apify SDK: trigger actors, collect results
  ingest.py          # Normalize + dedup + BQ write
  classify.py        # Claude API: categorize + summarize
  alert.py           # Email alert per review negative
  email.py           # Report settimanale HTML + invio Gmail API
  app.py             # Streamlit dashboard
  cli_commands.py    # CLI handlers
```

Segue il pattern degli altri vertical: directory dedicata, appoggiata su `core/` per config, schemas, BQ.

### Pipeline flow

```
Apify Actors (cloud)            hotelops
────────────────────            ─────────────────────────
                     API call
booking-reviews   <──────────   reviews/scrape.py
tripadvisor       <──────────     trigger + poll + collect
google-reviews    <──────────
expedia           <──────────
         |
         v JSON
reviews/ingest.py
  normalize (punteggio_norm, campi comuni)
  dedup (review_hash MD5)
         |
         v
reviews/classify.py
  Claude API (Haiku 4.5) per batch di review
  -> categoria_nlp, sentiment_nlp, riassunto_nlp
         |
         v
  core/schemas.py (ReviewRow validation)
         |
         v
  BigQuery: f_reviews (APPEND)
         |
         v
reviews/alert.py
  if punteggio_norm <= 6.0 -> email immediata
```

### Scheduling

- **Scrape + ingest + classify:** cron giornaliero (o 2x/giorno)
- **Report settimanale:** cron lunedi' mattina
- Apify actors girano nel loro cloud; noi facciamo trigger via API + collect JSON

## Data Model

### f_reviews (APPEND, dedup via review_hash)

| Campo | Tipo | Note |
|---|---|---|
| `review_hash` | STRING | MD5(piattaforma + review_id) -- chiave dedup |
| `piattaforma` | STRING | BOOKING, TRIPADVISOR, GOOGLE, EXPEDIA |
| `review_id` | STRING | ID originale dalla piattaforma |
| `societa_id` | STRING | ORTI, INTUR |
| `business_unit_id` | STRING | HOTEL, RESIDENCE, CVM, LIDO |
| `punteggio_raw` | FLOAT | Score originale (scala piattaforma) |
| `punteggio_norm` | FLOAT | Normalizzato 1-10 |
| `testo` | STRING | Testo completo review |
| `testo_positivo` | STRING | Pro (Booking split, NULL altrove) |
| `testo_negativo` | STRING | Contro (Booking split, NULL altrove) |
| `titolo` | STRING | Titolo review (se disponibile) |
| `lingua` | STRING | IT, EN, DE, FR, etc. |
| `data_review` | DATE | Data pubblicazione |
| `data_soggiorno` | DATE | Data soggiorno (se disponibile) |
| `reviewer_nome` | STRING | Nome reviewer |
| `reviewer_paese` | STRING | Nazionalita' reviewer |
| `tipo_viaggio` | STRING | COPPIA, FAMIGLIA, BUSINESS, SOLO, AMICI |
| `camera_tipo` | STRING | Tipo camera (se disponibile) |
| `url_review` | STRING | Link alla review originale |
| `categoria_nlp` | STRING | PULIZIA, CIBO, STAFF, STRUTTURA, POSIZIONE, RUMORE, PREZZO, WIFI, ALTRO |
| `sentiment_nlp` | STRING | POSITIVO, NEGATIVO, MISTO |
| `riassunto_nlp` | STRING | Riassunto breve da Claude API (max 1 frase) |
| `alert_inviato` | BOOL | True se email alert e' stata inviata |
| `data_ingest` | TIMESTAMP | Quando la review e' stata ingerita |

### Normalizzazione punteggio

| Piattaforma | Scala raw | Formula norm |
|---|---|---|
| Booking | 1-10 | punteggio_raw (gia' 1-10) |
| TripAdvisor | 1-5 | punteggio_raw * 2 |
| Google | 1-5 | punteggio_raw * 2 |
| Expedia | 1-10 | punteggio_raw (gia' 1-10) |

### Soglia alert

`punteggio_norm <= 6.0` -> alert email

## Apify Actors

| Piattaforma | Actor | Costo ~1K reviews | Note |
|---|---|---|---|
| Booking | `voyager/booking-reviews-scraper` | $2.00 | 1.56M runs, 99.8% success |
| TripAdvisor | `automation-lab/tripadvisor-scraper` | $3.00 | Nuovo ma funzionale |
| Google | `compass/google-maps-reviews-scraper` | $0.60 | 94M runs, dominante |
| Expedia | `memo23/expedia-scraper` | $2.50 | 46 users, 5 stelle |

Interazione via **Apify Python SDK** (`apify-client`):
- `ApifyClient.actor(actor_id).call(run_input)` per trigger
- Poll fino a completamento
- `client.dataset(dataset_id).list_items()` per raccogliere risultati

## NLP Classification (Claude API)

### Prompt

```
Sei un analista hotel. Classifica questa review.

Piattaforma: {piattaforma}
Punteggio: {punteggio_raw}/{scala_max}
Testo: {testo}

Rispondi SOLO con JSON valido:
{
  "categoria": "PULIZIA|CIBO|STAFF|STRUTTURA|POSIZIONE|RUMORE|PREZZO|WIFI|ALTRO",
  "sentiment": "POSITIVO|NEGATIVO|MISTO",
  "riassunto": "max 1 frase in italiano"
}
```

### Batch strategy

- Raggruppa fino a 20 review per singola chiamata API
- Modello: Claude Haiku 4.5 (veloce, economico, sufficiente per classificazione)
- Costo stimato: ~$0.01 per 100 review

## Email

### Alert review negativa (immediato)

**Da:** stefano@panoramagroup.it (Gmail API, gcloud auth)
**A:** stefano@panoramagroup.it (poi aggiungere direttore hotel)
**Oggetto:** `Review negativa — {BU} — {piattaforma} — {punteggio_raw}/{scala}`

**Corpo:**
```
Review negativa ricevuta

Piattaforma: Booking.com
Struttura: Hotel Panorama (HOTEL)
Punteggio: 4/10
Data review: 2026-04-05
Categoria: PULIZIA
Reviewer: John D. (UK)

Riassunto: Bagno sporco al check-in, asciugamani usati sul pavimento.

Testo completo:
[testo review]

Link: [url_review]
```

### Report settimanale (lunedi' mattina)

**Oggetto:** `Reviews settimanali — {data_inizio} / {data_fine}`

**Contenuto HTML:**
- Punteggio medio settimana per piattaforma (con trend vs settimana precedente)
- Totale review ricevute, di cui negative
- Top 3 categorie problematiche (barchart inline o tabella)
- Lista review negative con: piattaforma, punteggio, categoria, riassunto
- Link alla dashboard Streamlit per dettagli

## Dashboard Streamlit (reviews/app.py)

### Layout

**Sidebar:**
- Filtro piattaforma (multi-select)
- Filtro BU
- Filtro periodo (date range)
- Filtro sentiment
- Reload button

**Main area:**

1. **KPI cards (top):**
   - Punteggio medio (con delta vs mese precedente)
   - # review mese corrente
   - % review negative
   - Piattaforma con punteggio piu' basso

2. **Trend chart:**
   - Punteggio medio per mese, linea per piattaforma
   - Plotly line chart

3. **Categorie breakdown:**
   - Barchart orizzontale: # review per categoria NLP
   - Colore per sentiment (verde/rosso/giallo)

4. **Tabella review:**
   - Colonne: data, piattaforma, BU, punteggio, categoria, riassunto
   - Filtro rapido negativo/positivo
   - Click per espandere testo completo

## CLI

```bash
hotelops reviews                     # Ultime 30 review, media, # alert
hotelops reviews --scrape            # Trigger scrape manuale tutte le piattaforme
hotelops reviews --scrape --only booking  # Solo Booking
hotelops reviews --alert             # Mostra review che hanno generato alert
hotelops reviews --stats             # Stats mese corrente
hotelops reviews --stats --mese 3    # Stats mese specifico
hotelops reviews --report            # Genera e invia report settimanale manualmente
```

## Integration with core/

- `core/config.py`: aggiungere `F_REVIEWS = _t("f_reviews")`
- `core/schemas.py`: aggiungere `ReviewRow` Pydantic model
- `cli.py`: aggiungere subcomando `reviews` che delega a `reviews/cli_commands.py`
- `CLAUDE.md`: aggiungere sezione reviews vertical

## Dependencies (nuove)

- `apify-client` -- Apify Python SDK per trigger + collect
- `anthropic` -- Claude API per NLP classification (Haiku 4.5)
- Gmail API via `google-api-python-client` (o `google-cloud-gmail`)

## Configuration

```python
# reviews/config.py
APIFY_ACTORS = {
    "BOOKING": "voyager/booking-reviews-scraper",
    "TRIPADVISOR": "automation-lab/tripadvisor-scraper",
    "GOOGLE": "compass/google-maps-reviews-scraper",
    "EXPEDIA": "memo23/expedia-scraper",
}

# Property URLs/IDs per piattaforma -- da configurare
PROPERTIES = {
    "HOTEL": {
        "BOOKING": "https://www.booking.com/hotel/it/panorama-maiori.html",
        "TRIPADVISOR": "https://www.tripadvisor.com/...",
        "GOOGLE": "place_id:ChIJ...",
        "EXPEDIA": "https://www.expedia.com/...",
    },
    # RESIDENCE, CVM, LIDO...
}

ALERT_THRESHOLD = 6.0  # punteggio_norm <=
ALERT_RECIPIENTS = ["stefano@panoramagroup.it"]
REPORT_RECIPIENTS = ["stefano@panoramagroup.it"]
NLP_MODEL = "claude-haiku-4-5-20251001"
```

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Apify actor breaking (HTML changes) | Apify mantiene gli actors; se uno si rompe, fallback manuale. Monitor via success rate. |
| Rate limiting piattaforme | Apify gestisce proxy/throttling internamente |
| Costi Apify | Trascurabili: poche centinaia di review/mese, < $5/mese |
| Costi Claude API | Haiku 4.5 + batch: < $1/mese per volumi hotel |
| Gmail sending limits | 500 email/giorno -- abbondante per alert + 1 report/settimana |
| Review duplicate cross-platform | Dedup basato su piattaforma+review_id, non sul testo |
