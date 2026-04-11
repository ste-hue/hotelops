# Status — 2026-04-11

## In corso
- `f_pipeline_runs` creazione tabella BQ — manuale, da runnare prima del prossimo cron (comando in commit Layer 2)
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito

## Completato di recente
- 2026-04-11: reviews **Layer 2 f_pipeline_runs observability** (merge commit + `b9f46a3` + `72b5e20`) — `PipelineRun` context manager in `core/pipeline_run.py` (INSERT RUNNING su __enter__, UPDATE finale su __exit__, best-effort BQ mai blocker), `PipelineRunRow` schema, `F_PIPELINE_RUNS` constant. `_cmd_scrape` wrappato con cattura rows_found/rows_new/alerts_sent/usage_total_usd/watermark meta. `scrape_platform`/`scrape_all` ora ritornano `(items, total_cost_usd)` tuple (deviazione vs spec per evitare re-query BQ). 3 health check: `check_watermark_staleness` (21d), `check_pipeline_staleness` (36h), `check_crashed_runs` (1h RUNNING stuck) wirati in `condges/cli_commands.cmd_health`. 15 test nuovi (11 PipelineRun + 4 health). **Tabella BQ da creare manualmente** prima del prossimo cron — comando in commit message.
- 2026-04-11: reviews **Trip.com come 5° fonte review** (merge commit + `9d2ab7e`) — `knagymate/trip-com-reviews-scraper` per Hotel (774198), Residence (3094414), CVM (4043516). `PiattaformaReview` Literal esteso, `SCORE_SCALE`/`SCORE_SCALES`/`PIATTAFORME` allineati, help text `inspect_actors` aggiornato. `_build_input` branch TRIP usa `hotelUrl` (STRING, non `startUrls` array) + `maxReviews` — regression guard per blowout $3.38 del 2026-04-11 (schema defaults fallback = Grand Hyatt Shanghai, 1000 review). `normalize_trip` + `_extract_trip_hotel_id`: rating già 1-10, review anonime (no `reviewer_nome`), hash combina hotel_id|review_id per isolamento cross-hotel, content preferito per IT/EN con fallback a `translatedContent` per altre lingue. 10 test nuovi.
- 2026-04-10: reviews **Task #17 — POC aggregator SHELVED** — `tri_angle/hotel-review-aggregator` archiviato in `docs/superpowers/poc-archive/` (script + output Run #1 + README con rationale). Blocker Expedia fundamental (Google-first cross-match non risolve Hotel Panorama), e il fan-out 4-actor corrente costa frazioni di cent/run → nessun incentivo a migrare. Worktree `.worktrees/poc-aggregator` rimosso, branch `poc/apify-aggregator` eliminato. Condizioni di riapertura documentate nel README.
- 2026-04-10: reviews **Task #16 — Apify cost persistence** (`12df482`) — `ApifyRunRow` schema in `core/schemas.py` + `persist_apify_run()` in `reviews/scrape.py` (best-effort, mai blocker) + sezione "Costi Apify" in `render_weekly_report` via `_fetch_apify_costs`. `n_items` pre-truncation per audit onesto del blast radius. 6 test nuovi (3 persist + 2 cost section + 1 schema). **Verificato end-to-end live**: 3 run BOOKING in `f_apify_runs` (HOTEL/RESIDENCE/CVM, $0.0001 ciascuno), email settimanale mostra breakdown corretto ($0.0003 totali, 45 item, 0 cap viol).
- 2026-04-10: reviews **`mark_alerts_sent` streaming buffer fix** (`af685b2`) — retry 3× (30+60+120s) su `BadRequest "streaming buffer"`, altri errori sollevano immediati. Se i retry falliscono, hash persistite in `.hotelops_state/pending_alert_flags.json` (merge-not-overwrite). `flush_pending_alert_flags()` chiamato step 0 di `_cmd_scrape` per auto-reconciliation quando il buffer si è svuotato. 9 test nuovi in `tests/test_reviews_alert.py`, 198/198 suite verde.
- 2026-04-10: reviews **`--start/--end` override report** (`d0f468c`) — `hotelops reviews --report --start 2026-04-06 --end 2026-04-10` per ispezioni ad hoc. Default Lun-Dom invariato (contratto cron settimanale). Validazione: entrambi o nessuno.
- 2026-04-10: cli **auto-load `.env`** (`303905b`) — manual loader in `cli.py` prima degli import dei submodule. Preserva spazi nei valori (fix definitivo al bug `export $(... | xargs)` che troncava la Gmail App Password al primo spazio). Shell env var vincono su .env. Verificato live: `hotelops reviews --report` → "1 reviews, Email inviata".
- 2026-04-10: reviews **`url_review` fix Booking** (`e08a012`) — `normalize_booking` popola `url_review` con `PROPERTIES[bu]["BOOKING"] + "#tab-reviews"` invece di `None`. Email alert Booking ora hanno un link utile invece di "Link: N/A". Test regression in `tests/test_reviews_ingest.py`. Backfill row esistenti pending (insieme a UPDATE `alert_inviato`).
- 2026-04-10: reviews **Apify cost tracking log-only** (`b60b250`) — `scrape.py` legge `run.usageTotalUsd` con fallback refetch, logga per-run e totale per-piattaforma. Nessuna persistenza ancora. Task #15 chiuso, Task #16 aperto per persistenza.
- 2026-04-10: reviews **Prod scrape Booking manuale** — 15 review caricate, di cui Andre 1/10 (review negativa). Alert emails inviate manualmente via one-shot per Luana 6.0 + Andre 1.0 dopo fix watermark gate. **Bug aperto**: `mark_alerts_sent` ha crashato su streaming buffer error (UPDATE su row inserite via `insert_rows_json` bloccato per ~30-90 min); email sono partite ma `alert_inviato` NON è stato aggiornato. Hash pending: `225f59cd5b9bf76ec1fe7ab7777050b2` (Luana), `5a473fb8bde80958bdf2c6459c2431da` (Andre).
- 2026-04-10: reviews **SMTP bug root-cause** — `export $(grep -v '^#' .env | xargs)` splittava la Gmail App Password su spazi (formato "xxxx xxxx xxxx xxxx"), esportando solo i primi 4 char → 535 Bad Credentials. Fix: loader .env manuale in Python. Password esistente validata, non rotata.
- 2026-04-10: reviews **watermark gate** — `filter_by_watermark` + `read_watermarks` derivato da `MAX(data_review) GROUP BY (piattaforma, business_unit_id)`, grace window 7gg per first-run keys, gap detection a `len(kept)==cap` con mail riepilogativa. ADR 0003. Live verificato: 120/162 review droppate dal gate, 0 mail spurie.

