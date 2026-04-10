# Status — 2026-04-10

## In corso
- **Task #17 — POC aggregator `tri_angle/hotel-review-aggregator`**: worktree `.worktrees/poc-aggregator` con `reviews/poc_aggregator.py`. Run #1 eseguita su HOTEL / 10-day window / $1 cap → 5 item (tutti Booking), $0.0181, `reviewsFromDate` server-side confermato efficace. **Blocker**: Expedia fallisce con "Failed to get any URLs" (Google-first cross-match non trova Hotel Panorama), nonostante 197 row Expedia esistano in BQ. POC run #2 non decisa (finestra 6 mesi ~$0.78 stimati).
- Layer 2 refactor — observability: `f_pipeline_runs` + PipelineRun context manager + `hotelops health` esteso, non ancora iniziato
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito

## Completato di recente
- 2026-04-10: reviews **Task #16 — Apify cost persistence** (`12df482`) — `ApifyRunRow` schema in `core/schemas.py` + `persist_apify_run()` in `reviews/scrape.py` (best-effort, mai blocker) + sezione "Costi Apify" in `render_weekly_report` via `_fetch_apify_costs`. `n_items` pre-truncation per audit onesto del blast radius. 6 test nuovi (3 persist + 2 cost section + 1 schema). **Verificato end-to-end live**: 3 run BOOKING in `f_apify_runs` (HOTEL/RESIDENCE/CVM, $0.0001 ciascuno), email settimanale mostra breakdown corretto ($0.0003 totali, 45 item, 0 cap viol).
- 2026-04-10: reviews **`mark_alerts_sent` streaming buffer fix** (`af685b2`) — retry 3× (30+60+120s) su `BadRequest "streaming buffer"`, altri errori sollevano immediati. Se i retry falliscono, hash persistite in `.hotelops_state/pending_alert_flags.json` (merge-not-overwrite). `flush_pending_alert_flags()` chiamato step 0 di `_cmd_scrape` per auto-reconciliation quando il buffer si è svuotato. 9 test nuovi in `tests/test_reviews_alert.py`, 198/198 suite verde.
- 2026-04-10: reviews **`--start/--end` override report** (`d0f468c`) — `hotelops reviews --report --start 2026-04-06 --end 2026-04-10` per ispezioni ad hoc. Default Lun-Dom invariato (contratto cron settimanale). Validazione: entrambi o nessuno.
- 2026-04-10: cli **auto-load `.env`** (`303905b`) — manual loader in `cli.py` prima degli import dei submodule. Preserva spazi nei valori (fix definitivo al bug `export $(... | xargs)` che troncava la Gmail App Password al primo spazio). Shell env var vincono su .env. Verificato live: `hotelops reviews --report` → "1 reviews, Email inviata".
- 2026-04-10: reviews **`url_review` fix Booking** (`e08a012`) — `normalize_booking` popola `url_review` con `PROPERTIES[bu]["BOOKING"] + "#tab-reviews"` invece di `None`. Email alert Booking ora hanno un link utile invece di "Link: N/A". Test regression in `tests/test_reviews_ingest.py`. Backfill row esistenti pending (insieme a UPDATE `alert_inviato`).
- 2026-04-10: reviews **Apify cost tracking log-only** (`b60b250`) — `scrape.py` legge `run.usageTotalUsd` con fallback refetch, logga per-run e totale per-piattaforma. Nessuna persistenza ancora. Task #15 chiuso, Task #16 aperto per persistenza.
- 2026-04-10: reviews **Prod scrape Booking manuale** — 15 review caricate, di cui Andre 1/10 (review negativa). Alert emails inviate manualmente via one-shot per Luana 6.0 + Andre 1.0 dopo fix watermark gate. **Bug aperto**: `mark_alerts_sent` ha crashato su streaming buffer error (UPDATE su row inserite via `insert_rows_json` bloccato per ~30-90 min); email sono partite ma `alert_inviato` NON è stato aggiornato. Hash pending: `225f59cd5b9bf76ec1fe7ab7777050b2` (Luana), `5a473fb8bde80958bdf2c6459c2431da` (Andre).
- 2026-04-10: reviews **SMTP bug root-cause** — `export $(grep -v '^#' .env | xargs)` splittava la Gmail App Password su spazi (formato "xxxx xxxx xxxx xxxx"), esportando solo i primi 4 char → 535 Bad Credentials. Fix: loader .env manuale in Python. Password esistente validata, non rotata.
- 2026-04-10: reviews **watermark gate** — `filter_by_watermark` + `read_watermarks` derivato da `MAX(data_review) GROUP BY (piattaforma, business_unit_id)`, grace window 7gg per first-run keys, gap detection a `len(kept)==cap` con mail riepilogativa. ADR 0003. Live verificato: 120/162 review droppate dal gate, 0 mail spurie.
- 2026-04-10: reviews **`alert_inviato` fix** — `mark_alerts_sent(hashes)` UPDATE parameterized post-SMTP. Regression test su review negativa vecchia (Zuzana Jul 2025). Bug delle 3 mail false chiuso alla radice.

