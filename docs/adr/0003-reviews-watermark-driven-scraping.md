---
date: 2026-04-10
status: accepted
supersedes: none
subsystem: reviews
owner: stefano
---

# ADR 0003 — Reviews watermark-driven scraping

## Contesto

La pipeline reviews (`hotelops reviews --scrape`) aveva due bug collegati:

1. **`alert_inviato` colonna morta**. `alert.py` mandava la mail ma non
   aggiornava mai `alert_inviato` in `f_reviews`. Ogni rebuild/ripass
   dello scraper rimandava l'alert su review vecchie. Il 2026-04-10 sono
   partite 3 mail di alert per review negative di lug/ago/set 2025 —
   rumore puro.

2. **Scraping cieco**. Gli actor Apify ritornano le N più recenti e la
   pipeline normalizzava/classificava tutto passando per il dedup MD5 su
   `review_hash`. Nessun watermark: se fosse passato un mese, l'actor
   tornerebbe gli stessi 15 item già visti e Claude Haiku li ri-classificherebbe
   ogni volta. Spreco di classify + amplificazione del rumore alert.

Il requisito utente:

> voglio beccare una review nuova entro 24h se è ≤6, assorbire in BQ
> tutte quelle buone senza generare alert, e non sprecare scraping su
> giorni che ho già coperto.

## Decisione

Introduciamo un **watermark gate** derivato (non materializzato) da
`f_reviews`:

```sql
SELECT piattaforma, business_unit_id, MAX(data_review) AS watermark
FROM `hotelops-suite.hotelops.f_reviews`
WHERE LENGTH(data_review) = 10
GROUP BY piattaforma, business_unit_id
```

