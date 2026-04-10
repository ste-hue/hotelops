---
last_verified: 2026-04-10
code_paths:
  - reviews/scrape.py
  - reviews/ingest.py
  - reviews/classify.py
  - reviews/alert.py
  - reviews/email.py
  - reviews/config.py
  - reviews/cli_commands.py
  - reviews/inspect_actors.py
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
       ├─ reviews/ingest.read_watermarks   (prima di tutto; abort su BQ fail)
       ├─ reviews/scrape.py                Apify actor call, cap 15/property
       ├─ reviews/ingest.normalize_items   piattaforma-specific normalize
       ├─ reviews/ingest.dedup_reviews     MD5 review_hash dedup
       ├─ reviews/ingest.filter_by_watermark  droppa ≤ watermark, flag gap
       ├─ reviews/classify.py              Claude Haiku (solo nuove, post-filter)
       ├─ reviews/ingest.load_to_bq        insert in f_reviews
       ├─ reviews/alert.send_alerts        grace window 7gg per first-run keys
       ├─ reviews/alert.mark_alerts_sent   UPDATE alert_inviato=TRUE post-SMTP
       └─ reviews/alert.send_gap_alert     mail riepilogativa se gap rilevato
```

BQ table: `hotelops-suite.hotelops.f_reviews` (APPEND, dedup per `review_hash`).

Lo state del watermark vive **implicitamente in `f_reviews`** via
`MAX(data_review) GROUP BY (piattaforma, business_unit_id)`. Nessuna
tabella separata (un watermark esplicito arriverà col Layer 2
`f_pipeline_runs`, vedi sotto).

## Parametri attuali

- `MAX_REVIEWS_PER_PROPERTY = 15` (reviews/scrape.py)
- Soglia negativa: `punteggio_norm ≤ 6.0` (reviews/config.py / alert.py)
- `GRACE_WINDOW_DAYS = 7` (reviews/alert.py) — solo per first-run keys
- Cron: 2x/giorno (14:00, 22:00) — __verificare crontab su host__
- Budget Apify: **$25/mese** (hard limit, oltre → alert)

## Actor Apify per piattaforma

**Snapshot via `python -m reviews.inspect_actors` del 2026-04-10** (usa
l'API Apify `client.actor(id).get()` — è l'unica fonte authoritative,
le pagine Store sono JS-rendered e inaffidabili).

| Piattaforma | Actor ID | Version | Max-cap param atteso | Date-filter param | Stato `scrape.py` |
|---|---|---|---|---|---|
| BOOKING | voyager/booking-reviews-scraper | 0.99 | `maxReviewsPerHotel` | `cutoffDate` | ✅ `sortReviewsBy` (fix 2026-04-10) |
| TRIPADVISOR | maxcopell/tripadvisor-reviews | 0.99 | `maxItemsPerQuery` | `lastReviewDate` | ✅ `maxItemsPerQuery`, lingua omessa (fix 2026-04-10) |
| GOOGLE | compass/Google-Maps-Reviews-Scraper | 1.0 | `maxReviews` | `reviewsStartDate` | ✅ corretto |
| EXPEDIA | memo23/expedia-scraper | 0.0 | `maxItems` | `reviewsFrom` | ✅ `maxItems` (fix 2026-04-10) |

Fix applicato in `fix/apify-param-names` (2026-04-10): 6 unit test in
`tests/test_reviews_scrape.py` verificano l'input emesso per ogni
piattaforma contro lo schema live. Rieseguire `inspect_actors.py`
periodicamente per intercettare drift futuro.

Safety net: in `scrape_platform` se `len(items) > MAX_REVIEWS_PER_PROPERTY`
logghiamo `CAP VIOLATED` e tronchiamo. Così abbiamo scoperto il blow-out
costi del 2026-04-09.

Per ri-ispezionare gli actor in futuro (e verificare che i param non
siano cambiati versione):
```bash
export APIFY_API_TOKEN=...
python -m reviews.inspect_actors               # tutti
python -m reviews.inspect_actors --only BOOKING
```
Stampa nome + version + modifiedAt + input schema. Il `version` è
l'ancora: se l'actor bumpa e il param scompare, sai rispetto a quale
build era scritto il nostro codice.

### Audit costo di una run Apify (futuro — task #15)

L'endpoint non deprecato `GET /v2/actor-runs/{runId}` ritorna
`data.usageTotalUsd` (float USD) + `data.usage` (12 dimensioni metered:
ACTOR_COMPUTE_UNITS, DATASET_READS/WRITES, KEY_VALUE_STORE_*,
REQUEST_QUEUE_*, DATA_TRANSFER_*, PROXY_*) + `data.usageUsd` (breakdown
per dimensione). Via SDK:
```python
from apify_client import ApifyClient
client = ApifyClient(token)
run = client.actor(actor_id).call(run_input=...)  # ritorna già il runId
cost = client.run(run["id"]).get().get("usageTotalUsd")
```
**Richiede token auth** — senza token i campi `usageUsd`/`usageTotalUsd`
sono nascosti. Da cablare nel pipeline come log post-run + eventuale
comando `hotelops reviews --cost-audit <runId>` per analisi on-demand.
Non in scope del watermark branch.

## Stato BQ (snapshot 2026-04-09, pre-watermark)

```
piattaforma  tot   prima       ultima       negative  alert_inviato
BOOKING      664   2024-03-31  2026-04-06   91        0
EXPEDIA      197   2024-04-13  2026-04-06   24        0
GOOGLE        42   2025-04-13  2026-03-03    3        0
TRIPADVISOR   10   2024-10-24  2025-10-17    0        0
```

Il `alert_inviato=0` ovunque era il sintomo del bug risolto nel 2026-04-10.
Dopo il primo run post-fix il contatore `alert_inviato` deve iniziare a
riflettere le mail effettivamente inviate (verifica manuale in Task 11).

## Watermark gate (2026-04-10+)

Pipeline `hotelops reviews --scrape`:

1. **`read_watermarks()`** — query `SELECT piattaforma, business_unit_id, MAX(data_review) FROM f_reviews WHERE LENGTH(data_review)=10 GROUP BY ...`. Ritorna `dict[(str, str), str]`. In dry_run viene comunque eseguita (valida auth/connettività BQ) e su fallimento degrada a dict vuoto con WARNING; in produzione un fallimento aborta la run. Esegue anche una seconda query di audit che logga `WATERMARK EXCLUDED N malformed data_review rows on <piattaforma>` per i record con `LENGTH(data_review)<>10` (il format drift Google pre-fix).
2. **scrape** — invariato, cap 15/property.
3. **`normalize_items` + `dedup_reviews`** — invariato.
4. **`first_run_keys`** calcolato BEFORE il filter: `{k for k in present_keys if k not in watermarks}` — serve ad `alert.py` per applicare la grace window.
5. **`filter_by_watermark(watermarks, items, cap)`** — pure function, droppa items con `data_review <= watermark` per la loro `(piattaforma, bu)`; droppa malformed date (log warning per count aggregato); popola `gap_keys` con tutte le chiavi per cui `len(kept)==cap` (possibili review oltre il 16° item).
6. **Se 0 nuove** → skip classify/load/alert. Se ci sono `gap_keys`, manda comunque la mail riepilogativa e return.
7. **`classify_reviews`** (solo nuove) — risparmio costo Claude Haiku.
8. **`load_to_bq`** — insert.
9. **`send_alerts(new_rows, first_run_keys=first_run_keys)`** — filtra `punteggio_norm <= 6.0 AND alert_inviato=false`. Per le chiavi in `first_run_keys` applica anche la grace window 7gg (`data_review >= today - 7`) per evitare mail di massa al seed di una nuova property. NON muta più le righe — ritorna solo la lista degli alertati.
10. **`mark_alerts_sent([r["review_hash"] for r in alerted])`** — UPDATE parameterized `WHERE review_hash IN UNNEST(@hashes)`. Chiamato DOPO che `send_alerts` ritorna con successo: se l'SMTP crasha mid-loop il flag non viene scritto e al prossimo run ritenta.
11. **`send_gap_alert(gap_keys)`** — mail riepilogativa con la lista `(piattaforma, bu)` a cap pieno, suggerisce rilancio manuale con cap più alto.

### Gap detection

Quando `len(kept) == cap` per una chiave, c'è il sospetto che ci siano
review oltre il 16° item che l'actor non ci ha ritornato. Mail ad
`ALERT_RECIPIENTS`, la decisione di rilancio è manuale — **no auto-catchup**
per evitare loop costi Apify. Limitazione nota v1: euristica rigida, un
14/15 legittimo non triggera, e un 15/15 legittimo dopo un weekend di alto
volume può generare falso allarme. Da rivedere dopo 2-4 settimane di dati
reali osservando i `GAP SUSPECTED` log.

### Grace window

Solo per chiavi `(piattaforma, bu)` che non avevano watermark (prima run
di una nuova property). Reviews più vecchie di `today - 7gg` non vengono
alertate al seed — la tabella si popola, ma non ricevi 50 mail storiche.
Per le chiavi che invece hanno già un watermark, tutte le nuove negative
vengono alertate senza finestra.

### Crash window (scelta consapevole)

Tra `send_email` success e `mark_alerts_sent` UPDATE c'è una finestra in
cui un crash del processo fa ripartire l'alert al run successivo. Scelta
di design: **alert duplicato > alert perso** nel contesto hotel ops. Se
diventasse un problema, la mitigazione è spostare il flag scritto in una
CTE transazionale prima dell'SMTP, ma oggi non serve.

## Decisioni storiche

- **2026-04-07**: rename `ALTRO → GENERICA` in `classify.py` (cat generica per review senza tema chiaro). __Drift__: `core/schemas.py` non aggiornato, cron rotto 2026-04-09. Fix: schemas.py + contract test (`tests/test_reviews_schema_sync.py`).
- **2026-04-07**: switch Gmail API OAuth → SMTP + app password. Più semplice.
- **2026-04-09**: `MAX_REVIEWS_PER_PROPERTY = 15` (era implicitamente ~300, cost blowout).
- **2026-04-09**: `ReviewRow.testo` può essere vuoto (Google/Booking ammettono star-only reviews).
- **2026-04-09**: `normalize_items` droppa review con `punteggio_norm ∉ [1,10]` (Google actor ritorna owner replies / Q&A artifacts senza stelle).
- **2026-04-09**: `normalize_google` trunca `publishedAtDate` a `[:10]` per allineare al formato delle altre piattaforme.

## Bug noti / debt

### ✅ `alert_inviato` — RISOLTO 2026-04-10
Risolto introducendo `mark_alerts_sent()` in `alert.py` che esegue
`UPDATE f_reviews SET alert_inviato=TRUE WHERE review_hash IN UNNEST(@hashes)`
dopo ogni mail inviata con successo. Oltre al flag, la pipeline ora ha
un watermark gate (`MAX(data_review)` per `(piattaforma, business_unit_id)`)
che droppa le review già viste prima ancora di arrivare all'alert, quindi
anche se il flag non fosse scritto (crash window) il watermark tiene la
seconda linea di difesa. Vedi ADR 0003 e
`docs/superpowers/specs/2026-04-10-reviews-watermark-design.md`.
Regression test: `tests/test_reviews_watermark.py::test_regression_old_negative_review_blocked_by_watermark`.

### ✅ Param names Apify — RISOLTO 2026-04-10
Scoperto il 2026-04-10 via `reviews/inspect_actors.py`: BOOKING,
TRIPADVISOR, EXPEDIA mandavano parametri ignorati silenziosamente.
La live run di smoke-test del watermark branch lo ha reso tangibile:
Expedia RESIDENCE ha restituito 226 items invece di 15 (cap violated,
pay-per-item). Fix in branch `fix/apify-param-names`:
- BOOKING: `reviewsSort` → `sortReviewsBy`
- TRIPADVISOR: `maxItems` + `language:"ALL"` → `maxItemsPerQuery`, lingua omessa
- EXPEDIA: `maxReviewsPerHotel` + `maxReviews` → `maxItems`
- GOOGLE: invariato (già corretto)

6 unit test in `tests/test_reviews_scrape.py` bloccano regressioni.

### 🔴 Google ha 42 row totali, gap di 5+ settimane (ancora aperto)
`MAX(data_review)` Google pre-watermark = `2026-03-03`. Booking/Expedia
a `2026-04-06`. Causa root non identificata (actor timeout? url property
cambiato? run fallivano silenziosamente?). Con il watermark gate adesso
il prossimo run su Google pescherà tutto ciò che è `> 2026-03-03` — se il
gap era dovuto a scraping rotto e non a mancanza di review reali, dovremmo
vederlo nel prossimo run. Da monitorare.

### ✅ Format drift `data_review` su Google — RISOLTO 2026-04-10
42 row Google esistenti avevano `data_review` come timestamp ISO
(`2025-04-13T15:37:24.784Z`) invece di `YYYY-MM-DD`. Il fix in
`normalize_google` vale per i nuovi; il backfill SQL ha sistemato gli
esistenti dopo il merge del watermark branch:
```sql
UPDATE `hotelops-suite.hotelops.f_reviews`
SET data_review = SUBSTR(data_review, 1, 10)
WHERE piattaforma = 'GOOGLE' AND LENGTH(data_review) > 10
-- 42 rows affected
```
Post-fix: `read_watermarks` restituisce 11 chiavi invece di 8 (le 3
GOOGLE BU ora materializzano MAX(data_review)), il log
`WATERMARK EXCLUDED` è muto, e il prossimo cron eviterà i 42 Haiku
sprecati a ri-classificare GOOGLE storici.

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
**Risolto 2026-04-10** (vedi bug ✅ sopra + ADR 0003). Se succede di nuovo dopo il fix, le cause possibili sono:
1. `mark_alerts_sent` fallito post-SMTP (crash window): controlla il log per `mark_alerts_sent: flagged N reviews`. Se manca la riga ma la mail è arrivata, c'è stato un crash in mezzo — rieseguire `hotelops reviews --scrape` una volta, il filtro `alert_inviato=false` tiene il duplicato.
2. Watermark non letto: controlla log per `read_watermarks: N keys`. Se manca, la run è abortita o `read_watermarks` ha ritornato dict vuoto.
3. `data_review` malformato: la review ha `LENGTH(data_review)<>10` quindi esclusa dal watermark → considerata "nuova". Cerca `WATERMARK EXCLUDED` nel log. Fix: backfill Google (vedi 🟡 sopra).

### Gap suspected su (piattaforma, bu)
Mail riepilogativa con oggetto `[hotelops] GAP SUSPECTED reviews — N chiavi`. Significa che `filter_by_watermark` ha trovato `len(kept)==cap` per quelle chiavi, quindi **potrebbero** esserci review oltre il 16° item non catturate. Decisione manuale:
1. Valuta se è legittimo (weekend di alto volume su Hotel ad Agosto) o sospetto (primo gap dopo mesi di pipeline tranquilla).
2. Se sospetto: `APIFY_MAX_REVIEWS_OVERRIDE=50 hotelops reviews --scrape --only <piattaforma>` (feature non ancora implementata — TODO: env var override del cap). In alternativa: modifica temporaneamente `MAX_REVIEWS_PER_PROPERTY` in `reviews/scrape.py` e rilancia.
3. Se pattern ricorrente: rivedere l'euristica `len(kept)==cap` (limitazione v1 nota).

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

1. ✅ ~~Fix `alert.py` → scrivere `alert_inviato=true` dopo invio~~ — risolto 2026-04-10 (watermark gate + `mark_alerts_sent` + regression test).
2. ✅ ~~Branch `fix/apify-param-names`~~ — risolto 2026-04-10. BOOKING `sortReviewsBy`, TRIPADVISOR `maxItemsPerQuery` (lingua omessa), EXPEDIA `maxItems`. 6 unit test in `tests/test_reviews_scrape.py`.
3. 🔴 Introdurre `f_pipeline_runs` + PipelineRun context manager (Layer 2 refactor). Sblocca: "il cron è girato ieri?", watermark esplicito come backup, alert "ultimo run OK > 36h fa".
4. ✅ ~~Backfill `data_review` Google~~ — fatto 2026-04-10, 42 row sistemate, watermarks GOOGLE ora materializzati.
5. 🟡 Verificare perché Google era rotto prima del 9 aprile (gap 5+ settimane). Il primo run post-watermark ci dirà se era il scraping o se le review reali mancavano.
6. 🟡 **Cost tracking** via `GET /v2/actor-runs/{runId}` → `usageTotalUsd`. Task #15 nel tracker. Log post-run + comando `hotelops reviews --cost-audit <runId>`.
7. 🟡 Env var override del cap per gap recovery manuale (`APIFY_MAX_REVIEWS_OVERRIDE=50`).
8. 🟡 Rivedere euristica gap detection dopo 2-4 settimane di dati reali (`GAP SUSPECTED` log pattern).
9. 🟢 Cron health check: se `MAX(data_ingest)` più vecchio di 36h → mail.
