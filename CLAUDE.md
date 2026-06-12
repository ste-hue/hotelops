# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Last checkpoint:** 2026-06-12 | **Version:** 0.8.0

> **2026-06-12 checkpoint:** il diario operativo vivo è `STATUS.md` (in corso / decisioni aperte / rotto / prossimi passi) — leggilo prima di pianificare, non duplicarlo qui. Ultimo merge rilevante: **F&B Looker pipeline** (4 viste F&B + audit tool direzione + RistoCube Orders, commit `06abda7`, 2026-05-22), **GCS raw lineage layer** (Phase 1), refactor `v_fb_kpi` a 3 bucket onesti CANTINA=Bar + esclusione 9 UoM (2026-06-08). Thread aperti principali: loop minimo `cash_control` end-to-end, dashboard Looker F&B da aggiornare al nuovo contratto colonne `v_fb_kpi`.

> **For AI agents**: ground truth = repo + BigQuery schema. Read in this order before non-trivial work:
> 1. `docs/architecture/INVARIANTS.md` — la costituzione (I1–I8, canonical per concept). [migrato dal vault il 2026-04-30]
> 2. `docs/architecture/AI_INSTRUCTIONS.md` — layer model, canonical truth registry, operational loop, anti-goals.
> 3. `docs/architecture/LE_3_DIMENSIONI.md` — il concetto temporale più importante del sistema.
> 4. `CLAUDE.md` (this file) — repo mechanics: commands, schemas, pipeline internals.
>
> **Goal di lungo termine**: HotelOps è il **Company OS** — il sistema operativo decisionale delle vere operazioni del business (frame canonico deciso 2026-05-02, supera la vecchia metafora "digital twin"). 3 layer:
> - **Code** (`core/`, `ingest/`, `verticals/condges/`, `verticals/reviews/`): come opera il twin.
> - **BigQuery**: cosa il twin osserva.
> - **Vault `<vault>/HotelOps/`**: meta-knowledge umano della realtà operativa che il twin riflette (people, companies, banks, loans, departments, stories). **Non canonical per fatti tecnici** — può essere stale. Verifica sempre con repo + BQ + utente. Per rientrare su un fronte di lavoro (F&B, pf-rotation, cashflow…) usa l'asse **workstream**: `workstreams/<NOME>.md` (hub curato: dove sono / prossimo passo / thread aperti + blocchi Dataview che raccolgono le note `workstream: [<id>]`), registry `workstreams/_INDEX.md`. Ricostruisce lo stato di un filo senza ripartire da zero. Ortogonale a *vertical* (app/audience) e *loop* (processo).

## Behavioral guidelines

**Vedi anche:** `~/.claude/CLAUDE.md` per "surface ambiguity" e "verify before claiming done". Le due regole qui sotto sono complementari, da Karpathy guidelines.

### Simplicity first

Codice minimo che risolve il problema. Niente di speculativo.

- Nessuna feature oltre a quello che è stato chiesto.
- Nessuna astrazione per codice usato una sola volta.
- Nessuna "flessibilità" o "configurabilità" non richiesta.
- Nessun error handling per scenari impossibili.
- Se scrivi 200 righe e potevano essere 50, riscrivile.

Test: "Un senior engineer direbbe che è overcomplicated?" Se sì, semplifica.

### Surgical changes

Tocca solo quello che devi. Pulisci solo il casino che hai fatto tu.

Quando modifichi codice esistente:

- Non "migliorare" codice, commenti o formatting adiacenti.
- Non refactor di cose che non sono rotte.
- Match dello stile esistente, anche se faresti diverso.
- Se noti dead code non correlato, segnalalo — non cancellarlo.

Quando le tue modifiche creano orfani:

- Rimuovi import/variabili/funzioni che le TUE modifiche hanno reso unused.
- Non rimuovere dead code preesistente se non richiesto.

Test: ogni riga modificata deve essere riconducibile direttamente alla richiesta dell'utente.

### Decisive action over exploration

Quando l'utente chiede un fix o un'azione, agisci. Non investigare oltre il necessario.

- Formula un'ipotesi in una frase prima di esplorare.
- Esegui il minimo comando che conferma o smentisce l'ipotesi.
- Se dopo 3-4 chiamate Bash non hai progressi, fermati e chiedi una domanda mirata invece di continuare a scavare.

Pattern noto: Stefano interrompe con "niente" / "perché non usiamo l'app?" quando l'esplorazione si trascina oltre il punto utile.

### Check STATUS.md prima di pianificare

Prima di scrivere plan multi-step, cutover, migration, o di toccare scope cross-cutting:

1. Leggi `STATUS.md` per le decisioni recenti e i thread aperti.
2. Leggi le ultime 1-2 session in `<vault>/HotelOps/sessions/` se l'ultimo task è recente.
3. Scansiona ADR / docs/architecture/INVARIANTS.md per regole già fissate.

Se trovi contraddizioni tra STATUS.md e il piano che stavi per proporre, **fermati e segnalale** — non procedere assumendo che STATUS.md sia obsoleto.

## Project Overview

hotelops is the financial data platform for Gruppo Panorama hotel operations. It ingests data from banks, ERP (Esolver), PMS (HotelCube), and manual budgets into BigQuery, then serves the **condges** (Controllo di Gestione) vertical through two complementary lenses: **Rosa (CASSA)** for cash flow forecasts ("quando il soldo entra/esce?") and **Gasparotto (COMPETENZA)** for budget vs actuals ("quanto consumo/genero?"). Every financial event has three temporal dimensions: COMPETENZA, CASSA, IMPEGNO. BigQuery is the source of truth.

## Architecture

