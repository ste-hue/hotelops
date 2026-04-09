---
last_verified: 2026-04-09
code_paths:
  - reviews/scrape.py
  - reviews/ingest.py
  - reviews/classify.py
  - reviews/alert.py
  - reviews/email.py
  - reviews/config.py
  - core/schemas.py
subsystem: reviews
owner: stefano
---

# Reviews pipeline

Guest reviews da Booking / TripAdvisor / Google / Expedia → NLP → alert + dashboard.

## Flow

```
cron (crontab macchina stefano)
  └─ hotelops reviews --scrape
       ├─ reviews/scrape.py        Apify actor call, cap 15/property
       ├─ reviews/ingest.py        normalize → dedup (review_hash) → BQ f_reviews
       ├─ reviews/classify.py      Claude Haiku batch: categoria+sentiment+riassunto
       └─ reviews/alert.py         email negative (punteggio_norm ≤ 6.0)
```

BQ table: `hotelops-suite.hotelops.f_reviews` (APPEND, dedup per `review_hash`).

## Parametri attuali

- `MAX_REVIEWS_PER_PROPERTY = 15` (reviews/scrape.py)
- Soglia negativa: `punteggio_norm ≤ 6.0` (reviews/config.py / alert.py)
- Cron: 2x/giorno (14:00, 22:00) — __verificare crontab su host__
- Budget Apify: **$25/mese** (hard limit, oltre → alert)

## Actor Apify per piattaforma

| Piattaforma | Actor ID | Param "max" | Note |
|---|---|---|---|
| BOOKING | voyager/booking-reviews-scraper | `maxReviewsPerHotel` | __NON__ `maxReviews` (ignorato) |
| TRIPADVISOR | maxcopell/tripadvisor-reviews | `maxItems` | confermato 2026-04-09 |
| GOOGLE | compass/Google-Maps-Reviews-Scraper | `maxReviews` | confermato 2026-04-09 |
| EXPEDIA | memo23/expedia-scraper | `maxReviewsPerHotel` + `maxReviews` | __unconfirmed__, mandiamo entrambi |

Safety net: in `scrape_platform` se `len(items) > MAX_REVIEWS_PER_PROPERTY` logghiamo `CAP VIOLATED` e tronchiamo. È come abbiamo scoperto il blow-out costi del 2026-04-09.

## Stato BQ (snapshot 2026-04-09)

```
piattaforma  tot   prima       ultima       negative  alert_inviato
BOOKING      664   2024-03-31  2026-04-06   91        0
EXPEDIA      197   2024-04-13  2026-04-06   24        0
GOOGLE        42   2025-04-13  2026-03-03    3        0
TRIPADVISOR   10   2024-10-24  2025-10-17    0        0
```

## Decisioni storiche

- **2026-04-07**: rename `ALTRO → GENERICA` in `classify.py` (cat generica per review senza tema chiaro). __Drift__: `core/schemas.py` non aggiornato, cron rotto 2026-04-09. Fix: schemas.py + contract test (`tests/test_reviews_schema_sync.py`).
- **2026-04-07**: switch Gmail API OAuth → SMTP + app password. Più semplice.
- **2026-04-09**: `MAX_REVIEWS_PER_PROPERTY = 15` (era implicitamente ~300, cost blowout).
- **2026-04-09**: `ReviewRow.testo` può essere vuoto (Google/Booking ammettono star-only reviews).
- **2026-04-09**: `normalize_items` droppa review con `punteggio_norm ∉ [1,10]` (Google actor ritorna owner replies / Q&A artifacts senza stelle).
- **2026-04-09**: `normalize_google` trunca `publishedAtDate` a `[:10]` per allineare al formato delle altre piattaforme.

## Bug noti / debt (2026-04-09)

### 🔴 `alert_inviato` è una colonna morta
Nessun record ha mai `alert_inviato=true`. `alert.py` manda la mail e non aggiorna il flag.
Conseguenza: ogni volta che una review "vecchia" entra per la prima volta in BQ, rimanda l'alert.
Stamattina: 3 alert per review di lug/ago/set 2025 (Zuzana "nice place", etc) → rumore, non segnale.

### 🔴 Google ha 42 row totali, gap di 5+ settimane
`MAX(data_review)` Google = `2026-03-03`. Booking/Expedia sono a `2026-04-06`. Google era rotto ben prima del cron failure del 9 aprile — vanno capite le cause (actor timeout? url property cambiato? run fallivano silenziosamente?).

### 🟡 Format drift `data_review` su Google (pre-fix)
42 row Google esistenti hanno `data_review` come timestamp ISO (`2025-04-13T15:37:24.784Z`) invece di `YYYY-MM-DD`. Il fix in `normalize_google` vale solo per i nuovi. Backfill SQL pronto ma bloccato dallo streaming buffer del test manuale di stamattina — __rieseguire dopo 2026-04-10__:
```sql
UPDATE `hotelops-suite.hotelops.f_reviews`
SET data_review = SUBSTR(data_review, 1, 10)
WHERE piattaforma = 'GOOGLE' AND LENGTH(data_review) > 10
```

### 🟡 Expedia actor param name unconfirmed
Mandiamo sia `maxReviewsPerHotel` che `maxReviews`. Da verificare guardando un run reale nel dashboard Apify e vedere quale rispetta.

## Domande aperte di design (da risolvere)

