# Status — 2026-05-07

## In corso
- v_condges_banca_dettaglio: view SQL creata, non ancora materializzata su BQ
- v_ledger_movimenti: view SQL creata (`core/bq/views/v_ledger_movimenti.sql`), non ancora materializzata su BQ
- xlsx-movimenti-parser: piano scritto (`docs/superpowers/plans/2026-03-30-xlsx-movimenti-parser.md`), non eseguito
- **revman vertical**: mappatura completa 5 fonti HotelCube; Power BI Z_DataSet espone 12 report downstream (AndamentoPrenotazioni, CamereTree, Clienti, ConsumazioniF&B, Cruscotto, CruscottoMP, CurveCumulative, Prenotazioni, StoricoPrevisione*3) — solo Cruscotto/CruscottoMP ha loop dichiarato (mail produzione). **Bozza email a Lara pronta** (non inviata).
- **condges Rosa→Gasparotto integration**: spec + plan scritti (`c69abc1`, `beddc7e`). 2 task iniziali implementati. Plan in esecuzione.
- **Projects event-sourced Step 1**: spec scritta `docs/superpowers/specs/2026-04-22-projects-event-sourced-design.md`. **Plan TDD da generare**, defer a Doc Refresh + cassa loop chiusi.
- **Vault loops restructure**: 2/12 loop specs scritti (`daily_reconciliation`, `cash_control`). Next candidate: `monthly_close` (Gasparotto file, COMPETENZA mensile).
- **Doc Refresh Sprint** (`docs/superpowers/plans/2026-05-01-doc-refresh-sprint.md`): Step 1+2+2.5 chiusi in working tree (da committare). Step 3 (README rewrite) — diff proposto in chat, in attesa OK. Step 4-9 in coda.

