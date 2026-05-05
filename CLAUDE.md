# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Last checkpoint:** 2026-04-30 | **Version:** 0.6.0

> **2026-04-30 session save:**
> - Sprint 1 chiuso e mergiato su `main`: `bq_write_validated` gate centralizzato (Pydantic + boundary check + lineage), 3 pilot SNAPSHOT validati su BQ produzione (scheda, partite, coperti).
> - Sprint 2 Phase 1: `f_vendite_fb` (vendite POS Ristocube, 19,806 righe, range 2024-03..2026-04, con `segmento_cliente`). Primo APPEND pilot via gate.
> - Magazzino aggiornato fino a 2026-03 (+5 file ECO_*). Aspetta APRILE 2026.
> - Nuove views: `v_food_cost_mensile`, `v_food_cost_categoria` (con segmento esposto). YoY 2024 vs 2025 sbloccato.
> - Parking lot Sprint 3: file `Stampa Consumi` (giornaliero), file `Ristocube (1)` (consumi giornalieri €), file `Ristocube (4)` (menu engineering: food cost per piatto). `d_prezzi_pensione` da definire (TBD se serve, dato che File 3 ha già segmento `ZRISTINT/EST/RES` per pensione).
> - Per il rollout dei codici Segmento Cliente: glossario interno richiesto (vuoto, INLE, INTUI, GRLE, GRBU, GRWE, GRSE, FERR25, ZRISTINT, ZRISTEST, ZRISRES). Decodifica downstream nelle views/dashboard.

> **For AI agents**: ground truth = repo + BigQuery schema. Read in this order before non-trivial work:
> 1. `docs/architecture/INVARIANTS.md` — la costituzione (I1–I8, canonical per concept). [migrato dal vault il 2026-04-30]
> 2. `docs/architecture/AI_INSTRUCTIONS.md` — layer model, canonical truth registry, operational loop, anti-goals.
> 3. `docs/architecture/LE_3_DIMENSIONI.md` — il concetto temporale più importante del sistema.
> 4. `CLAUDE.md` (this file) — repo mechanics: commands, schemas, pipeline internals.
>
> **Goal di lungo termine**: HotelOps è un **digital twin** delle vere operazioni del business. 3 layer:
> - **Code** (`core/`, `ingest/`, `condges/`, `reviews/`): come opera il twin.
> - **BigQuery**: cosa il twin osserva.
> - **Vault `<vault>/HotelOps/`**: meta-knowledge umano della realtà operativa che il twin riflette (people, companies, banks, loans, departments, stories). **Non canonical per fatti tecnici** — può essere stale. Verifica sempre con repo + BQ + utente.

## Project Overview

hotelops is the financial data platform for Gruppo Panorama hotel operations. It ingests data from banks, ERP (Esolver), PMS (HotelCube), and manual budgets into BigQuery, then serves the **condges** (Controllo di Gestione) vertical through two complementary lenses: **Rosa (CASSA)** for cash flow forecasts ("quando il soldo entra/esce?") and **Gasparotto (COMPETENZA)** for budget vs actuals ("quanto consumo/genero?"). Every financial event has three temporal dimensions: COMPETENZA, CASSA, IMPEGNO. BigQuery is the source of truth.

## Architecture

```
core/       <- schemas, config, BQ views, dimensions, ontology loaders
  bq/
    views/       <- 16 SQL view definitions
    dimensioni/  <- CSV sources (d_voci, d_fornitori, d_mapping)
    load/        <- dimension loaders (9 scripts -- load rarely-changed tables)
ingest/     <- continuous data flow pipelines
  classify.py    <- file classifier + router (10 detectors)
  orchestrate.py <- unified pipeline runner
  banca/         <- bank + PMS pipelines
  flussi/        <- recurring accounting pipelines (movimenti, gasparotto, scheda_contabile, etc.)
condges/    <- Controllo di Gestione vertical (Streamlit app, Excel gen, forecasts)
reviews/    <- Vertical #2: Guest reviews (scrape, classify, alert, dashboard)
cli.py      <- CLI entry point (hotelops command)
```

