---
date: 2026-04-10
subsystem: reviews
owner: stefano
status: draft
supersedes: none
code_paths:
  - reviews/scrape.py
  - reviews/ingest.py
  - reviews/classify.py
  - reviews/alert.py
  - reviews/config.py
  - core/schemas.py
---

# Reviews pipeline — watermark-driven scraping & alert dedup

## Problema

Oggi la pipeline reviews ha due bug collegati:

1. **`alert_inviato` è colonna morta**. `alert.py` manda la mail e non aggiorna mai il
   flag. Ogni review "vecchia" che rientra in `f_reviews` per qualunque motivo (rebuild,
   actor che ripassa storici, cambio `make_hash`) rimanda l'alert. Il 2026-04-10 sono
   arrivate 3 mail per review di lug/ago/set 2025.

2. **Scraping cieco**. Gli actor tornano le N più recenti e noi le passiamo tutte al
   dedup per `review_hash`. Non c'è nessun watermark: se fosse passato un mese, l'actor
   tornerebbe i soliti 15 items già visti. Spreco di classify (Claude Haiku) e rumore.

Il requisito utente: *"voglio beccare una review nuova entro 24h se è ≤6, assorbire in
BQ tutte quelle buone senza generare alert, e non sprecare scraping su giorni che ho
già coperto"*.

## Decisioni di design

- **Watermark derivato, non materializzato**. Lo stato vive in `f_reviews` stesso via
  `MAX(data_review) GROUP BY (piattaforma, business_unit_id)`. Nessuna tabella nuova
  in questa fase. Quando arriverà `f_pipeline_runs` (Layer 2 del refactor) potremo
  salvare un watermark esplicito come backup.
- **Granularità watermark = `business_unit_id`**. Oggi `f_reviews` non ha
  `property_id`; la property è mappata su `business_unit_id` (HOTEL, RESIDENCE, CVM,
  LIDO). Va bene: ogni BU mappa 1:1 con una property sulle OTA.
- **Filtro locale in `normalize_items`**. Nessuna dipendenza da parametri actor-specific.
  Funziona per tutte e 4 le piattaforme oggi.
- **Alert gating via watermark + flag**. Il watermark è la primary gate (dati
  cannot-lie). Il flag `alert_inviato=true` viene scritto dopo invio come belt-and-
  braces contro rebuild di `f_reviews`.
- **Grace window per prima run**. Se una property non è mai stata ingerita prima
  (watermark vuoto), `alert.py` filtra su `data_review >= CURRENT_DATE - 7` per
  seedarla senza spammare alert storici.
- **Gap detection = mail, non auto-catchup**. Se in una run tutti i 15 items tornati
  superano il watermark, log warning + mail "gap sospetto". Utente decide se
  rilanciare con cap più alto. Evita loop costi e mantiene l'utente nel loop.
- **Pay-per-item Apify già coperto dal cap**. Il cap `MAX_REVIEWS_PER_PROPERTY=15`
  risolve il problema costi per costruzione. Il filtro locale non riduce ulteriormente
  il costo Apify (gli items sono già stati pagati al ritorno), ma elimina costo
  Claude + rumore alert.
- **Ricognizione preliminare actor**. Prima di implementare, verifico README Apify di
  ciascun actor per un eventuale parametro `reviewsStartDate` / equivalente. Se esiste
  → filtro server-side (risparmio reale). Se no → filtro client-side come previsto.

## Architettura

Tre responsabilità separate nel modulo `reviews/`:

```
scrape.py    chiama actor, ritorna raw items (cap 15)
             |
             v
ingest.py    normalize_items → filter_by_watermark → dedup MD5 → BQ insert
             ritorna lista di NewReview (solo review effettivamente nuove)
             |
             v
alert.py     riceve lista nuove, filtra punteggio_norm ≤ 6,
             applica grace window se prima run, manda mail,
             UPDATE f_reviews SET alert_inviato=true WHERE review_hash IN (...)
```