## Completato di recente
- 2026-05-07: **Lineage FK + observability** (branch `feat/lineage-fk-and-observability`, 14 commit, mergiato `delete-digest` per Task 6+7). Migration `f_banche_movimenti.raw_object_id STRING NULLABLE` applicata su BQ produzione. `BancaMovimentoRow.raw_object_id` in `core/schemas.py`. `ingest.banca.ingest` single-file mode (`--file --raw-object-id --societa`), `promotion._invoke_parser` propaga `--raw-object-id` al subprocess. **Task 4.5**: `intake.py` emette `SOURCE_RESOLVED` (RAW_ONLY → CLASSIFIED) → sblocca `promote`. **Task 4.6**: state machine accetta `(CLASSIFIED, VALIDATED_OK)` + `(CLASSIFIED, PROMOTED)`, emit con `from_status=current`. View `v_raw_promotion_status` deployata su BQ (per-source × status counts), CLI `hotelops lineage --list --status/--source/--days/--limit`. Smoke produzione: state machine flow ✅ (`RAW_INGESTED → SOURCE_RESOLVED → PROMOTION_REQUESTED → VALIDATED_OK → PROMOTED`); FK stamping su new rows ⏳ (file di test era già storicamente ingestito → 0 nuove righe → in coda al prossimo MPS fresh). Scope creep `2b9d26a` accettato (failure path `(CLASSIFIED, VALIDATED_FAIL)` + `from_status=current` su VALIDATED_FAIL/REJECTED — semanticamente coerente, paper trail in plan).
- 2026-05-05: **GCS as Raw Staging — Phase 4 mergiata su `main`** (PR #8 squash). Bucket `gs://hotelops-raw` provisionato (EU, STANDARD, Object Versioning ON, Autoclass→ARCHIVE, public-access-prevention). Backend abstraction (`core/lineage/raw_storage.py`: `LocalBackend` passthrough + `GCSBackend` upload/download_to_temp). Schema migration additiva `f_raw_objects.gcs_generation INT64 NULLABLE` applicata su BQ produzione. Pilot `MPS_BANCA_ORTI_APPEND` (lifecycle APPEND) flippato a `backend: gcs`. Smoke test produzione su file MPS reale: intake → upload → register → event OK. **Bonus dedup-before-upload**: smoke ha scoperto gap (re-intake stesso content_hash creava orphan GCS generation + duplicate `RAW_INGESTED`); fix probe `_lookup_existing_by_hash` PRIMA di `backend.upload()` (chiude debt Phase 1). Re-smoke verde: 3rd intake → stesso id, no nuove generation, no nuovi event. 4 nuovi test (`test_intake_gcs.py` incluso regression `test_intake_dedup_hit_skips_upload_and_event`).
- 2026-05-05: **Ingest lineage Phase 1+2 mergiati** — moduli `core/lineage/` completi (schemas, source_resolver, state_machine, policy_gate, raw_manifest), tabelle `f_raw_objects` + `f_lineage_events` + view `v_raw_objects_current` produzione, CLI `hotelops intake/promote/lineage` operativi. State machine: RAW_ONLY → CLASSIFIED → PROMOTABLE → PROMOTED + REJECTED. Hard gate invariant `loop_targets == [] ⇔ promotion_policy == RAW_ONLY`.
- 2026-05-05: **Branch cleanup** — eliminate 5 branch stale (codex/refactor-code-for-clarity, codex/update-search-strategy-to-use-rg ×2, feature/manifest-budget-fix, saldo-banca-manuale). Rimaste 2 branch con PR aperte (codex/update-search-strategy-to-use-rg-pjgr7y PR #5, add-claude-github-actions-1772490755260 PR #1).
- 2026-05-02: **bug fix ultrareview** — `bug_001` `hash_riga` in `ingest_vendite_fb` ora include `segmento_cliente` (era 470 hash con collisioni cross-segmento → 0); `bug_004` `sys.exit(0)` → `return` in `ingest_vendite_fb`/`ingest_coperti`/`ingest_partite_aperte` (PipelineRun status FAIL→OK); 4 nuovi test in `tests/test_ingest_vendite_fb.py` + 1 regression in `test_pipeline_run.py`. **Backfill `f_vendite_fb` eseguito** (TRUNCATE + ri-ingest da `Ristocube Data (3).xlsx`, 19.806 righe, 19.806 hash distinti, 0 collisioni cross-segmento, €315.407,40 invariati). 373/373 test verdi.
- 2026-05-01: **Doc Refresh Sprint Step 1-2.5** — vocab fix `AI_INSTRUCTIONS.md` (Gasparotto = file Master di Roberto Romita, Rosa = persona reale, Romita = persona); nuovo `docs/architecture/DATA_ENGINEERING_RULES.md` (lineage contract, naming, write gate, lifecycle, plan-first per dominio finanziario); riga reading list in `CLAUDE.md`; Step 2.5 fix gate UUID — `core/bq/write.py` ora genera UUID standalone fuori da PipelineRun invece di `run_id=None`, conforme a Rules §3.
- 2026-04-30: **Sprint 1 closure + Sprint 2 Phase 1 + INVARIANTS migration** — `bq_write_validated` gate centralizzato (Pydantic + boundary check + lineage), 3 pilot SNAPSHOT validati su BQ produzione (scheda contabile, partite aperte, coperti). `f_vendite_fb` con `segmento_cliente` (19.806 righe, 2024-03..2026-04). Views `v_food_cost_mensile` + `v_food_cost_categoria` (YoY 2024 vs 2025 sbloccato). INVARIANTS migrati al repo (`docs/architecture/INVARIANTS.md`, e12bc59). CLAUDE.md v0.6.0 checkpoint.
- 2026-04-26: **Projects event-sourced design** — spec `2026-04-22-projects-event-sourced-design.md` (3 tab event-sourced: `d_progetti`/`f_progetto_voci`/`f_progetto_eventi`, 5 tipi evento, validation seed 2 progetti reali). Spec S2 archiviata. Vault captures: PROGETTO event-log, ADR amended.
- 2026-04-23: **vault foundation + primi loop specs** — IDENTITY.md ("company operating system per hospitality"), loops/_INDEX.md (12 loop in 3 categorie), daily_reconciliation, cash_control.
- 2026-04-23: **parser account-based + hardening cassa + shell scripts** — c72e66a/966542d, 34 test verdi.

## Decisioni aperte
- Budget Apify: **$25/mese** hard limit (deciso 2026-04-09)
- Doc tecniche → `docs/`. Business/ontology → vault. Deciso 2026-04-09.
- Refactoring cleanup: spec esiste, non prioritizzato.
- Manifest/shadow OS: spec esiste, parking lot.
- Reviews GENERICA al 39% — monitorare se servono categorie aggiuntive.
- Gap detection euristica `len(kept)==cap` da rivedere dopo 2-4 settimane di dati reali.
- **revman come verticale #3**: confermato. Scope dipende da risposta API HotelCube.
- **Pattern integrazione API HotelCube**: client diretto da hotelops CLI, auth apiKey + IP whitelist (deciso 2026-04-18).
- **Projects come dimensione di primo livello (CapEx)**: deciso 2026-04-21, refined 2026-04-26 con event-sourcing 3 tab. Aperta: vertical #4 vs CONDGES extension (rinviata a fine Step 1).
- **Fonti CLI/APP in `f_piano_finanziario_input` cieche a `v_previsione_cassa`** (emerso 2026-04-23): decidere se promuovere fonti a canonical o consolidare. Richiede decision esplicita prima di toccare la view.
- **Drift `bank_reconciliation` vs `bank_ledger_reconciliation`** in vault loops: due loop semanticamente distinti — decidere se coesistono o si unificano.
- **Frame canonico HotelOps = Company OS** (non "digital twin") — articolato 2026-05-02 in manifesto. Vault `IDENTITY.md` già allineato; CLAUDE.md linea "digital twin" è debito da risolvere in Doc Refresh Step 4.
- **GCS come Raw layer immutabile** (deciso 2026-05-02, **IMPLEMENTATO per pilot 2026-05-05** PR #8, **FK pilot 2026-05-07**): bucket `hotelops-raw` con Object Versioning + Autoclass terminal=ARCHIVE è il Raw layer per **TUTTO il contenuto Drive datahub**. Pilot `MPS_BANCA_ORTI_APPEND` live in produzione con FK `f_banche_movimenti.raw_object_id`. Drive datahub resta come spazio umano editabile. Resta aperto il rollout: bulk flip altre 12 sources `backend: gcs` quando il loop le richiama (discrimination-need rule), pattern FK additivo per ogni canonical table (template migration `2026_05_06`).
- **Bulk flip 12 sources rimanenti → `backend: gcs`** (emerso 2026-05-05): 12 source_def in `core/source_registry.yaml` ancora `backend: drive`. Politica: flip on-demand quando un loop la richiama (no big-bang refactor). Regola discrimination-need ancora valida.
- **Backfill rows storiche `file://` → `gs://`** (emerso 2026-05-05): righe `f_raw_objects` pre-Phase-4 hanno `raw_uri = file://...` e `gcs_generation IS NULL`. Decidere se backfill upload + relink (preserva storia) o lasciarle local-only (storico immutabile). Trigger: la prima volta che un parser deve rileggere una riga storica.
- **Primo loop vivo deciso = cassa giornaliera quadra y/n** — verdetto persistito (richiede tabella `f_decisioni` o equivalente). Sblocca pattern decision-record per loop futuri. Spec da scrivere dopo Doc Refresh.
- **Regola operativa ingest** (articolata 2026-05-02): lo scope dell'ingest è settato dal *discrimination need del loop*, non dalla disponibilità del dato. Si estende quando il loop fallisce *cieco* (non sa nominare il gap). Backlog tipo "x dato esiste, lo prendo" è parking lot finché un loop non lo nomina.
- **Glossario `segmento_cliente` parziale** (Ristocube): INLE=individuali leisure, INTUI=individuali TUI, GRLE=gruppi leisure, GRBU=gruppi business, GRSE=gruppi in serie, ZRIST*=roof restaurant interno/esterno (NON pensione camere). TBD: vuoto, GRWE, FERR25, ZRISRES. Capture in `vault/concepts/SEGMENTO_CLIENTE.md` da fare.

## Rotto / da fixare
- ✅ ~~`extract_saldo_mps2026` date parsing~~ — fixato 2026-04-16.
- ✅ ~~d_voci pattern duplicate `390521`~~ — verificato 2026-04-23.
- ✅ ~~Google rotto 5+ settimane~~ — risolto 2026-04-24.
- ✅ ~~bug_001 `hash_riga` ingest_vendite_fb omette `segmento_cliente`~~ — fixato 2026-05-02 + backfill (TRUNCATE + ri-ingest, 19.806 righe, 0 collisioni).
- ✅ ~~bug_004 `sys.exit(0)` in `with PipelineRun(...)` registra FAIL invece di OK~~ — fixato 2026-05-02 nei 3 callsite + regression test che documenta il trap.
- 🔴 **Schema drift `f_chiusura_mensile`**: `hotelops health` riporta tabella NON FOUND su BQ. View/pipeline `chiudi` la cita ma la tabella non esiste — chiusura mese non scrivibile.
- 🟡 **Pipelines stale >36h**: `ingest_scheda_contabile` + `ingest_partite_aperte` ultimo OK run 2026-04-30 (54h ago).
- 🟡 **f_pms_statistiche freshness**: dati fermi al 2026-04-11 (21gg indietro). Da estrarre 60 file Cruscotto giornalieri (20gg × 3 BU) da Power BI per coprire 2026-04-12 → 2026-05-01. Solo `Cruscotto/CruscottoMP` ha loop dichiarato (mail produzione giornaliera).
- 🟡 **Banche stale**: INTUR/INTESA 53gg, ORTI/INTESA 32gg, INTUR/MPS 31gg, ORTI/MPS+MPS_KROSS 15gg. Solo INTUR/SELLA fresh.
- 🟡 Gap residuo crash totale `send_email` → `mark_alerts_sent` — fix `af685b2` cattura streaming buffer; processo morto tra send_email e persist_pending non lascia traccia locale. Scelta consapevole "alert duplicato > alert perso", blast radius ridotto.

## Prossimi passi
- **FK end-to-end smoke su MPS file fresh** — al prossimo export bancario non già storico, rilanciare `intake + promote` e verificare `f_banche_movimenti.raw_object_id IS NOT NULL` con JOIN risolto a `f_raw_objects`. Chiude la prova FK su NEW rows pending da Task 5.
- **Bulk extension FK pattern** — quando una nuova source flippa a `backend: gcs`, aggiungere `raw_object_id` alla sua canonical_table nello stesso commit (template: migration `2026_05_06_add_raw_object_id_f_banche_movimenti.py`).
- **Doc Refresh Sprint Step 3-9** — README rewrite (diff proposto, OK pendente) → CLAUDE.md Project Overview + Architecture (Step 4) → CLAUDE.md sezioni mancanti (Step 5) → counts + tests refresh (Step 6) → Cutover decision in vault (Step 7) → TODO markers in `ingest/banca/ingest.py` (Step 8) → Agent Epistemology promotion in AI_INSTRUCTIONS (Step 9). Plan-First per ogni step.
- **Bulk flip 12 sources `backend: drive` → `backend: gcs`** in `core/source_registry.yaml` quando il loop le richiama (post-Phase-4, on-demand).
- **Phase 5 cutover `cmd_drop` = `intake + promote`** — eliminare lo shadow path, rendere lineage il default. Pre-condizione: Phase 4 stabile su pilot per >7gg + bulk flip di almeno N sources core (TBD).
- **Spec loop cassa giornaliera quadra y/n** (post-Doc-Refresh) — primo verdetto operativo del sistema (NON_QUADRA con discrepanza nominabile), input GCS narrow, recipient Rosa solo se non quadra. Stefano fornirà schema minimo input + query riconciliazione una volta chiuso Doc Refresh.
- **Capture `vault/concepts/SEGMENTO_CLIENTE.md`** — glossario codici Ristocube (5/11 noti), TBD su GRWE/FERR25/vuoto/ZRISRES.
- **Loop spec `monthly_close`** — Gasparotto file, COMPETENZA mensile, completa trilogia base (daily/weekly/monthly).
- **bug_013 (nit)** — `--dry-run` skippa Pydantic in `ingest_coperti.py:580`, valida in `ingest_partite_aperte` (incoerenza tra sister-pipeline). Hoist Pydantic sopra `if dry_run: return` al prossimo touch (~3 righe).
- **Estrazione produzione PMS** — 60 file Cruscotto giornalieri (20gg × HOTEL/CVM/RESIDENCE) per il gap 2026-04-12 → 2026-05-01. Stefano export manuale da Power BI; ingest via `python -m ingest.flussi.ingest_pms_statistiche /path/to/cartella`.
- **Risolvere drift bank_reconciliation vs bank_ledger_reconciliation** — decidere se due loop o uno (file `bank_ledger_reconciliation.md` non committato).
- **Test cassa giornaliera su 1 giorno reale** — usare nuovo stream `f_accodamenti` per validare `condges/cassa_giornaliera.py` vs riferimento manuale.
- **Materializzare** v_ledger_movimenti + v_condges_banca_dettaglio su BQ.
- **Schema fix `f_chiusura_mensile`** — creare tabella o rimuovere riferimenti dalle pipeline (drift schema 🔴).
- **Inviare email a Lara Durisotti** (bozza pronta) — sblocca revman.
- **Documento interno `docs/hotelcube-api-extension.md`** — mappatura 5 export + 12 report Power BI Z_DataSet.
- **Discussione `SOCIETA_DEFAULT = "INTUR"`** — righe `ingresso/accodamenti/ORTI/…` taggate INTUR via default.
- **Backfill `file_sorgente` 277 righe vecchie** (cosmetico, non blocca query).
- **Projects Step 1 plan TDD** — defer a Doc Refresh + cassa loop chiusi.
- **condges Rosa→Gasparotto plan resume** — continuare esecuzione plan `beddc7e`.
- **Mail produzione giornaliera** — email occupazione + revenue per BU da `f_pms_statistiche` (richiede freshness fix sopra).
- **Struttura `revman/`** dopo risposta HotelCube.
- Investigare CVM Trip.com avg 4.57 (sotto threshold alert 6.0).
- Instrumentare banca/flussi pipeline con `PipelineRun` (context manager generico).
- Valutare email alert per `check_watermark_staleness` dopo 2-3 settimane.
- Verifica manuale Google Maps RESIDENCE+CVM post-2025-09-13.
- Valutare esecuzione xlsx-movimenti-parser.