```
core/       <- schemas, config, BQ views, dimensions, lineage, ingest manager
  bq/
    views/       <- 26 SQL view definitions
    dimensioni/  <- CSV sources (d_voci, d_fornitori, d_mapping, d_saldi_banca_chiusura)
    load/        <- dimension loaders + DDL/migrations one-shot (20 scripts)
ingest/     <- continuous data flow pipelines
  classify.py    <- file classifier + router (10 detectors)
  orchestrate.py <- unified pipeline runner
  banca/         <- bank + PMS pipelines
  flussi/        <- recurring accounting pipelines (movimenti, gasparotto, scheda_contabile, etc.)
verticals/  <- domain apps (each consumes core/ + ingest/)
  condges/  <- Controllo di Gestione vertical (Streamlit app, Excel gen, forecasts)
  reviews/  <- Vertical #2: Guest reviews (scrape, classify, alert, dashboard)
cli.py      <- CLI entry point (hotelops command)
```

**core/** -- The world model (nothing here imports from verticals)
- `core/schemas.py` -- Pydantic models + `validate_batch()`. Every BQ write goes through here.
- `core/config.py` -- Table IDs and BQ constants (PROJECT, DATASET). All table refs as `F_*`, `D_*`, `V_*`.
- `core/contracts.py` -- `SchemaViolationError`, `validate_columns()`.
- `core/datahub.py` -- Minimal CSV reader (usato da `verticals/condges/reconcile_banca.py`). Nome legacy, modulo ancora vivo.
- `core/datahub_sync.py` -- **LEGACY** rclone helper (Drive staging pre-GCS). Drive non è più popolato; il Phase 5 cutover rimuoverà questo modulo. Spec: `docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md`.
- `core/bq/client.py` -- BigQuery client singleton (`get_client()`). 41 call sites consolidated 2026-04-19.
- `core/parsers/accodamenti.py` -- Shared parser for HotelCube TXT accodamenti (H_/R_/C_ × Corr/Mov/Fatt). Extracted 2026-04-19 from ingest/banca/.
- `core/pipeline_run.py` -- PipelineRun context manager for pipeline instrumentation (scrive `f_pipeline_runs`).
- `core/ingest_manager.py` -- `IngestManager`: loop di ingestion incrementale source-adapter → GCS (`SourceAdapter` protocol, checkpoint via start_date). Usato da cli.py.
- `core/start_date.py` -- Watermark per load incrementali: `START_DATE_MAP` (tabella BQ, colonna data, fallback) → `get_next_start_date()` / `update_last_processed()`.
- `core/sources/local_folder.py` -- `LocalFolderAdapter`: watch di una cartella locale per nuovi Excel/CSV (adapter per IngestManager).
- `core/bq/views/` -- BigQuery view SQL definitions (source of truth). 26 SQL files.
- `core/bq/dimensioni/` -- Dimension CSV sources (d_voci_piano_finanziario.csv, d_fornitori.csv, d_mapping_piano_finanziario.csv, d_saldi_banca_chiusura_mensile.csv).
- `core/bq/load/` -- 20 script: loaders (load_voci_piano_finanziario, load_piano_conti, load_categorie, load_fornitori, load_anagrafica_fornitori, load_anagrafica_clienti, load_budget_costi, load_coefficienti_stagionalita, load_mapping_piano_finanziario, load_ricavi_storici, load_saldi_banca_chiusura_mensile, load_pf_rotazioni, load_views, load_lineage_tables, load_v_raw_promotion_status) + one-shot DDL/seed/migrations (create_produzione_table, create_progetti_tables, seed_progetti_step1, migrate_add_lineage_era, migrate_add_raw_object_id_bulk).

**core/lineage/** -- Per-raw-object lineage layer (Phase 1, additive)
- `core/lineage/schemas.py` -- Pydantic: SourceDefinition, RawObject, LineageEvent + naming grammar (`<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>` strict 4 parts)
- `core/lineage/source_resolver.py` -- Loads `core/source_registry.yaml` (SSOT policy per source), validates invariant `loop_targets == [] ⇔ promotion_policy == RAW_ONLY` at boot
- `core/lineage/state_machine.py` -- Pure transitions (RAW_ONLY → CLASSIFIED → PROMOTABLE → PROMOTED, REJECTED side-state)
- `core/lineage/policy_gate.py` -- Hard gate: no loop target ⇒ no canonical promotion
- `core/lineage/raw_manifest.py` -- API: register_raw_object + emit_event (always via `bq_write_validated(append)` — I1 strict)

Tabelle: `f_raw_objects` (identity, write-once), `f_lineage_events` (state log, append-only), view `v_raw_objects_current`.
Spec: `docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md`.

**ingest/** -- Reality Capture (file → GCS staging → BigQuery)

**Target model**: `hotelops intake` (RAW → `f_raw_objects` con URI `gs://`) + `hotelops promote` (RAW → canonical via policy gate). Bucket `gs://hotelops-raw` con Object Versioning. Spec: `docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md`.

**Legacy** (Phase 5 cutover pendente — Drive non è più popolato):
- `ingest/classify.py` -- File classifier + router: 10 file type detectors, infers societa+banca, renames and routes.
- `ingest/orchestrate.py` -- Unified pipeline runner (sync → classify → ingest → manifest). Da sostituire con intake+promote.
- `ingest/banca/fetch_drive.py` -- Rclone fetcher (legacy).
- `ingest/banca/` -- Bank and PMS pipelines (ingest.py, ingest_accodamenti.py).
- `ingest/flussi/` -- Recurring accounting pipelines: ingest_movimenti_contabili, ingest_gasparotto, ingest_scheda_contabile, ingest_scheda_190101, ingest_piano_finanziario_xlsx, ingest_partite_aperte, ingest_bilancino, ingest_bilanci_annuali, ingest_consumi_economato (+ ingest_consumi_economato_consolidato), ingest_coperti, ingest_fatture, ingest_vendite_fb, ingest_ricavi_fb, ingest_ristocube_orders, ingest_produzione_pms, ingest_pms_statistiche, budget_orti_xlsx.

**verticals/condges/** -- Vertical #1: Controllo di Gestione (containerizable)
- `verticals/condges/app_cdg.py` -- Streamlit Controllo di Gestione: CE riclassificato, Budget vs Consuntivo, Tesoreria, Indicatori.
- `verticals/condges/cdg_engine.py` -- Pure computation: CE cascade, indicatori (EBITDA, BEP), proiezione anno con stagionalità.
- `verticals/condges/cli_commands.py` -- Extracted CLI handlers (cmd_pf, cmd_health, cmd_chiudi, cmd_saldo, cmd_scadenzario, cmd_accodamenti, cmd_help).
- `verticals/condges/genera_excel.py` -- Generate PF Excel from BQ (color-coded: nero=consuntivo, blu=previsione, verde=formula).
- `verticals/condges/update_previsione.py` -- Write forecasts to f_piano_finanziario_input (DELETE-INSERT, parameterized).
- `verticals/condges/reconcile_banca.py` -- Bank vs ledger reconciliation.
- `verticals/condges/scadenzario_excel.py` -- Excel bridge: scadenzario fornitori → voci PF.
- `verticals/condges/app_scadenzario.py` -- Streamlit scadenzario app.
- `verticals/condges/cassa_giornaliera.py` -- Riconciliazione cassa giornaliera da accodamenti HotelCube. Legge TXT pipe-delimited (H_/R_/C_ × Corr/Mov/Fatt), aggrega per giorno × struttura (POS/contanti/caparre) e produce Excel 2 sheet (Riepilogo + Dettaglio strutture). Porting amputato di `reconciliation_dino` (scartati: IMPPN/TeamSystem, fingerprint state, CSV writer).
- `verticals/condges/accodamenti_service.py` -- Service layer riconciliazione accodamenti: wrappa cassa_giornaliera per app/CLI (parse TXT → aggregati → Excel, anche cumulativo da BQ).
- `verticals/condges/app_accodamenti.py` -- Streamlit: upload TXT accodamenti → riconciliazione cassa via accodamenti_service.
- `verticals/condges/audit_consumi_dashboard.py` -- Streamlit read-only audit consumi F&B per la direzione: canonical-transformation-matrix su 3 vertical (BREAKFAST/RISTORANTE/BAR), 6 layer Ricavi→Consumi→Coperti→KPI→Range industria→Alert. Spec: `docs/superpowers/specs/2026-05-21-audit-consumi-fb-direzione-design.md`.
- `verticals/condges/tesoreria.py` -- Streamlit tesoreria: cabla parse_pf + bq_data + cashflow + export_excel.
- `verticals/condges/bq_data.py` -- Query BQ read-only per la app tesoreria Streamlit (cached `@st.cache_data` ttl=300).
- `verticals/condges/bq_tesoreria_core.py` -- Read BQ tesoreria condivisi tra Streamlit e CLI export (nessun import Streamlit).
- `verticals/condges/cashflow.py` -- Logica di proiezione cashflow pura (no I/O, no BQ).
- `verticals/condges/export_excel.py` -- Export Excel tesoreria pulito/stampabile (`generate_tesoreria_excel`).
- `verticals/condges/gen_tesoreria_xlsx.py` -- CLI: genera Tesoreria Excel da PF (+ scadenzario opzionale), mirror della app Streamlit tesoreria.
- `verticals/condges/parse_pf.py` -- Parser dei master Excel "Piano Finanziario" di Rosa (varianti ORTI+INTUR) → PFData.
- `verticals/condges/scadenze_parse.py` -- Parser condivisi scadenzario fornitori Esolver (sintetica / partite) → ScadenzarioData.
- `verticals/condges/skeleton_shift.py` -- Shift mensile dello skeleton PF: value-cells una colonna a sinistra nel range forward-months, formule lasciate in place.
- `verticals/condges/materialize_reconciliation.py` -- Materializza stato riconciliazione banca: 1 riga per movimento con stato Pending/AutoMatched/Confirmed/Rejected (CSV in datahub meta/).
- `verticals/condges/pf_rotate/` -- Package rotation mensile PF (`hotelops pf-rotate`): `rotate.py` orchestratore + step0_normalize_intur, step1_saldi, step2_azzera, step3_scadenzario, step5_controlli, excel_model, fornitori_map, interactive_map, saldi_registry, diff, cli_handler. Regole in "Financial Data / Cashflow".

**verticals/reviews/** -- Vertical #2: Guest Reviews (Apify scrape -> Claude NLP -> BQ -> alert + dashboard)
- `verticals/reviews/config.py` -- Apify actor IDs, property URLs, thresholds, email recipients.
- `verticals/reviews/scrape.py` -- Trigger Apify actors (Booking, TripAdvisor, Google, Expedia), collect JSON.
- `verticals/reviews/ingest.py` -- Normalize per platform, dedup by review_hash, write to f_reviews.
- `verticals/reviews/classify.py` -- Claude API (Haiku) batch classification: categoria + sentiment + riassunto.
- `verticals/reviews/alert.py` -- Email alert for reviews with punteggio_norm <= 6.0.
- `verticals/reviews/email.py` -- Weekly HTML report + Gmail API send.
- `verticals/reviews/app.py` -- Streamlit dashboard: KPIs, trends, categories, review table.
- `verticals/reviews/cli_commands.py` -- CLI handlers for `hotelops reviews`.
- `verticals/reviews/PROPERTIES.md` -- Reference doc: actors, costs, property URLs, env vars.

**Root**
- `cli.py` -- CLI entry point (`hotelops` command). 28 subcommands (26 in cli.py + `pf-rotate`/`pf-normalize-intur` registrati da `verticals/condges/pf_rotate/cli_handler.py`). Large handlers in `verticals/condges/cli_commands.py` and `verticals/reviews/cli_commands.py`.
- `core/registry.yaml` -- Pipeline registry: file types, dest folders, BQ tables, signatures.

## GCP

- **Project:** `hotelops-suite`
- **Dataset:** `hotelops`
- **Auth:** `gcloud` authenticated as `stefano@panoramagroup.it`

## Commands

```bash
# Install
pip install -e ".[dev]"

# CLI
hotelops pf                                # Piano Finanziario ORTI (all months)
hotelops pf --mese 4                       # Single month
hotelops pf --societa INTUR                # INTUR
hotelops bva                               # Budget vs Consuntivo YTD, top 30 delta
hotelops bva --mese 3                      # Single month
hotelops chiudi                            # Chiusura mese: previsione vs consuntivo + saldo banca + salva snapshot
hotelops chiudi --mese 2 --dry-run         # Preview senza salvare
hotelops saldo                             # Saldo banca corrente + proiezione cash forward 12 mesi
hotelops saldo --societa INTUR             # INTUR
hotelops health                            # Health check: freshness, gaps, alerts
hotelops voci                              # List PF voci
hotelops previsione utenze 4-12 22000      # Update forecast: utenze ORTI Apr-Dec
hotelops previsione "entrate hotel" aprile-ottobre 180000  # Natural language months
hotelops manifest                              # Generate BQ table catalog (manifest.yaml)
hotelops manifest --table f_consumi_economato  # Single table
hotelops deploy-views                          # Deploy all BQ views from core/bq/views/ (dependency-ordered)
hotelops deploy-views --dry-run                # Show deploy order without executing
hotelops classifica file1.xlsx file2.csv       # Classify files (show type + destination)
hotelops classifica *.xlsx --route --ingest    # Classify + route + ingest
hotelops accodamenti --no-sync --input <dir>   # Riconciliazione cassa da TXT HotelCube → Excel su Desktop (Drive non più popolato: usa --no-sync)

# Lineage (Phase 1)
hotelops intake <file> --source-name X      # Register a file (RAW_INGESTED event)
hotelops promote --raw-object-id Y          # Promote PROMOTABLE → PROMOTED
hotelops lineage Y                          # Inspect raw_object identity + event history
hotelops intake <xlsx> --source-name POWERBI_RICAVIFB_ORTI_SNAPSHOT  # Ricavi F&B → GCS + f_raw_objects
hotelops promote --raw-object-id <id>                                # → parser ingest_ricavi_fb → f_ricavi_fb
python -m ingest.flussi.ingest_ricavi_fb --file <xlsx> --dry-run     # Parser standalone, preview
hotelops intake "Orders Report RISTOCUBE*.xlsx" --source-name RISTOCUBE_ORDERS_ORTI_APPEND  # Orders → GCS + f_raw_objects
hotelops promote --raw-object-id <id>                                # → parser ingest_ristocube_orders → f_ristocube_orders
python -m ingest.flussi.ingest_ristocube_orders --file <xlsx> --dry-run  # Parser standalone, preview

# Reviews vertical
hotelops reviews                           # Ultime 30 reviews, media, negative
hotelops reviews --scrape                  # Scrape tutte le piattaforme
hotelops reviews --scrape --only booking   # Solo Booking
hotelops reviews --scrape --dry-run        # Preview senza scraping
hotelops reviews --stats                   # Stats mese corrente per piattaforma
hotelops reviews --stats --mese 3          # Stats mese specifico
hotelops reviews --alert                   # Mostra review che hanno generato alert
hotelops reviews --report                  # Invia report settimanale manualmente
streamlit run verticals/reviews/app.py               # Dashboard reviews

# Condges vertical
streamlit run verticals/condges/app_cdg.py               # Controllo di Gestione (CE, Budget, Tesoreria, Indicatori)
python -m verticals.condges.genera_excel --output ~/Desktop/PF.xlsx
python -m verticals.condges.update_previsione --voce utenze --societa ORTI --mesi 4-12 --importo 22000

# Ingest pipelines
python -m ingest.orchestrate                           # Run everything (sync + ingest all)
python -m ingest.orchestrate --dry-run                 # Parse + CSV, no BQ writes
python -m ingest.orchestrate --only banca              # Only bank group
python -m ingest.orchestrate --only flussi             # Only recurring accounting
python -m ingest.orchestrate --only dimensioni         # Only dimension tables
python -m ingest.orchestrate --pipeline gasparotto     # Single pipeline

# Individual flussi pipelines
python -m ingest.flussi.ingest_movimenti_contabili --datahub /path/to/datahub
python -m ingest.flussi.ingest_gasparotto --file "Master Completo....xlsx" --societa ORTI
python -m ingest.flussi.ingest_partite_aperte --file situazione_partite.xlsx
python -m ingest.flussi.ingest_scheda_contabile --datahub /path/to/datahub

# Dimension loaders
python -m core.bq.load.load_voci_piano_finanziario
python -m core.bq.load.load_piano_conti
python -m core.bq.load.load_categorie
python -m core.bq.load.load_fornitori
python -m core.bq.load.load_anagrafica_fornitori
python -m core.bq.load.load_mapping_piano_finanziario
python -m core.bq.load.load_coefficienti_stagionalita
python -m core.bq.load.load_ricavi_storici
python -m core.bq.load.load_budget_costi
python -m core.bq.load.load_saldi_banca_chiusura_mensile   # Saldi certificati fine mese (anchor cash_control)

# Test / lint
pytest
ruff check .
ruff format .
```

## BigQuery Tables

### Fact tables

Two lifecycle types: **APPEND** (each file adds rows, MD5 dedup) vs **SNAPSHOT** (latest file replaces previous data via DELETE-INSERT).

| Table | Description |
|-------|-------------|
| `f_banche_movimenti` | Bank transactions -- MPS, MPS_KROSS, SELLA, INTESA, BCP x ORTI/INTUR (APPEND) |
| `f_movimenti_contabili` | Esolver prima nota. CodConto senza punti (570913) (APPEND) |
| `f_budget_mensile` | Budget mensile per codice conto. Fonti: GASPAROTTO, MAPPATURA, INCIDENZA (SNAPSHOT) |
| `f_piano_finanziario_input` | Cash flow previsioni: 28 voci x 12 mesi. Fonti: PIANO_FINANZIARIO, SCADENZIARIO, BVA_2026, CLI, APP (SNAPSHOT) |
| `f_accodamenti` | Vendite da HotelCube PMS: corrispettivi, caparre, fatture attive (APPEND) |
| `f_bilancino` | Bilancio di verifica Esolver, solo leaf nodes (SNAPSHOT) |
| `f_consumi_economato` | Consumi materie prime per reparto/prodotto — 33 reparti canonici dal re-ingest consolidato 2026-05-21 (APPEND) |
| `f_coperti_giornalieri` | Coperti pasto giornalieri per BU/tipo_ospite (APPEND) |
| `f_chiusura_mensile` | Snapshot chiusura mese: previsione vs consuntivo per voce + saldo banca (SNAPSHOT) |
| `f_saldi_banca_snapshot` | Registro contabile banca da Esolver, end-of-day running balance (APPEND) |
| `f_partite_aperte_fornitori` | Snapshot partite aperte fornitori (IMPEGNO dimension) (SNAPSHOT) |
| `f_mastrino_consolidato` | Mastrino consolidato da "Costi Ricavi 2025-2026 Budget.xlsx" (APPEND) |
| `f_ricavi_storici` | Riepilogo Entrate mensili 2023-2025 per BU (APPEND) |
| `f_coefficienti_consumo` | Coefficienti consumo per reparto/prodotto (APPEND) |
| `f_pms_statistiche` | Statistiche PMS HotelCube (APPEND) |
| `f_affidamenti` | Affidamenti bancari (linee di credito) -- schema TBD |
| `f_reviews` | Guest reviews da OTA (Booking, TripAdvisor, Google, Expedia). NLP classified. (APPEND) |
| `f_vendite_fb` | Vendite F&B POS (giorno × sala × articolo) da Ristocube. Include `segmento_cliente`. (APPEND, dedup hash_riga) |
| `f_ricavi_fb` | Ricavi F&B per struttura × mese × codice pasto (Produzione Netta PMS, export Power BI). Drill-down di classe 02FB. Ingerita via lineage (source `POWERBI_RICAVIFB_ORTI_SNAPSHOT`). (SNAPSHOT, natural_key business_unit_id+anno+mese) |
| `f_ristocube_orders` | Comande RistoCube POS a livello item × comanda. Campi comanda (sala, tavolo, coperti, segmento_cliente, modalita_chiusura) ereditati da ogni item. Ingerita via lineage (source `RISTOCUBE_ORDERS_ORTI_APPEND`). (APPEND, dedup hash_riga, partition DAY su data, cluster sala/segmento/comanda_id) |
| `f_produzione_pms` | Produzione giornaliera HotelCube per struttura × classe ricavo (Daily Production Report, Imponibile, export Power BI). Drill-down giorno×classe; `societa_id` derivata dal cutover 2025-04-01. Ingerita via lineage (source `POWERBI_PRODUZIONE_ORTI_SNAPSHOT`). (SNAPSHOT, natural_key business_unit_id+anno, partition DAY su data, cluster business_unit_id/classe) |
| `f_fatture_righe` | Registro fatture Esolver acquisto/vendita a livello riga, contropartite con cod_conto. Canale complementare alla prima nota — insieme quadrano col bilancino per classe (vedi `v_ce_macro_mensile`). Parser `ingest/flussi/ingest_fatture.py`, sources `ESOLVER_FATTURE{ACQUISTO,VENDITA}_{ORTI,INTUR}_APPEND`. (APPEND) |
| `f_saldi_banca_chiusura_mensile` | Saldi banca certificati a fine mese (fonte manuale/tesoreria) — **anchor del loop `cash_control`**: se presente per (societa, data, banca) ha priorità su snapshot Esolver + movimenti in `hotelops chiudi` e nel calcolo saldi CLI. Source: `core/bq/dimensioni/d_saldi_banca_chiusura_mensile.csv` → `core.bq.load.load_saldi_banca_chiusura_mensile` |
| `f_bilanci_annuali` | Bilanci annuali da XBRL markdown (Registro Imprese): una riga per societa × anno × sezione × voce. Parser `ingest/flussi/ingest_bilanci_annuali.py`. (SNAPSHOT per societa+anno) |
| `f_apify_runs` | Observability reviews: una riga per run Apify actor (costi scraping). Scritta da `verticals/reviews/scrape.py`. (APPEND) |
| `f_pipeline_runs` | Observability layer 2: una riga per esecuzione pipeline ("il cron ha girato? è andato a buon fine?"). Scritta da `core/pipeline_run.py`. (APPEND) |
| `f_progetto_voci` | CapEx: righe di scope per progetto, `voce_id = {progetto_id}.{seq}`. (SNAPSHOT per voce_id) |
| `f_progetto_eventi` | CapEx: eventi immutabili sul thread di una voce progetto (lifecycle IMPEGNO→COMPETENZA→CASSA→CHIUSURA). (APPEND) |

### Dimension tables

| Table | Description |
|-------|-------------|
| `d_voci_piano_finanziario` | 28 voci PF mappate a codici conto Esolver via LIKE patterns. Source: `core/bq/dimensioni/d_voci_piano_finanziario.csv` |
| `d_mapping_piano_finanziario` | 220 rows connecting PF sotto-voci to Esolver codes per-societa. Source: `core/bq/dimensioni/d_mapping_piano_finanziario.csv` |
| `d_piano_conti` | Piano dei conti 2026 -- 160 conti con codice (dotted), tipo, sezione (CE/SP) |
| `d_categorie_conti` | Mapping canonici: codice_conto -> (tipo_costo, categoria_ce). 167 righe |
| `d_fornitori` | Fornitori ORTI (65) con voce_id e flag intercompany. Source: `core/bq/dimensioni/d_fornitori.csv` |
| `d_anagrafica_fornitori` | Anagrafica fornitori completa per riconciliazione partite |
| `d_budget_costi_fissi` | Costi fissi annuali per BU (43 righe) |
| `d_personale_mensile` | Costi personale mensili per divisione (78 righe) |
| `d_coefficienti_stagionalita` | Monthly seasonality multipliers per BU, computed from f_ricavi_storici. Sum=12.0 |
| `d_periodi_apertura` | Calendario stagionale apertura/chiusura per BU (3 righe) |
| `d_progetti` | Anagrafica progetti CapEx (progetto_id es. HPAN25PIANO1, SPIAGGIA_LOTTO7). SNAPSHOT per progetto_id |

### Views

| View | Description |
|------|-------------|
| `v_piano_finanziario_mensile` | Rosa's view: Budget vs consuntivo per voce PF, rolling 18 mesi. `core/bq/views/` |
| `v_piano_finanziario_consuntivo` | Actuals per voce PF via d_voci LIKE patterns. `core/bq/views/` |
| `v_budget_vs_consuntivo` | Gasparotto's view: Budget vs actuals per cod_conto x mese. ROW_NUMBER fonte priority dedup. `core/bq/views/` |
| `v_pl_movimenti` | P&L: ricavi - costi per categoria CE. `core/bq/views/` |
| `v_cashflow_mensile` | Cashflow mensile aggregato da banca. `core/bq/views/` |
| `v_incassi_per_canale` | Entrate bancarie per canale (BONIFICO, CARTE, CONTANTI, ALTRO). `core/bq/views/` |
| `v_previsione_cassa` | Cash forward rolling 12 mesi, stato_liquidita semaphore. `core/bq/views/` |
| `v_condges_budget_consuntivo` | Looker: Budget vs consuntivo per codice conto, dual CE/PF labels. `core/bq/views/` |
| `v_condges_pf_mensile` | Looker: Piano Finanziario 28 voci with labels + DATE. `core/bq/views/` |
| `v_condges_cashflow` | Looker: Cashflow actuals + 12m projection + semaphore. `core/bq/views/` |
| `v_economato_consumi` | Looker: Consumi per reparto/prodotto + YoY + coefficients. `core/bq/views/` |
| `v_economato_pareto` | Looker: ABC analysis top referenze per reparto. `core/bq/views/` |
| `v_budget` | Budget consolidato per codice conto. `core/bq/views/` |
| `v_condges_banca_dettaglio` | Looker: Dettaglio movimenti banca per analisi. `core/bq/views/` |
| `v_ledger_movimenti` | Bank reconciliation ledger: dedup SCHEDA_190101 vs PNC per day, excludes 'Ripresa saldi'. `core/bq/views/` |
| `v_economato_costo_unitario` | Looker: costo unitario per pax-notte per reparto × articolo × mese + ABC ranks. `core/bq/views/` |
| `v_food_cost_mensile` | Food cost macro mensile: costi CUCINA+CANTINA + ricavi POS + coperti hotel + YoY (LAG su anno). `core/bq/views/` |
| `v_food_cost_categoria` | Food cost granulare per (anno, mese, sala, tipo_piatto, segmento_cliente) + €/coperto + YoY. `core/bq/views/` |
| `v_fb_consumi` | Looker F&B: costo merce per prodotto/categoria + scomposizione prezzo/volume + YoY. Anni >= 2025. `core/bq/views/` |
| `v_fb_pasti` | Looker F&B: conteggio pasti per BU, mensile, YoY. Anni >= 2025. `core/bq/views/` |
| `v_fb_ricavi` | Looker F&B: ricavi per BU × codice + scontrino medio + YoY. Anni >= 2025. `core/bq/views/` |
| `v_fb_kpi` | Looker F&B: bridge mensile in **3 bucket onesti** (breakfast / ristorante=CUCINA / bar=CANTINA) — ricavi split food vs beverage, `food_cost_pct_ristorante` + `food_cost_pct_bar` separati, €/pasto. 9 articoli UoM-rotti esclusi per `codice_prodotto`. Anni >= 2025. `core/bq/views/` |
| `v_ce_macro_mensile` | CE mensile per macro classe: unione prima nota (`f_movimenti_contabili`) + registro fatture (`f_fatture_righe`) — insieme quadrano col bilancino per classe (verificato ORTI YTD mag 2026). Corrispettivi PMS esclusi: per i ricavi gestionali completi usare `f_produzione_pms`. `core/bq/views/` |
| `v_budget_canonical` | Budget canonico per codice conto: dedup fonte priority (GASPAROTTO > MAPPATURA > INCIDENZA), invariant I8. `core/bq/views/` |
| `v_raw_objects_current` | Lineage: stato corrente per raw_object (latest event per oggetto). `core/bq/views/` |
| `v_raw_promotion_status` | Lineage: stato promozione raw objects (RAW→CLASSIFIED→PROMOTABLE→PROMOTED) + freshness. `core/bq/views/` |

### How the views connect

```
f_movimenti_contabili --+
                        +- JOIN d_voci_piano_finanziario (LIKE patterns) --> v_piano_finanziario_consuntivo
f_banche_movimenti -----+                                                          |
                                                                                    +---> v_piano_finanziario_mensile
f_budget_mensile ------ JOIN d_voci_piano_finanziario (LIKE patterns) --------------+     (scaffold x consuntivo x budget x input)
                                                                                    |
f_piano_finanziario_input -- direct voce_id FK ----------------------------------------+

f_movimenti_contabili -- JOIN d_categorie_conti --> v_budget_vs_consuntivo (BQ-only)
f_budget_mensile ------- FULL OUTER JOIN ----------+

f_saldi_banca_snapshot --+
v_piano_finanziario_mensile --+---> v_previsione_cassa (cash forward 12m)
f_partite_aperte_fornitori --+

v_piano_finanziario_mensile --> `hotelops chiudi` --> f_chiusura_mensile (snapshot delta)
f_banche_movimenti ------------+                      (traccia accuratezza previsioni)
```

## Data model

Every fact row carries **5 dimensions**: `societa_id`, `business_unit_id`, `funzione_id`, `location_id`, `oggetto_id`.

**Account code formats:** d_piano_conti uses dots (57.09.13), f_movimenti_contabili uses no dots (570913). Join with `REPLACE(codice_conto, '.', '')`.

**Sign conventions:**
- Views: ENTRATE positive = entrata, USCITE positive = uscita
- Esolver: ENTRATE = imp_avere - imp_dare, USCITE = imp_dare - imp_avere
- Banche: importo_netto positive = entrata, negative = uscita

### d_voci_piano_finanziario -- the mapping layer

28 voci that map the Piano Finanziario structure to Esolver account codes:
- 11 ENTRATE (Hotel, Residence, CVM, Supermercato, Spiaggia, Affitti, Caparre, etc.)
- 17 USCITE (Salari, Utenze, Materie Prime, Tasse, Mutui, Commissioni, Consulenze, Marketing, etc.)
- fonte=ESOLVER: joins via cod_conto_pattern LIKE
- fonte=BANCHE: joins via banca_tipo_pat LIKE on tipo_movimento
- fonte=MANUALE: only via f_piano_finanziario_input.voce_id FK

Source CSV: `core/bq/dimensioni/d_voci_piano_finanziario.csv`.

### d_mapping_piano_finanziario -- detailed sotto-voce mapping

220 rows connecting PF sotto-voci to Esolver account codes, per-societa. Enables finer-grained mapping than d_voci LIKE patterns. Source CSV: `core/bq/dimensioni/d_mapping_piano_finanziario.csv`.

### Budget sources

| Fonte | Scope | Granularity | Where |
|-------|-------|-------------|-------|
| GASPAROTTO | Full CE | Company-level, seasonality-adjusted | f_budget_mensile |
| MAPPATURA | Fixed/variable costs | Per BU (HOTEL, RESIDENCE, CVM, LIDO) | f_budget_mensile |
| INCIDENZA | Payroll costs | Per divisione | f_budget_mensile |
| PIANO_FINANZIARIO | Cash flow (28 voci) | ORTI+INTUR monthly | f_piano_finanziario_input |
| SCADENZIARIO | Loan schedules | Per voce x mese | f_piano_finanziario_input |
| BVA_2026 | Revenue budgets | Per voce x mese | f_piano_finanziario_input |
| CLI/NANOCLAW | Manual forecast updates | Per voce x mese | f_piano_finanziario_input |
| APP | Streamlit app saves | Per voce x mese | f_piano_finanziario_input |

## Entities

### Societa (legal entities)

- **ORTI** -- gestione operativa: vendite, acquisti, costi di Hotel, Residence, CVM. Paga fitto a INTUR (conto 6511).
- **INTUR** -- proprieta e aspetti finanziari (mutui, IVA, fatture). Possiede Hotel+Spiaggia+Immobili. Gestisce direttamente solo il Lido.

**Relazione critica**: ORTI non genera cash -> non paga fitto -> INTUR non paga mutui -> rischio default. Il fitto ORTI->INTUR e intercompany e si cancella nel consolidato.

### Business Units

| business_unit_id | Nome | Note |
|---|---|---|
| `HOTEL` | Hotel Panorama | Hotel 4* a Maiori, stagionale apr-ott |
| `RESIDENCE` | Angelina Residence | Appartamenti, tutto l'anno |
| `CVM` | Casa Vacanze Maiori | Appartamenti vacanza, tutto l'anno |
| `LIDO` | Lido / Spiaggia | Concessione balneare, INTUR |
| `HQ` | Sede / Amministrazione | Funzioni centrali |

### Banks

- **MPS** -- Monte dei Paschi di Siena (conto principale)
- **MPS_KROSS** -- MPS conto Kross (separato)
- **SELLA** -- Banca Sella
- **INTESA** -- Intesa Sanpaolo
- **BCP** -- Banca di Credito Popolare (INTUR only)

#### Esolver bank account mapping (Cc# -> banca_id)

| Societa | Cc# | banca_id | Banca |
|---------|-----|----------|-------|
| ORTI | Cc1 | INTESA | Intesa Sanpaolo |
| ORTI | Cc2 | MPS | Monte dei Paschi |
| ORTI | Cc3 | MPS_KROSS | MPS Kross |
| INTUR | Cc1 | SELLA | Banca Sella |
| INTUR | Cc2 | MPS | Monte dei Paschi |
| INTUR | Cc3 | INTESA | Intesa Sanpaolo |
| INTUR | Cc4 | BCP | Banca di Credito Popolare |

## Financial Data / Cashflow

Regole specifiche per le rotation mensili del Piano Finanziario (`hotelops pf-rotate`).

**Layout-aware = obbligatorio.** Esistono due layout strutturalmente diversi del master "Piano Finanziario":

- **ORTI (`snapshot_kind="month-closed"`)**: colonna del mese chiuso (es. C per APR) ospita saldi banche puntuali + saldo iniziale hardcoded.
- **INTUR (`snapshot_kind="fixed-snapshot"`)**: colonna C è snapshot fisso con `C1="DATA RILEVAZ"`, `C2=<data>`, saldi puntuali in `C31:C33`. La colonna del mese chiuso resta vuota sulle righe saldi.

`PFLayout.snapshot_kind` viene dedotto da `find_layout(wb)` leggendo `pf["C1"]`. Step 1 (saldi), step 2 (azzera) e step 5 (controlli) sono branched per `snapshot_kind`.

**Mai azzerare formule.** Step 2 ("azzera mese chiuso") tocca solo `is_value_cell(cell)` — numero, stringa, o formula-di-costanti (es. `=110000+160000`). **Formule con riferimenti A1-style (`=Utenze!K3`, `=SUM(D5:D11)`, `=C37`) non vengono MAI sovrascritte**. Questo è il vincolo che protegge le cascate cross-sheet (uscite) e i link strutturali.

**File output nuovo, mai mutare l'input.** Naming: `<societa>_PF_<YYYY-MM>_post-rotate_<timestamp>.xlsx`, dove `YYYY-MM` è il **primo mese aperto** (data_saldo + 1 mese): il PF post-rotazione di aprile parte dai saldi al 30/04 ed è il file `2026-05`. Se step 5 trova ERR il file riceve suffisso `_FAILED_CHECKS` ma viene comunque scritto (per debug visivo in Excel).

**Smoke verificato end-to-end** prima di dichiarare "rotation funziona":
- ORTI: `hotelops pf-rotate --societa ORTI --pf <file_pre> --scad <scadenzario> --scad-tipo sintetica --mese-chiuso aprile --data-saldo 2026-04-30 --unmapped-policy skip --out /tmp/pf-out`
- INTUR: prerequisite `hotelops pf-normalize-intur --pf <intur_pre> --out /tmp/pf-out/intur.normalized.xlsx`, poi `hotelops pf-rotate --societa INTUR --pf /tmp/pf-out/intur.normalized.xlsx ...`

Attesi: ORTI 13/0/7, INTUR 12/0/8 (INDET sono celle-formula non valutabili in puro Python — accettabili).

## Git Conventions

In aggiunta alle regole git globali (vedi `~/.claude/CLAUDE.md`):

- **Mai `git checkout main -- .`** o broad checkouts su working tree dirty. Usa `git stash` prima, o opera su path specifici (`git checkout main -- <path/specifico>`).
- **Mai `git add .` o `git add -A`** quando il working tree ha file untracked non-cashflow (es. `vault/` stub, `.env`). Stagia solo i file pertinenti al commit per nome.
- **Commit logicamente atomici, non micro-step**: preferenza per "feat(X): goal completo" piuttosto che "feat(X): step 1", "feat(X): step 2". Eccezione: spec/plan committati separatamente dall'implementazione.
- **Branch `feat/cashflow`**: pf-rotate sprint. `verticals-v2`: laboratorio frozen, NON toccare. `main`: branch operativo.

## Governance Rules

- Every pipeline reads from its dedicated datahub folder and writes to BigQuery.
- Every fact row must carry all 5 dimensions.
- No speculative modules -- pipelines are born from real data flows.
- Never modify `fatti/` manually -- pipelines only.
- All budget data carries a `fonte` tag -- never mix fonti without explicit filter.
- d_voci_piano_finanziario is the single mapping layer between PF voci and Esolver codici conto.

## NanoClaw Agent Integration

NanoClaw (WhatsApp agent) is a query + ingest channel. It uses `ingest/classify.py` to classify
and route files received via WhatsApp. Configuration lives in the NanoClaw repo
(`~/education/repos/AI_repos/nanoclaw/groups/hotelops/`).

## Tests and Dependencies

Python >=3.11. Run: `pytest`. Lint: `ruff check .` / `ruff format .`

```
tests/
  test_budget_canonical.py       -- Invariant tests for v_budget_canonical (fonte priority, I8)
  test_cassa_giornaliera.py      -- Daily cash reconciliation from accodamenti TXT
  test_cdg_engine.py             -- CDG computation engine (CE cascade, indicatori, proiezione)
  test_classify.py               -- File classifier: 65 tests, all 10 detectors + routing + lifecycle
  test_contracts.py              -- Schema validation tests
  test_health_checks.py          -- Watermark + pipeline staleness checks
  test_ingest_gasparotto.py      -- Gasparotto Budget → f_budget_mensile ingest (timedelta decoder + CE parser)
  test_ingest_movimenti_xlsx.py  -- Movimenti contabili XLSX ingestion tests
  test_manifest.py               -- BQ manifest generation tests
  test_materialize.py            -- Materialization tests
  test_pipeline_run.py           -- PipelineRun context manager
  test_reviews_alert.py          -- Review alert logic + email rendering
  test_reviews_classify.py       -- Reviews NLP classification
  test_reviews_ingest.py         -- Reviews ingest: normalization + dedup
  test_reviews_schema.py         -- ReviewRow schema validation
  test_reviews_schema_sync.py    -- Contract: reviews NLP enums in sync across code + schema
  test_reviews_scrape.py         -- Apify actor input builder
  test_reviews_watermark.py      -- Watermark-based review filtering
  test_scadenzario.py            -- Scadenzario Excel bridge tests
  test_stagionalita.py           -- Seasonality coefficient tests
```

Core: `pyyaml`, `openpyxl`, `pandas`, `google-cloud-bigquery`, `pydantic`.
Optional: `bank-reconcile` (`.[reconcile]`), `streamlit + plotly + db-dtypes` (`.[dashboard]`).
Dev: `pytest`, `ruff` (`.[dev]`).