La funzione nuova `filter_by_watermark(watermarks, items)` vive in `ingest.py`.

## Data flow (happy path)

1. **Leggi watermark** (prima di qualunque scrape):
   ```sql
   SELECT piattaforma, business_unit_id, MAX(data_review) AS watermark
   FROM `hotelops-suite.hotelops.f_reviews`
   WHERE LENGTH(data_review) = 10  -- guard contro format drift Google pre-fix
   GROUP BY piattaforma, business_unit_id
   ```
   Output: `dict[(piattaforma, business_unit_id), str]` (`data_review` è stringa
   ISO `YYYY-MM-DD` per schema, confronto lessicografico = cronologico).

2. **Scrape** (invariato): ogni actor ritorna fino a 15 items recenti.

3. **Normalize + filter**: per ogni item,
   - normalizza `data_review` a stringa `YYYY-MM-DD`
   - se `data_review <= watermarks.get((p, bu))` → scarta (già visto)
   - se `data_review > watermark` o watermark `None` → tieni

4. **Gap detection**: per ogni (piattaforma, business_unit), se `len(kept) == CAP_15`,
   log `GAP SUSPECTED <piattaforma> <bu>` + append a lista gap. A fine run, se la
   lista non è vuota, manda una singola mail riepilogativa.

5. **Insert BQ** (solo nuove): dedup MD5 residuo, `f_reviews` insert.

6. **Classify** (solo nuove): Claude Haiku batch, update righe con
   `categoria_nlp`, `sentiment`, `riassunto`.

7. **Alert**:
   - Se prima run per `(p, pid)` (watermark era `None`), applica filtro
     `data_review >= CURRENT_DATE - 7`.
   - Altrimenti tutte le nuove sono candidate.
   - Filtra `punteggio_norm <= 6.0 AND alert_inviato=false`.
   - Manda mail.
   - Su successo SMTP: `UPDATE f_reviews SET alert_inviato=true WHERE review_hash IN (...)`.
   - Su fail SMTP: log, non toccare il flag, al prossimo run riprova.

## Unit di design (interfacce)

**`ingest.read_watermarks() -> dict[tuple[str, str], str]`**
- Query BQ. Ritorna dict. Chiave `(piattaforma, business_unit_id)`, valore
  `data_review` ISO `YYYY-MM-DD`.
- Errori: se la query fallisce, solleva eccezione → la run aborta.

**`ingest.filter_by_watermark(watermarks, items) -> tuple[list[dict], list[tuple[str, str]]]`**
- Input: watermark dict + items normalizzati.
- Output: `(kept_items, gap_keys)`. `gap_keys` è popolato con
  `(piattaforma, business_unit_id)` se per quella chiave `len(kept) == CAP_15`.
- Pure function, testabile senza BQ.

**`alert.send_alerts(new_reviews, first_run_keys) -> list[str]`**
- Input: lista review nuove + set di `(piattaforma, business_unit_id)` che avevano
  watermark `None` (prima run per quella BU).
- Filtra punteggio ≤6 + grace window per prime run.
- Manda mail.
- Ritorna lista `review_hash` effettivamente notificati.
- Il caller scrive `alert_inviato=true` per quei hash.

**`alert.mark_alerts_sent(review_hashes: list[str]) -> None`**
- `UPDATE f_reviews SET alert_inviato=true WHERE review_hash IN UNNEST(@hashes)`.
- Parameterized query.

## Error handling