## Decisioni aperte
- Budget Apify: **$25/mese** hard limit (deciso 2026-04-09)
- Doc tecniche (runbook, protocolli) → `docs/` nel repo. Business/ontology → Obsidian vault. Deciso 2026-04-09.
- Refactoring cleanup: spec esiste (`docs/superpowers/specs/2026-03-27-refactoring-cleanup-design.md`), non prioritizzato
- Manifest/shadow OS: spec esiste, parking lot
- Reviews GENERICA al 39% — monitorare se servono categorie aggiuntive
- Gap detection euristica (`len(kept)==cap`): da rivedere dopo 2-4 settimane di dati reali — oggi falsi positivi su property piccole a first-run

## Rotto / da fixare
- 🟡 **Gap residuo crash totale** `send_email` → `mark_alerts_sent` — il fix `af685b2` cattura il caso streaming buffer (retry + pending file), ma se il processo muore completamente tra send_email e persist_pending non c'è traccia locale. Scelta consapevole "alert duplicato > alert perso" ancora in piedi, ora blast radius molto ridotto.
- 🔴 Google rotto 5+ settimane prima del 9 aprile — `MAX(data_review)` Google pre-watermark = 2026-03-03 vs Booking/Expedia 2026-04-06. Root cause sconosciuta. Il prossimo cron post-watermark ci dirà se era scraping rotto o review reali mancanti.
- 🟡 Crash window tra `send_email` e `mark_alerts_sent` UPDATE — scelta consapevole "alert duplicato > alert perso", da rivedere se succede. (Ora aggravata dal bug streaming buffer sopra.)

## Prossimi passi
- Creare tabella BQ `f_pipeline_runs` manualmente (comando in commit Layer 2) prima del prossimo cron reviews
- Prima scrape reale Trip.com per validare `normalize_trip` end-to-end + verificare rating normalization
- Instrumentare banca/flussi pipeline con `PipelineRun` (context manager è già generico)
- Valutare email alert per `check_watermark_staleness` dopo 2-3 settimane di dati (oggi solo display CLI)
- Investigare perché Google era rotto prima del 9 aprile (confronto con prossimo cron post-fix)
- Env var override del cap per gap recovery manuale (`APIFY_MAX_REVIEWS_OVERRIDE=50`)
- Server-side date filter come ottimizzazione costi Apify (`cutoffDate`/`lastReviewDate`/`reviewsStartDate`/`reviewsFrom`) — POC aggregator ha confermato che `reviewsFromDate` funziona server-side per il nuovo actor
- Weekly narrative synthesis: LLM-generated 3-paragraph summary in `render_weekly_report` via Claude Haiku (~30 min work, non approvato)
- Materializzare v_condges_banca_dettaglio su BQ
- Valutare esecuzione xlsx-movimenti-parser