### "Come sapere se il cron è girato ieri e non ha trovato niente?"

Oggi non lo sappiamo. `f_reviews` dice solo "quali review esistono", non "quando abbiamo provato a cercarle". Gap fondamentale.

**Soluzione corretta (senior)**: separare *run history* da *review data*.

```
f_pipeline_runs
  run_id             STRING
  pipeline_name      STRING    -- "reviews_scrape_google"
  started_at         TIMESTAMP
  ended_at           TIMESTAMP
  status             STRING    -- OK | FAIL | PARTIAL
  rows_found         INT64     -- quante review ha ritornato Apify
  rows_new           INT64     -- quante dopo dedup
  alerts_sent        INT64
  error              STRING
```

Con questa:
- "ieri hai scansionato?" → `WHERE pipeline='reviews_scrape_google' AND DATE(started_at)=CURRENT_DATE-1`
- "hai scansionato e trovato zero?" → stessa query, `rows_new=0, status='OK'`
- "ultima esecuzione riuscita?" → `MAX(started_at) WHERE status='OK'`
- "gap di giorni senza run?" → confronto con `GENERATE_DATE_ARRAY`
- Alert sistemici: "se l'ultima esecuzione OK è > 36h fa → mail a me"

### "Come scanniamo solo il nuovo, senza ripescare giorni già coperti?"

Due approcci, vanno combinati:

**A. Watermark per piattaforma** (stato implicito nei dati):
```sql
SELECT piattaforma, MAX(data_review) AS high_water
FROM f_reviews WHERE alert_inviato = TRUE
GROUP BY piattaforma
```
Alert solo su review con `data_review > high_water`. Richiede:
1. `alert_inviato` che venga __effettivamente scritto__ (bug 🔴 sopra)
2. Formato `data_review` coerente (bug 🟡 sopra)

**B. Watermark esplicito in `f_pipeline_runs`**: ogni run salva `max_data_review_visto`. Al run successivo, alert solo su review oltre quel watermark. Sopravvive anche a `f_reviews` vuota / rebuild.

La combinazione dà robustezza: A è auto-riparante dai dati, B è auto-riparante dallo stato del run.

### "Qual è il design che fa un genio?"

Tre principi:

1. **Stato esplicito, non implicito**. Non dedurre "abbiamo scannato ieri" da `data_review`. Scrivere una riga in `f_pipeline_runs` ogni volta. I dati rispondono a "cosa", lo stato a "quando abbiamo fatto cosa".

2. **Idempotenza per watermark, non per dedup hash**. Oggi deduplichiamo per `review_hash` (MD5 di piattaforma+review_id). Funziona ma è fragile: basta un change del `make_hash` e tutto viene reinserito. Meglio: (a) chiave naturale `(piattaforma, review_id)` come PK logica + (b) watermark che dice "da quando in poi considero le review come 'nuove'".

3. **Observability = la prima feature, non l'ultima**. `f_pipeline_runs` + un comando `hotelops health` che legge quello + un cron che alerta se sono passate > 36h dall'ultimo run OK. È la cosa che ci avrebbe salvato il 2026-04-09: il cron era rotto da 2 giorni e non l'avremmo saputo se io non avessi chiesto. Questo è il livello 2 del piano di refactor.

## Runbook

### Alert: "negative review via email ma è vecchia di 6 mesi"
Causa: `alert_inviato` non viene mai scritto (bug 🔴). Lo rileva il filtro `alert_inviato=false AND punteggio_norm ≤ 6.0` ad ogni run. Fix: `alert.py` deve `UPDATE f_reviews SET alert_inviato=true WHERE review_hash IN (...)` dopo l'invio. **TODO**.

### Alert: "review con `categoria_nlp=GENERICA` fallisce pydantic"
Drift schema/code. Controllare `tests/test_reviews_schema_sync.py`, garantisce allineamento tra `reviews/classify.VALID_CATEGORIE` e `core/schemas.CategoriaNlp`.

### "Il cron non ha mandato niente oggi"
1. `tail ~/cron-logs/reviews-daily-*.log`
2. `bq query 'SELECT MAX(data_ingest) FROM f_reviews'` — quando è stato l'ultimo insert?
3. Lock file: `ls /tmp/hotelops-reviews/` (daily lock, si pulisce da solo)
4. Manuale: `set -a; source .env; set +a; hotelops reviews --scrape`

### Cost blowout (Apify bill > $25/mese)
1. Check Apify dashboard → Runs → sort per cost
2. Log del run: cerca `CAP VIOLATED` → qualche actor ha ignorato il cap
3. Nel `_build_input` verifica nomi param per quel piattaforma
4. In staging: fai un dry-run con `count` e verifica quanti items torna

## TODO prioritari

1. 🔴 Fix `alert.py` → scrivere `alert_inviato=true` dopo invio. Regression test.
2. 🔴 Introduciamo `f_pipeline_runs` + PipelineRun context manager + integrazione in `reviews`, `ingest.flussi`, `ingest.banca`. Layer 2 del piano refactor.
3. 🟡 Backfill `data_review` Google (dopo 2026-04-10, streaming buffer free).
4. 🟡 Verificare perché Google era rotto prima del 9 aprile (gap 5+ settimane).
5. 🟡 Confermare param name Expedia actor.
6. 🟢 Cron health check: se `MAX(data_ingest)` più vecchio di 36h → mail.