La funzione pura `filter_by_watermark(watermarks, items, cap)` vive in
`reviews/ingest.py` e droppa tutto ciò che è `<= watermark` per la sua
chiave, prima di classify/load/alert. Granularità chiave: `(piattaforma,
business_unit_id)`, che oggi coincide 1:1 con la property sulle OTA (non
c'è `property_id` in `f_reviews`).

Dopo l'invio della mail, `mark_alerts_sent(hashes)` esegue un UPDATE
parameterized su BQ per persistere `alert_inviato=TRUE`, chiudendo il
bug del flag morto:

```sql
UPDATE `f_reviews` SET alert_inviato = TRUE
WHERE review_hash IN UNNEST(@hashes)
```

Quando una chiave ritorna `len(kept) == cap` scatta un **gap alert** via
mail riepilogativa: potrebbero esserci review oltre il 16° item e
l'utente decide se rilanciare con cap più alto. **Niente auto-catchup**
per evitare loop costi Apify.

Per le **prime run** di una nuova `(piattaforma, bu)` (watermark `None`)
si applica una **grace window di 7 giorni** solo sugli alert, per evitare
di seedare la tabella con decine di mail storiche. I dati storici vengono
comunque caricati in BQ, ma non generano notifica.

`read_watermarks()` esegue anche una seconda query di audit che logga
`WATERMARK EXCLUDED N malformed data_review rows on <piattaforma>` per i
record con `LENGTH<>10`. Rende visibile il format drift Google pre-fix
finché il backfill non passa.

## Scoperta collaterale: param names Apify

Durante la ricognizione pre-implementazione abbiamo scritto
`reviews/inspect_actors.py` usando l'API Apify `client.actor(id).get()`
(le pagine Store sono JS-rendered e inaffidabili via scraping HTML).
Output: per ciascun actor, nome + version + `modifiedAt` + input schema.

Risultato del 2026-04-10: **3 dei 4 actor ignoravano i nostri param**:

| Piattaforma | Parametro sbagliato | Parametro atteso |
|---|---|---|
| BOOKING (voyager/booking-reviews-scraper 0.99) | `reviewsSort` | `sortReviewsBy` |
| TRIPADVISOR (maxcopell/tripadvisor-reviews 0.99) | `maxItems`, `language` | `maxItemsPerQuery`, `reviewsLanguages` |
| EXPEDIA (memo23/expedia-scraper 0.0) | `maxReviewsPerHotel`, `maxReviews` | `maxItems` |
| GOOGLE (compass/Google-Maps-Reviews-Scraper 1.0) | — | corretto |

Inoltre **tutti e 4 supportano un filtro data server-side**: `cutoffDate`
(BOOKING), `lastReviewDate` (TRIPADVISOR), `reviewsStartDate` (GOOGLE),
`reviewsFrom` (EXPEDIA). Possibile riduzione reale dei costi Apify in
futuro (oggi paghiamo pay-per-item anche per le review che droppiamo
client-side col watermark).

Il fix dei param names è **fuori scope** di questo ADR: va in un branch
separato `fix/apify-param-names` dopo il merge del watermark, per non
mescolare concerns. L'uso del date-filter server-side è un enhancement
da valutare dopo, una volta che i param names sono corretti.

## Alternative scartate

- **Solo flag-based (`alert_inviato`)**: fragile a rebuild di `f_reviews`,
  non protegge da duplicati di `review_hash` se `make_hash` cambia. La
  teniamo come belt-and-braces, non come gate primario.
- **Solo data-based (finestra rolling 24h)**: perde review se l'actor
  ritorna timestamp antico per review appena pubblicate sulla piattaforma.
- **Auto-catchup al gap** (rilancio automatico con cap più alto): rischio
  loop costi Apify. Preferito l'utente nel loop con mail manuale.
- **Tabella dedicata `d_reviews_watermark`** (materializzazione esplicita):
  prematura; il dato vive già in `f_reviews`. Quando arriverà
  `f_pipeline_runs` (Layer 2 del refactor) un watermark esplicito potrà
  stare lì come backup, ma non è bloccante.
- **Granularità watermark per `property_id`**: `f_reviews` non ha
  `property_id`, la property è mappata 1:1 su `business_unit_id`. Usare
  `business_unit_id` evita una colonna nuova e un backfill.
- **Filtro data server-side come primary gate**: dipenderebbe dalla
  disponibilità del param per ogni actor e potrebbe cambiare senza
  preavviso. Il filtro client-side rimane il gate authoritative; il
  server-side, quando arriverà, sarà un'ottimizzazione costi.

## Conseguenze

**Positive:**
- Nessuna mail duplicata su review storiche — bug risolto alla radice.
- Risparmio costo Claude Haiku: classifichiamo solo le nuove.
- Observability dei gap pre-catastrofe (`GAP SUSPECTED` log + mail).
- Audit del format drift (`WATERMARK EXCLUDED N malformed rows`).
- Separation of concerns in `alert.py`: `send_alerts` è pura, non muta
  più le righe; `mark_alerts_sent` è un'azione esplicita del caller.
- Scoperta param names Apify sbagliati (non avremmo mai indagato senza
  la ricognizione pre-implementazione).

**Negative / limitazioni (v1):**
- **Gap detection rigido** a `len(kept) == cap`. Una review cancellata
  lato piattaforma (14/15) non triggera il warning anche se c'è un gap
  vero; un 15/15 legittimo dopo un weekend di alto volume può generare
  falso allarme. Da rivedere dopo 2-4 settimane di `GAP SUSPECTED` log.
- **Crash window** tra `send_email` success e `mark_alerts_sent` UPDATE:
  se il processo crasha in mezzo, il prossimo run manda duplicato. Scelta
  consapevole: **alert duplicato > alert perso** nel contesto hotel ops.
- **Filtro `LENGTH=10` silenzioso** per i record malformati — mitigato
  dal log audit di `read_watermarks`, ma il dato resta fuori dal gate
  finché il backfill Google non passa.
- **Pay-per-item Apify non ridotto**: il cap 15 rimane, il filtro
  watermark è client-side. Il costo Apify è già coperto dal cap, il
  risparmio reale è su Claude Haiku + rumore alert. Riduzione vera dei
  costi Apify richiederà il server-side date filter (follow-up).

## Done criteria (verifica)

- [x] `filter_by_watermark()` pure function + 7 unit test (vuoto, hit,
      boundary, malformed, gap at-cap, gap below, multi-key)
- [x] `read_watermarks()` con audit query + 2 unit test (dict + empty)
- [x] `send_alerts(first_run_keys=...)` grace window 7gg
- [x] `mark_alerts_sent(hashes)` UPDATE parameterized
- [x] `send_gap_alert(gap_keys)` mail riepilogativa
- [x] `_cmd_scrape` rewire nell'ordine corretto (read → scrape →
      normalize → filter → classify → load → alert → mark → gap mail)
- [x] dry_run esercita comunque `read_watermarks` (validazione auth BQ)
- [x] Regression test: review negativa vecchia (lug 2025) bloccata dal watermark
- [x] `inspect_actors.py` eseguito → snapshot actor version + input schema
- [x] Runbook aggiornato (`last_verified`, bug ✅ risolto, actor table,
      watermark section, cost audit footnote)
- [x] ADR 0003 (questo documento)
- [ ] Live verification run contro BQ reale (Task 11 — manuale da
      Stefano perché serve gcloud auth attivo)

## Riferimenti

- Spec: `docs/superpowers/specs/2026-04-10-reviews-watermark-design.md`
- Plan: `docs/superpowers/plans/2026-04-10-reviews-watermark.md`
- Runbook: `docs/procedures/reviews_pipeline.md`
- Apify OpenAPI v2: `https://docs.apify.com/api/openapi.yaml`
- Commit range del branch `feat/reviews-watermark`: `d2ba338..8ebbd84`