## Decisioni aperte
- Budget Apify: **$25/mese** hard limit (deciso 2026-04-09)
- Doc tecniche (runbook, protocolli) → `docs/` nel repo. Business/ontology → Obsidian vault. Deciso 2026-04-09.
- Refactoring cleanup: spec esiste (`docs/superpowers/specs/2026-03-27-refactoring-cleanup-design.md`), non prioritizzato
- Manifest/shadow OS: spec esiste, parking lot
- Reviews GENERICA al 39% — monitorare se servono categorie aggiuntive
- Gap detection euristica (`len(kept)==cap`): da rivedere dopo 2-4 settimane di dati reali — oggi falsi positivi su property piccole a first-run

## Rotto / da fixare
- 🟡 **Gap residuo crash totale** `send_email` → `mark_alerts_sent` — il fix `af685b2` cattura il caso streaming buffer (retry + pending file), ma se il processo muore completamente tra send_email e persist_pending non c'è traccia locale. Scelta consapevole "alert duplicato > alert perso" ancora in piedi, ora blast radius molto ridotto.
- 🟡 POC aggregator Expedia cross-match fallisce — `tri_angle/hotel-review-aggregator` identifica property via Google Maps e poi cerca su altre piattaforme, ma non trova Hotel Panorama su Expedia nonostante noi abbiamo già 197 row Expedia scrapate via `memo23/expedia-scraper`. Blocker per adozione aggregator al posto del fan-out 4-actor.
- 🔴 Google rotto 5+ settimane prima del 9 aprile — `MAX(data_review)` Google pre-watermark = 2026-03-03 vs Booking/Expedia 2026-04-06. Root cause sconosciuta. Il prossimo cron post-watermark ci dirà se era scraping rotto o review reali mancanti.
- 🟡 Cron reviews su host stefano — nessuna observability ancora (Layer 2 sblocca). Gap alert watermark copre in parte.
- 🟡 Crash window tra `send_email` e `mark_alerts_sent` UPDATE — scelta consapevole "alert duplicato > alert perso", da rivedere se succede. (Ora aggravata dal bug streaming buffer sopra.)

## Prossimi passi
- **Task #17**: decidere POC aggregator run #2 (6-month window ~$0.78) o shelf il POC. Blocker Expedia resta aperto.
- Layer 2: `f_pipeline_runs` + PipelineRun context manager in reviews/ingest/banca, `hotelops health` con alert se ultimo run OK > 36h fa
- Investigare perché Google era rotto prima del 9 aprile (confronto con prossimo cron post-fix)
- Env var override del cap per gap recovery manuale (`APIFY_MAX_REVIEWS_OVERRIDE=50`)
- Server-side date filter come ottimizzazione costi Apify (`cutoffDate`/`lastReviewDate`/`reviewsStartDate`/`reviewsFrom`) — POC aggregator ha confermato che `reviewsFromDate` funziona server-side per il nuovo actor
- Weekly narrative synthesis: LLM-generated 3-paragraph summary in `render_weekly_report` via Claude Haiku (~30 min work, non approvato)
- Materializzare v_condges_banca_dettaglio su BQ
- Valutare esecuzione xlsx-movimenti-parser