**core/** -- The world model (nothing here imports from verticals)
- `core/schemas.py` -- Pydantic models + `validate_batch()`. Every BQ write goes through here.
- `core/config.py` -- Table IDs and BQ constants (PROJECT, DATASET). All table refs as `F_*`, `D_*`, `V_*`.
- `core/contracts.py` -- `SchemaViolationError`, `validate_columns()`.
- `core/datahub.py` -- Minimal CSV reader for local fact tables.
- `core/datahub_sync.py` -- Centralized rclone/Drive sync (7 sites consolidated 2026-04-19).
- `core/bq/client.py` -- BigQuery client singleton (`get_client()`). 41 call sites consolidated 2026-04-19.
- `core/parsers/accodamenti.py` -- Shared parser for HotelCube TXT accodamenti (H_/R_/C_ × Corr/Mov/Fatt). Extracted 2026-04-19 from ingest/banca/.
- `core/pipeline_run.py` -- PipelineRun context manager for pipeline instrumentation.
- `core/bq/views/` -- BigQuery view SQL definitions (source of truth). 16 SQL files.
- `core/bq/dimensioni/` -- Dimension CSV sources (d_voci_piano_finanziario.csv, d_fornitori.csv, d_mapping_piano_finanziario.csv).
- `core/bq/load/` -- Dimension loaders: load_voci_piano_finanziario, load_piano_conti, load_categorie, load_fornitori, load_anagrafica_fornitori, load_budget_costi, load_coefficienti_stagionalita, load_mapping_piano_finanziario, load_ricavi_storici.

**core/lineage/** -- Per-raw-object lineage layer (Phase 1, additive)
- `core/lineage/schemas.py` -- Pydantic: SourceDefinition, RawObject, LineageEvent + naming grammar (`<SYSTEM>_<DATASET>_<SOCIETA>_<LIFECYCLE>` strict 4 parts)
- `core/lineage/source_resolver.py` -- Loads `core/source_registry.yaml` (SSOT policy per source), validates invariant `loop_targets == [] ⇔ promotion_policy == RAW_ONLY` at boot
- `core/lineage/state_machine.py` -- Pure transitions (RAW_ONLY → CLASSIFIED → PROMOTABLE → PROMOTED, REJECTED side-state)
- `core/lineage/policy_gate.py` -- Hard gate: no loop target ⇒ no canonical promotion
- `core/lineage/raw_manifest.py` -- API: register_raw_object + emit_event (always via `bq_write_validated(append)` — I1 strict)

Tabelle: `f_raw_objects` (identity, write-once), `f_lineage_events` (state log, append-only), view `v_raw_objects_current`.
Spec: `docs/superpowers/specs/2026-05-05-ingest-lineage-gcs-design.md`.

**ingest/** -- Reality Capture (Drive/Excel/CSV -> BigQuery)
- `ingest/classify.py` -- File classifier + router: 10 file type detectors, infers societa+banca, renames and routes to datahub.
- `ingest/orchestrate.py` -- Unified pipeline runner. Sync -> classify -> ingest -> manifest. Groups: banca, flussi, dimensioni.
- `ingest/banca/` -- Bank and PMS pipelines (ingest.py, ingest_accodamenti.py, fetch_drive.py).
- `ingest/flussi/` -- Recurring accounting pipelines: ingest_movimenti_contabili, ingest_gasparotto, ingest_scheda_contabile, ingest_piano_finanziario_xlsx, ingest_partite_aperte, ingest_bilancino, ingest_consumi_economato, ingest_coperti.

**condges/** -- Vertical #1: Controllo di Gestione (containerizable)
- `condges/app_cdg.py` -- Streamlit Controllo di Gestione: CE riclassificato, Budget vs Consuntivo, Tesoreria, Indicatori.
- `condges/cdg_engine.py` -- Pure computation: CE cascade, indicatori (EBITDA, BEP), proiezione anno con stagionalità.
- `condges/cli_commands.py` -- Extracted CLI handlers (cmd_pf, cmd_health, cmd_chiudi, cmd_saldo, cmd_scadenzario, cmd_accodamenti, cmd_help).
- `condges/genera_excel.py` -- Generate PF Excel from BQ (color-coded: nero=consuntivo, blu=previsione, verde=formula).
- `condges/update_previsione.py` -- Write forecasts to f_piano_finanziario_input (DELETE-INSERT, parameterized).
- `condges/reconcile_banca.py` -- Bank vs ledger reconciliation.
- `condges/scadenzario_excel.py` -- Excel bridge: scadenzario fornitori → voci PF.
- `condges/app_scadenzario.py` -- Streamlit scadenzario app.
- `condges/cassa_giornaliera.py` -- Riconciliazione cassa giornaliera da accodamenti HotelCube. Legge TXT pipe-delimited (H_/R_/C_ × Corr/Mov/Fatt), aggrega per giorno × struttura (POS/contanti/caparre) e produce Excel 2 sheet (Riepilogo + Dettaglio strutture). Porting amputato di `reconciliation_dino` (scartati: IMPPN/TeamSystem, fingerprint state, CSV writer).

**reviews/** -- Vertical #2: Guest Reviews (Apify scrape -> Claude NLP -> BQ -> alert + dashboard)
- `reviews/config.py` -- Apify actor IDs, property URLs, thresholds, email recipients.
- `reviews/scrape.py` -- Trigger Apify actors (Booking, TripAdvisor, Google, Expedia), collect JSON.
- `reviews/ingest.py` -- Normalize per platform, dedup by review_hash, write to f_reviews.
- `reviews/classify.py` -- Claude API (Haiku) batch classification: categoria + sentiment + riassunto.
- `reviews/alert.py` -- Email alert for reviews with punteggio_norm <= 6.0.
- `reviews/email.py` -- Weekly HTML report + Gmail API send.
- `reviews/app.py` -- Streamlit dashboard: KPIs, trends, categories, review table.
- `reviews/cli_commands.py` -- CLI handlers for `hotelops reviews`.
- `reviews/PROPERTIES.md` -- Reference doc: actors, costs, property URLs, env vars.

**Root**
- `cli.py` -- CLI entry point (`hotelops` command). 16 subcommands. Large handlers in `condges/cli_commands.py` and `reviews/cli_commands.py`.
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
hotelops classifica file1.xlsx file2.csv       # Classify files (show type + destination)
hotelops classifica *.xlsx --route --ingest    # Classify + route + ingest
hotelops accodamenti                           # Sync da Drive + riconciliazione cassa da TXT HotelCube → Excel su Desktop
hotelops accodamenti --no-sync --input <dir>   # Skip rclone sync, legge da cartella locale

# Lineage (Phase 1)
hotelops intake <file> --source-name X      # Register a file (RAW_INGESTED event)
hotelops promote --raw-object-id Y          # Promote PROMOTABLE → PROMOTED
hotelops lineage Y                          # Inspect raw_object identity + event history

# Reviews vertical
hotelops reviews                           # Ultime 30 reviews, media, negative
hotelops reviews --scrape                  # Scrape tutte le piattaforme
hotelops reviews --scrape --only booking   # Solo Booking
hotelops reviews --scrape --dry-run        # Preview senza scraping
hotelops reviews --stats                   # Stats mese corrente per piattaforma
hotelops reviews --stats --mese 3          # Stats mese specifico
hotelops reviews --alert                   # Mostra review che hanno generato alert
hotelops reviews --report                  # Invia report settimanale manualmente
streamlit run reviews/app.py               # Dashboard reviews

# Condges vertical
streamlit run condges/app_cdg.py               # Controllo di Gestione (CE, Budget, Tesoreria, Indicatori)
python -m condges.genera_excel --output ~/Desktop/PF.xlsx
python -m condges.update_previsione --voce utenze --societa ORTI --mesi 4-12 --importo 22000

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
| `f_consumi_economato` | Consumi materie prime per reparto/prodotto (APPEND) |
| `f_coperti_giornalieri` | Coperti pasto giornalieri per BU/tipo_ospite (APPEND) |
| `f_chiusura_mensile` | Snapshot chiusura mese: previsione vs consuntivo per voce + saldo banca (SNAPSHOT) |
| `f_saldi_banca_snapshot` | Registro contabile banca da Esolver, end-of-day running balance (APPEND) |
| `f_partite_aperte_fornitori` | Snapshot partite aperte fornitori (IMPEGNO dimension) (SNAPSHOT) |
| `f_mastrino_consolidato` | Mastrino consolidato da "Costi Ricavi 2025-2026 Budget.xlsx" (APPEND) |
| `f_ricavi_storici` | Riepilogo Entrate mensili 2023-2025 per BU (APPEND) |
| `f_coefficienti_consumo` | Coefficienti consumo per reparto/prodotto (APPEND) |
| `f_pms_statistiche` | Statistiche PMS HotelCube (APPEND) |
| `f_mastrino_consolidato` | Mastrino consolidato da "Costi Ricavi 2025-2026 Budget.xlsx" (APPEND) |
| `f_affidamenti` | Affidamenti bancari (linee di credito) -- schema TBD |
| `f_reviews` | Guest reviews da OTA (Booking, TripAdvisor, Google, Expedia). NLP classified. (APPEND) |
| `f_vendite_fb` | Vendite F&B POS (giorno × sala × articolo) da Ristocube. Include `segmento_cliente`. (APPEND, dedup hash_riga) |

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