| Scenario | Comportamento |
|---|---|
| Actor fail/timeout | Cattura in `scrape_platform`, log `SCRAPE FAIL`, ritorna `[]`. Altre piattaforme continuano. |
| BQ down (watermark read) | Abort run, exit ≠ 0. Mai procedere con watermark vuoto involontario. |
| Watermark vuoto (nuova property) | Normale: tutti gli items passano. Alert filtrato da grace window 7gg. |
| `data_review` malformata | Log warning, drop singolo item. Run continua. |
| Duplicato logico | Watermark copre 99%. Dedup MD5 esistente resta come backup. |
| SMTP fail | Log, non scrivere flag. Ritento next run. Alert duplicato > alert perso. |
| Gap sospetto (15/15 nuovi) | Log + mail riepilogativa a fine run. Nessun auto-catchup. |

## Testing

**Unit** (`tests/test_reviews_watermark.py`, nuovo)

- `filter_by_watermark({}, items)` → ritorna tutti (no watermark)
- `filter_by_watermark({("BOOKING", "HOTEL"): "2026-04-01"}, items)` → droppa ≤2026-04-01
- Item con `data_review` malformata → scartato con log
- `filter_by_watermark` quando `len(kept) == 15` → popola `gap_keys`
- `filter_by_watermark` quando `len(kept) < 15` → `gap_keys` vuoto

**Unit alert** (`tests/test_reviews_alert.py`, esistente o nuovo)

- `send_alerts` con watermark vuoto applica grace window 7gg
- `send_alerts` con watermark presente notifica tutti i ≤6
- `mark_alerts_sent` costruisce query parameterized corretta

**Regression** (bug corrente)

- Fixture: `f_reviews` con review negativa vecchia (lug 2025), `alert_inviato=false`.
- Run con watermark da f_reviews.
- Verifica: **nessun** alert mandato per quella review (esclusa dal watermark).

**Integration** (mock BQ + mock actor)

- Mock actor ritorna 15 items: 5 con `data_review > watermark`, 10 ≤.
- 2 dei 5 nuovi hanno `punteggio_norm ≤ 6`.
- Expected: insert 5, mail con 2 review, `alert_inviato=true` scritto per 2 hash.

## Ricognizione preliminare (pre-implementazione)

Step di ricerca, ~15 min, prima di toccare codice:

1. Leggere README Apify dei 4 actor (Booking `voyager/booking-reviews-scraper`,
   TripAdvisor `maxcopell/tripadvisor-reviews`, Google
   `compass/Google-Maps-Reviews-Scraper`, Expedia `memo23/expedia-scraper`).
2. Cercare parametro tipo `reviewsStartDate`, `sinceDate`, `minDate`, `dateFrom`.
3. Per ciascun actor dove esiste → passarlo in `_build_input` usando il watermark.
   Il filtro client-side resta come safety net.
4. Risultato → aggiornare `docs/procedures/reviews_pipeline.md` tabella actor.

## Fuori scope (rimandato)

- `f_pipeline_runs` + PipelineRun context manager → **Layer 2 refactor** (spec separato)
- Watermark esplicito salvato nel run record → Layer 2
- `hotelops health` alerts se ultimo run OK > 36h → Layer 2
- Investigazione root cause gap Google pre-2026-04-09 → task separato
- Backfill `data_review` Google (blocked by streaming buffer) → task separato

## Done criteria

- [ ] `read_watermarks()` implementato + unit test
- [ ] `filter_by_watermark()` implementato + unit test (casi: vuoto, hit, malformed, gap)
- [ ] `normalize_items` integra il filtro
- [ ] `alert.send_alerts` applica grace window per first-run
- [ ] `alert.mark_alerts_sent` implementato con parameterized query
- [ ] Gap detection → mail riepilogativa a fine run
- [ ] Regression test: review negativa vecchia NON genera alert
- [ ] Ricognizione actor Apify completata + runbook aggiornato
- [ ] `docs/procedures/reviews_pipeline.md` aggiornato (`last_verified` + bug 🔴 risolto)
- [ ] ADR 0003 scritto (watermark-driven reviews, sostituisce ingest cieco)
- [ ] Run reale: verifica che nella prima run post-deploy non vengano mandati alert
      per review già presenti in BQ
