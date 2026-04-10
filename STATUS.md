# Status — 2026-04-10

## In corso
- Layer 2 refactor — observability: `f_pipeline_runs` + PipelineRun context manager + `hotelops health` esteso, non ancora iniziato
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito

## Completato di recente
- 2026-04-10: reviews **watermark gate** — `filter_by_watermark` + `read_watermarks` derivato da `MAX(data_review) GROUP BY (piattaforma, business_unit_id)`, grace window 7gg per first-run keys, gap detection a `len(kept)==cap` con mail riepilogativa. ADR 0003. Live verificato: 120/162 review droppate dal gate, 0 mail spurie.
- 2026-04-10: reviews **`alert_inviato` fix** — `mark_alerts_sent(hashes)` UPDATE parameterized post-SMTP. Regression test su review negativa vecchia (Zuzana Jul 2025). Bug delle 3 mail false chiuso alla radice.
- 2026-04-10: reviews **`alert.py` separation of concerns** — `send_alerts` pura (no side effects sui row), `mark_alerts_sent` esplicito, `send_gap_alert` per gap sospetti.
- 2026-04-10: `reviews/inspect_actors.py` — introspezione actor Apify via API (`client.actor(id).get()`), usato come source-of-truth per i param names.
- 2026-04-10: reviews **fix param names Apify** (`fix/apify-param-names`) — BOOKING `reviewsSort`→`sortReviewsBy`, TRIPADVISOR `maxItems`+`language`→`maxItemsPerQuery` (lingua omessa), EXPEDIA `maxReviewsPerHotel`+`maxReviews`→`maxItems`. 6 unit test in `tests/test_reviews_scrape.py`. Verificato live: Expedia 226→30 items (~85% cost reduction).
- 2026-04-10: reviews **backfill `data_review` Google** — 42 row ISO→YYYY-MM-DD via `UPDATE … SUBSTR(…,1,10)`. Watermarks 8→11 chiavi (GOOGLE ora coperto). Spreco Haiku su 42 review ri-classificate ogni run azzerato.
- 2026-04-09: reviews pipeline repair — schema drift GENERICA (schemas.py non allineato a classify.py), contract test `tests/test_reviews_schema_sync.py`
- 2026-04-09: reviews cost cap — `MAX_REVIEWS_PER_PROPERTY=15`, fix Booking `maxReviewsPerHotel` (era ignorato), CAP VIOLATED warning
- 2026-04-09: reviews noise filter — `normalize_items` droppa review con `punteggio_norm ∉ [1,10]`
- 2026-04-09: `ReviewRow.testo` accetta stringa vuota (star-only reviews)
- 2026-04-09: `normalize_google` trunca `publishedAtDate` a `[:10]`
- 2026-04-09: docs infra — `docs/procedures/`, `docs/protocols/`, `scripts/check_docs_freshness.py`, `hotelops docs check`, freshness in `hotelops health`
- 2026-04-09: `docs/procedures/reviews_pipeline.md` runbook completo
- 2026-04-09: `ingest_movimenti_contabili --replace` — SNAPSHOT-by-period semantics
- 2026-04-07: app_cdg — unified CDG app (CE + Budget + Tesoreria + Indicatori)
- 2026-04-07: cdg_engine — pure computation module

## Decisioni aperte
- Budget Apify: **$25/mese** hard limit (deciso 2026-04-09)
- Doc tecniche (runbook, protocolli) → `docs/` nel repo. Business/ontology → Obsidian vault. Deciso 2026-04-09.
- Refactoring cleanup: spec esiste (`docs/superpowers/specs/2026-03-27-refactoring-cleanup-design.md`), non prioritizzato
- Manifest/shadow OS: spec esiste, parking lot
- Reviews GENERICA al 39% — monitorare se servono categorie aggiuntive
- Gap detection euristica (`len(kept)==cap`): da rivedere dopo 2-4 settimane di dati reali — oggi falsi positivi su property piccole a first-run

## Rotto / da fixare
- 🔴 Google rotto 5+ settimane prima del 9 aprile — `MAX(data_review)` Google pre-watermark = 2026-03-03 vs Booking/Expedia 2026-04-06. Root cause sconosciuta. Il prossimo cron post-watermark ci dirà se era scraping rotto o review reali mancanti.
- 🟡 Cron reviews su host stefano — nessuna observability ancora (Layer 2 sblocca). Gap alert watermark copre in parte.
- 🟡 Crash window tra `send_email` e `mark_alerts_sent` UPDATE — scelta consapevole "alert duplicato > alert perso", da rivedere se succede.

## Prossimi passi
- Layer 2: `f_pipeline_runs` + PipelineRun context manager in reviews/ingest/banca, `hotelops health` con alert se ultimo run OK > 36h fa
- Cost tracking Apify via `GET /v2/actor-runs/{runId}` → `usageTotalUsd` (task #15, endpoint documentato nel runbook)
- Investigare perché Google era rotto prima del 9 aprile (confronto con prossimo cron post-fix)
- Env var override del cap per gap recovery manuale (`APIFY_MAX_REVIEWS_OVERRIDE=50`)
- Server-side date filter come ottimizzazione costi Apify (`cutoffDate`/`lastReviewDate`/`reviewsStartDate`/`reviewsFrom`)
- Materializzare v_condges_banca_dettaglio su BQ
- Valutare esecuzione xlsx-movimenti-parser
- Push dei 16 commit locali a `origin/main` quando deciso
