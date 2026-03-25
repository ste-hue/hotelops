# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Last checkpoint:** 2026-03-23 | **Version:** 0.4.0

## Project Overview

hotelops is the financial data platform for Gruppo Panorama hotel operations. It ingests data from banks, ERP (Esolver), PMS (HotelCube), and manual budgets into BigQuery, then serves the **condges** (Controllo di Gestione) vertical through two complementary lenses:

1. **Rosa (lente CASSA)** — Piano Finanziario: flussi di cassa mensili previsionali (entrate/uscite di cassa). Domanda: "quando il soldo entra/esce?"
2. **Gasparotto (lente COMPETENZA)** — Budget vs Consuntivo: CE per codice conto, break-even, KPI operativi. Domanda: "quanto consumo/genero?"

Rosa e Gasparotto sono due facce della stessa medaglia — stesso verticale `condges/`, stesso dataset, stesse fact tables. Cambia la vista e la domanda.

**Architecture:** Three layers — `core/` (world model), `ingest/` (reality capture), `condges/` (decision verticals). BigQuery is the source of truth.

```
core/       ← schemas, config, BQ views, dimensions — the ontology
ingest/     ← pipelines: Drive/Excel/CSV → BigQuery fact tables
condges/    ← Vertical #1: Controllo di Gestione (Streamlit app, Excel gen, previsioni)
cli.py      ← terminal interface (imports from core + condges)
```

Raw data lives in the Datahub (Google Drive: `hotelops_datahub/`). Analytics live in BigQuery. Verticals are containerizable.

### Datahub Structure (Google Drive)

```
hotelops_datahub/
├── homebanking/{ORTI,INTUR}/           ← Estratti conto da portale banca (MPS, Sella, Intesa XLS/XLSX)
├── movimenti_contabili/{ORTI,INTUR}/   ← Esolver prima nota (LISTAMOVCONT.XLS)
├── registro_banca_esolver/{ORTI,INTUR}/ ← Esolver scheda contabile (registro del conto banca) — CSV or XLSX
├── partite_fornitori/{ORTI,INTUR}/     ← Esolver situazione partite fornitori (snapshot periodici)
├── piani_finanziari/{ORTI,INTUR}/      ← Piano Finanziario Excel (Rosa, mensili)
├── accodamenti/ORTI/                   ← HotelCube PMS TXT files (corrispettivi, fatture, movimenti)
├── economato/                          ← Consumi materie prime per reparto (sottocartelle per reparto)
├── coperti/                            ← Coperti giornalieri
├── bilancino/{ORTI,INTUR}/             ← Bilancio di verifica Esolver
├── gasparotto/                         ← Master Completo budget (aggiornamenti periodici)
├── dimensioni/                         ← Dimension CSV sources
├── fatti/                              ← Local fact CSV copies (pipeline output)
└── meta/                               ← Pipeline manifests and logs
```

File naming convention for Esolver exports: `{SOCIETA}_{TIPO}_{BANCA}_{YYYYMMDD}.{ext}`
Esolver CSV auto-naming: `{DATE}_Conto_{SOCIETA}_{Banca}{NOME}_Cc{N}_Saldo{AMOUNT}_Esercizio{YEAR}.csv`

### The Three Temporal Dimensions

Every financial event has three timestamps — understanding which dimension you're looking at is the key concept:

| Dimension | Question | Who | Source | Status |
|-----------|----------|-----|--------|--------|
| **COMPETENZA** | Quando consumo/genero? | Gasparotto | f_movimenti_contabili → v_budget_vs_consuntivo | ✅ |
| **CASSA** | Quando il soldo entra/esce? | Rosa | f_banche_movimenti + f_piano_finanziario_input → v_piano_finanziario_mensile | ✅ |
| **IMPEGNO** | Quando devo pagare/incassare? | Entrambi | f_partite_aperte_fornitori → v_previsione_cassa | ✅ (ORTI live, INTUR pending) |

Example: fattura fornitore marzo (competenza=marzo), consumo aprile, pagamento giugno (cassa=giugno). Tutte e tre le dimensioni sono ora coperte per ORTI: f_partite_aperte_fornitori carica snapshot Esolver "Situazione Partite Fornitori" e v_previsione_cassa usa i dati di scadenza per proiettare il cash forward.

## GCP

- **Project:** `hotelops-suite`
- **Dataset:** `hotelops`
- **Auth:** `gcloud` authenticated as `stefano@panoramagroup.it`

## Commands

```bash
# Install (registers `hotelops` CLI command)
pip install -e ".[dev]"

# ═══════════════════════════════════════════════════════════
# CLI — primary interface for financial model
# ═══════════════════════════════════════════════════════════

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
hotelops previsione utenze 4-12 22000      # Update forecast: utenze ORTI Apr-Dec €22K/mo
hotelops previsione "entrate hotel" aprile-ottobre 180000  # Natural language months
hotelops classifica file1.xlsx file2.csv       # Classify files (show type + destination)
hotelops classifica *.xlsx --route             # Classify + copy to correct datahub folder + rename
hotelops classifica *.xlsx --route --ingest    # Classify + route + run BQ pipeline
hotelops classifica *.xlsx --dry-run           # Show plan without executing

# ═══════════════════════════════════════════════════════════
# CONDGES — Controllo di Gestione vertical
# ═══════════════════════════════════════════════════════════

streamlit run condges/app.py                                        # Interactive PF app for Rosa
python -m condges.genera_excel                                      # → Piano_Finanziario_2026_YYYY-MM-DD.xlsx
python -m condges.genera_excel --output ~/Desktop/PF.xlsx
python -m condges.update_previsione --voce utenze --societa ORTI --mesi 4-12 --importo 22000
python -m condges.reconcile_banca --datahub /path/to/datahub --societa INTUR --conto SELLA --from 2025-01-01 --to 2025-01-31

# ═══════════════════════════════════════════════════════════
# INGEST — Reality Capture (pipelines)
# ═══════════════════════════════════════════════════════════

python -m ingest.orchestrate                           # Run everything (sync + ingest all)
python -m ingest.orchestrate --dry-run                 # Parse + CSV, no BQ writes
python -m ingest.orchestrate --no-sync                 # Skip Drive sync
python -m ingest.orchestrate --only banca              # Only bank group
python -m ingest.orchestrate --only amministrativa     # Only accounting group
python -m ingest.orchestrate --only dimensioni         # Only dimension tables
python -m ingest.orchestrate --pipeline gasparotto     # Single pipeline

# Individual pipelines (manual/debug)
python -m ingest.banca.ingest --datahub /path/to/datahub --source ~/.cache/hotelops/tesoreria_staging
python -m ingest.banca.ingest_accodamenti --datahub /path/to/datahub --staging ~/.cache/hotelops/accodamenti_staging
python -m ingest.amministrativa.ingest_movimenti_contabili --datahub /path/to/datahub
python -m ingest.amministrativa.ingest_gasparotto --file "Master Completo....xlsx" --societa ORTI
python -m ingest.amministrativa.ingest_partite_aperte --file situazione_partite.xlsx

# Test / lint
pytest
ruff check .
ruff format .
```

## BigQuery Tables

### Fact tables

Two lifecycle types: **APPEND** (each file adds rows, MD5 dedup — file accumula nel tempo) vs **SNAPSHOT** (latest file replaces previous data in BQ via DELETE-INSERT — "situazione ad oggi").

| Table | Description | Lifecycle | Idempotency |
|-------|-------------|-----------|-------------|
| `f_banche_movimenti` | Bank transactions — MPS, MPS_KROSS, SELLA, INTESA, BCP × ORTI/INTUR | APPEND | MD5 dedup |
| `f_movimenti_contabili` | Prima nota completa Esolver. ORTI 2025→, INTUR dic2024→. CodConto senza punti (570913). | APPEND | MD5 dedup |
| `f_budget_mensile` | Budget mensile per codice conto. Fonti: GASPAROTTO, MAPPATURA (per BU), INCIDENZA (personale). | SNAPSHOT | DELETE-INSERT per anno+fonte |
| `f_piano_finanziario_input` | Cash flow previsioni: 28 voci × 12 mesi. Fonti: PIANO_FINANZIARIO (from XLSX), SCADENZIARIO (loan schedules), BVA_2026 (revenue budgets), CLI/NANOCLAW (manual updates), APP (Streamlit). | SNAPSHOT | MD5 dedup / DELETE-INSERT per fonte |
| `f_accodamenti` | Vendite da HotelCube PMS → Esolver: corrispettivi, caparre, fatture attive. | APPEND | MD5 dedup |
| `f_bilancino` | Bilancio di verifica Esolver (export manuale). Solo leaf nodes. | SNAPSHOT | MD5 dedup |
| `f_consumi_economato` | Consumi materie prime per reparto/prodotto. | APPEND | MD5 dedup |
| `f_coperti_giornalieri` | Coperti pasto giornalieri per BU/tipo_ospite. | APPEND | MD5 dedup |
| `f_chiusura_mensile` | Snapshot chiusura mese: previsione vs consuntivo per voce + saldo banca. Scritto da `hotelops chiudi`. Serve per tracciare l'accuratezza delle previsioni nel tempo. | SNAPSHOT | DELETE-INSERT per societa+anno+mese |
| `f_saldi_banca_snapshot` | Registro contabile banca da Esolver (end-of-day running balance). Fonte: SCHEDA_CONTABILE (file_sorgente column). Datahub: `registro_banca_esolver/`. Usato da v_previsione_cassa come ancora per cash forward. Pipeline: `ingest_scheda_contabile.py` (CSV+XLSX, auto DD/MM swap fix, reverse Cc#→societa inference). | APPEND | DELETE-INSERT per societa+banca+data_snapshot+file_sorgente |
| `f_partite_aperte_fornitori` | Snapshot partite aperte fornitori da Esolver. TERZA DIMENSIONE (IMPEGNO): fatture registrate non ancora pagate, con data_scadenza. Flag intercompany per PANORAMA COMPANY. | SNAPSHOT | DELETE-INSERT per societa+data_snapshot |
| `f_mastrino_consolidato` | Mastrino consolidato da "Costi Ricavi 2025-2026 Budget.xlsx". 901 righe. | APPEND | MD5 dedup |
| `f_ricavi_storici` | Riepilogo Entrate mensili 2023-2025 per BU. Fonte: Antonio. | APPEND | MD5 dedup |
| `f_affidamenti` | Affidamenti bancari (linee di credito). Definito in config.py, schema TBD. | TBD | TBD |

### Dimension tables

| Table | Description | Update |
|-------|-------------|--------|
| `d_voci_piano_finanziario` | 28 voci PF mappate a codici conto Esolver via LIKE patterns. Source: `core/bq/dimensioni/d_voci_piano_finanziario.csv`. | WRITE_TRUNCATE |
| `d_piano_conti` | Piano dei conti 2026 — 160 conti con codice (dotted), tipo, sezione (CE/SP). | WRITE_TRUNCATE |
| `d_categorie_conti` | Mapping canonici: codice_conto → (tipo_costo, categoria_ce). 167 righe da "Costi Ricavi" sheet CATEGORIE. | WRITE_TRUNCATE |
| `d_fornitori` | Fornitori ORTI (65) con voce_id e flag intercompany. Source: `core/bq/dimensioni/d_fornitori.csv`. | WRITE_TRUNCATE |
| `d_budget_costi_fissi` | Costi fissi annuali per BU (43 righe). Source: MAPPATURA DEI COSTI_v_2.xlsx. | WRITE_TRUNCATE |
| `d_personale_mensile` | Costi personale mensili per divisione (78 righe). Source: Incidenza_costi_personale.xlsx. | WRITE_TRUNCATE |
| `d_coefficienti_stagionalita` | Monthly seasonality multipliers per BU, computed from f_ricavi_storici. Sum=12.0. | WRITE_TRUNCATE |
| `d_periodi_apertura` | Calendario stagionale apertura/chiusura per BU (3 righe). | WRITE_TRUNCATE |

### Views

| View | Description | Source SQL |
|------|-------------|-----------|
| `v_piano_finanziario_mensile` | **THE view for Rosa**: Budget vs consuntivo per voce PF, rolling 18 mesi. Columns: importo_consuntivo, importo_budget, scostamento, tipo_periodo (CONSUNTIVO/BUDGET). | `core/bq/views/v_piano_finanziario_mensile.sql` |
| `v_piano_finanziario_consuntivo` | Actuals per voce PF (from f_movimenti_contabili + f_banche_movimenti via d_voci LIKE patterns). | `core/bq/views/v_piano_finanziario_consuntivo.sql` |
| `v_budget_vs_consuntivo` | **THE view for Gasparotto**: Budget vs actuals per cod_conto×mese. Status flags. **Note: SQL file NOT in core/bq/views/ — view defined directly in BigQuery.** | BQ-only (no local SQL) |
| `v_pl_movimenti` | P&L: ricavi - costi per categoria CE. Categorie: RICAVO, COSTO_FISSO, COSTO_VAR, PERSONALE, EXTRA_EBITDA, ALTRO. | `core/bq/views/v_pl_movimenti.sql` |
| `v_cashflow_mensile` | Cashflow mensile aggregato da banca. Columns: entrate, uscite, netto, netto_cumulativo. | `core/bq/views/v_cashflow_mensile.sql` |
| `v_incassi_per_canale` | Entrate bancarie per canale (BONIFICO, CARTE, CONTANTI, ALTRO). | `core/bq/views/v_incassi_per_canale.sql` |
| `v_previsione_cassa` | **Cash forward rolling 12 mesi**: ancora da f_saldi_banca_snapshot + PF stime + scadenzario. stato_liquidita: OK/ATTENZIONE/PERICOLO. Usata da `hotelops saldo`. | `core/bq/views/v_previsione_cassa.sql` |

### How the views connect

```
f_movimenti_contabili ──┐
                        ├─ JOIN d_voci_piano_finanziario (LIKE patterns) ──→ v_piano_finanziario_consuntivo
f_banche_movimenti ─────┘                                                          │
                                                                                    ├──→ v_piano_finanziario_mensile
f_budget_mensile ────── JOIN d_voci_piano_finanziario (LIKE patterns) ──────────────┤     (scaffold × consuntivo × budget × input)
                                                                                    │
f_piano_finanziario_input ── direct voce_id FK ────────────────────────────────────┘

f_movimenti_contabili ── JOIN d_categorie_conti ──→ v_budget_vs_consuntivo (BQ-only)
f_budget_mensile ─────── FULL OUTER JOIN ──────────┘

f_saldi_banca_snapshot ──┐
v_piano_finanziario_mensile ──┤──→ v_previsione_cassa (cash forward 12m)
f_partite_aperte_fornitori ──┘

v_piano_finanziario_mensile ──→ `hotelops chiudi` ──→ f_chiusura_mensile (snapshot delta)
f_banche_movimenti ───────────┘                        (traccia accuratezza previsioni)
```

## Architecture

### Code structure

**core/** — The world model (nothing here imports from verticals)
- `core/schemas.py` — Pydantic models + `validate_batch()`. Every BQ write goes through here.
- `core/config.py` — Table IDs e costanti BQ (PROJECT, DATASET). All table refs as `F_*`, `D_*`, `V_*`.
- `core/contracts.py` — `SchemaViolationError`, `validate_columns()`.
- `core/datahub.py` — Minimal CSV reader for local fact tables.
- `core/bq/views/` — BigQuery view SQL definitions (source of truth). 6 SQL files (v_budget_vs_consuntivo is BQ-only).
- `core/bq/dimensioni/` — Dimension CSV sources (d_voci_piano_finanziario.csv, d_fornitori.csv).
- `core/bq/SCHEMA_CONTEXT.md` — Comprehensive BQ schema documentation (483 lines).
- `core/bq/hotelops-data-analyst/` — NanoClaw data analyst skill with reference docs per table family.

**ingest/** — Reality Capture (Drive/Excel/CSV → BigQuery)
- `ingest/classify.py` — **File classifier + router**: content-based detection of 10 file types (banca, scheda_contabile, movimenti_contabili, partite_fornitori, bilancino, gasparotto, piano_finanziario, accodamenti, coperti, economato). Infers societa+banca from content and filename. Renames to canonical convention, routes to correct datahub folder, triggers ingest pipeline. Used by `hotelops classifica` CLI and NanoClaw agent.
- `ingest/orchestrate.py` — Unified pipeline runner. Sync → classify → ingest → manifest. Groups: banca, amministrativa, dimensioni. All paths point to datahub root (no more `ingresso/` prefix).
- `ingest/banca/` — Bank and PMS pipelines:
  - `fetch_drive.py` — Sync `homebanking/` from Drive via rclone.
  - `ingest.py` — Parse XLS/XLSX (MPS, Sella, Intesa) → f_banche_movimenti.
  - `ingest_accodamenti.py` — HotelCube PMS → f_accodamenti.
  - `parser_accodamenti.py` — Esolver TXT pipe-delimited parser (ported from reconciliation_dino, no external deps).
  - `ingest_mastrino.py` — Bank mastrino parsing.
- `ingest/amministrativa/` — Accounting, budget, consumption pipelines:
  - `ingest_scheda_contabile.py` — **NEW**: Esolver scheda contabile (CSV semicolon + XLSX) → f_saldi_banca_snapshot. Auto DD/MM swap fix for XLSX. Infers societa+banca from filename (Cc# or bank name). Supports all 7 bank accounts: MPS, MPS_KROSS, INTESA × ORTI + MPS, SELLA, INTESA, BCP × INTUR.
  - `ingest_movimenti_contabili.py` — Esolver prima nota → f_movimenti_contabili.
  - `ingest_gasparotto.py` — Gasparotto Master Budget → f_budget_mensile. MANUAL_COD_MAP for PDC 2026 (20 remapped codes).
  - `ingest_piano_finanziario_xlsx.py` — PF XLSX → f_piano_finanziario_input.
  - `ingest_partite_aperte.py` — Situazione Partite Fornitori (3rd dimension: IMPEGNO).
  - `ingest_bilancino.py` — Bilancio di verifica → f_bilancino.
  - `ingest_voci_piano_finanziario.py` — Loads d_voci dimension from CSV.
  - `ingest_piano_conti_nuovo.py` — Piano dei conti 2026 → d_piano_conti.
  - `ingest_categorie.py` — Categorie conti → d_categorie_conti.
  - `ingest_fornitori.py` — Fornitori → d_fornitori.
  - `ingest_coefficienti_stagionalita.py` — Computes monthly seasonality multipliers from f_ricavi_storici → d_coefficienti_stagionalita.
  - `ingest_ricavi_storici.py` — Riepilogo Entrate XLSX (2023-2025 monthly revenue from Antonio) → f_ricavi_storici.
  - `ingest_piano_finanziario_input.py` — PF input rows from various sources → f_piano_finanziario_input.
  - `ingest_ricevute.py` — Ricevute fiscali processing.
  - `ingest_consumi_economato.py`, `ingest_consumi_economato_consolidato.py`, `ingest_consumi_merce.py` — Consumption tracking pipelines.
  - `ingest_coperti.py` — Coperti giornalieri → f_coperti_giornalieri.
  - `ingest_mastrino.py` — Mastrino contabile.
  - `ingest_budget_costi.py` — Budget costi fissi.

**condges/** — Vertical #1: Controllo di Gestione (containerizable)
- `condges/app.py` — Streamlit interactive Piano Finanziario for Rosa. Saldo anchor, editable grid, cash flow semaphore, scadenzario drill-down, Excel export.
- `condges/genera_excel.py` — Generate PF Excel from BQ. Color-coded: nero=consuntivo, blu=previsione, verde=formula.
- `condges/update_previsione.py` — Write forecasts to f_piano_finanziario_input (DELETE-INSERT). Natural language voce aliases + Italian month names.
- `condges/reconcile_banca.py` — Bank vs ledger reconciliation (partial — depends on `bank-reconcile` optional dep).
- `condges/materialize_reconciliation.py` — Materialized reconciliation view (partial/stub).
- `condges/Dockerfile` — Containerization for Streamlit app.

**Root**
- `cli.py` — **CLI entry point** (`hotelops` command). Imports from core + condges + ingest. 8 subcommands: pf, bva, chiudi, saldo, health, previsione, voci, classifica.
- `core/registry.yaml` — **Pipeline registry**: single source of truth for file types, dest folders, BQ tables, signatures. classify.py and orchestrate.py reference this.
- `BRIEF_APP_PIANO_FINANZIARIO.md` — Streamlit app specification document (31KB).
- `CHANGELOG.md` — Recent changes log.
- `meta/reference/` — PDC 2025 vs 2026 reference files + INTUR/ORTI relationship docs.
- `meta/skills/hotelops-data-analyst/` — NanoClaw data analyst skill (duplicate of core/bq/ version).

### Data model

Every fact row carries **5 dimensions**: `societa_id`, `business_unit_id`, `funzione_id`, `location_id`, `oggetto_id`.

**Account code formats:** d_piano_conti uses dots (57.09.13), f_movimenti_contabili uses no dots (570913). Join with `REPLACE(codice_conto, '.', '')`.

**Sign conventions:**
- Views: ENTRATE positive = entrata, USCITE positive = uscita
- Esolver: ENTRATE = imp_avere - imp_dare, USCITE = imp_dare - imp_avere
- Banche: importo_netto positive = entrata, negative = uscita

### d_voci_piano_finanziario — the mapping layer

28 voci that map the Piano Finanziario structure to Esolver account codes:
- 11 ENTRATE (Hotel, Residence, CVM, Supermercato, Spiaggia, Affitti, Caparre, etc.)
- 17 USCITE (Salari, Utenze, Materie Prime, Tasse, Mutui, Commissioni, Consulenze, Marketing, Servizi Produzione, Canone Passivo, etc.)
- fonte=ESOLVER: joins via cod_conto_pattern LIKE
- fonte=BANCHE: joins via banca_tipo_pat LIKE on tipo_movimento
- fonte=MANUALE: only via f_piano_finanziario_input.voce_id FK

Source CSV: `core/bq/dimensioni/d_voci_piano_finanziario.csv`. Loaded by: `ingest_voci_piano_finanziario.py`.

### Budget sources

| Fonte | Scope | Granularity | Where |
|-------|-------|-------------|-------|
| GASPAROTTO | Full CE | Company-level, 1/12 monthly | f_budget_mensile |
| MAPPATURA | Fixed/variable costs | Per BU (HOTEL, RESIDENCE, CVM, LIDO) | f_budget_mensile |
| INCIDENZA | Payroll costs | Per divisione | f_budget_mensile |
| PIANO_FINANZIARIO | Cash flow (28 voci) | ORTI+INTUR monthly | f_piano_finanziario_input |
| SCADENZIARIO | Loan schedules | Per voce × mese | f_piano_finanziario_input |
| BVA_2026 | Revenue budgets | Per voce × mese | f_piano_finanziario_input |
| CLI/NANOCLAW | Manual forecast updates | Per voce × mese | f_piano_finanziario_input |
| APP | Streamlit app saves | Per voce × mese | f_piano_finanziario_input |

### PDC 2026 restructuring

The 2026 chart of accounts restructured significantly from 2025:
- All 61.xx administrative costs → 63.05.xx and 65.90.xx
- 25 new codes added (Commissioni OTA per BU, Marketing, Personale occasionale, etc.)
- 9 codes renamed
- MANUAL_COD_MAP in ingest_gasparotto.py has 20 remapped codes
- Reference files in `meta/reference/`: PDC Orti Srl Revision.xlsx (2025), Piano dei Conti Update.XLSX (2026)

## Key file locations (Stefano's Mac)

| What | Path |
|------|------|
| Gasparotto Master | `~/Desktop/WORK/artifacts/gasparotto_materialiereport/Master Completo Indici 2025 ORTI SRL_Budget26_AGG 17.03.xlsx` |
| Costi Ricavi Budget | `~/Desktop/WORK/artifacts/Costi Ricavi 2025-2026 Budget.xlsx` |
| Piano Finanziario XLSX | `~/Desktop/WORK/pianifinanziari/` (11 files ORTI+INTUR, aggiornati mar 2026) |
| Mappatura Costi | `~/work/artifacts/MAPPATURA DEI COSTI_v_2.xlsx` |
| Incidenza Personale | `~/work/artifacts/Incidenza_costi_personale.xlsx` |
| hotelops repo | `~/dev/Projects/hotelops` |
| NanoClaw repo | `~/education/repos/AI_repos/nanoclaw` |

## Stakeholders and their needs (from meeting 17.03.2026)

Rosa e Gasparotto sono le due facce del verticale `condges/` — stesso dataset, stesse fact tables, lenti diverse.

### Rosa (lente CASSA — Tesoreria)
- Uses: `hotelops pf`, `hotelops saldo`, `condges/genera_excel.py`, `condges/app.py` (Streamlit)
- Needs: monthly cash flow forecast (entrate/uscite di cassa)
- Her process: checks open payables in Esolver, estimates revenues from prior year, asks commercialista for taxes
- Goal: prevent liquidity crises in critical months

### Gasparotto/Roberto (lente COMPETENZA — Consulente Controllo di Gestione)
- Uses: `hotelops bva`
- Needs: CE budget vs consuntivo per codice conto, break-even analysis
- Goal: shift from backward-looking budget (copy 2025) to strategic zero-based budgeting
- Wants: seasonality-adjusted budget (not flat 1/12 — ✅ implemented), operational KPIs (cost per room, per cover)

### Key decisions from 17.03.2026 meeting
- Operational year is Nov-Oct (not calendar year) due to hotel seasonality
- 2026 is the transition year to real governance — "bussola decisionale"
- Antonio sending 2023-2025 monthly revenue data for seasonality analysis — ✅ received and integrated (d_coefficienti_stagionalita applied to Gasparotto + MAPPATURA budgets)
- Next meeting: April 17, 2026

## Monthly Routine (la routine mensile)

### Giorno 1-5: Aggiorna i dati
```bash
python -m ingest.orchestrate                 # Sync Drive + ingest banche, movimenti, tutto
hotelops health                              # Verifica freshness: banche aggiornate? movimenti recenti?
```

### Giorno 5: Chiudi il mese precedente
```bash
hotelops chiudi                           # Confronta previsione vs consuntivo, mostra saldo banca
                                          # Salva snapshot in f_chiusura_mensile (delta storicizzato)
hotelops chiudi --societa INTUR           # Idem per INTUR
```
Cosa guardi: ogni voce dove il delta è grande → indaghi. Perché le utenze sono costate €28K e non €22K? Aggiusti la previsione dei mesi futuri.

### Sessione con Rosa (tesoreria, ~mensile)
```bash
python -m condges.genera_excel --output ~/Desktop/PF_2026.xlsx  # Excel con saldo banca reale
# oppure:
streamlit run condges/app.py                                     # Interactive version
```
Voce per voce: lei guarda partite aperte in Esolver, tu aggiorni:
```bash
hotelops previsione "materie prime" aprile 80000
hotelops previsione utenze 4-12 28000     # Rivedi al rialzo dopo consuntivo
hotelops saldo                            # Proiezione cash forward: affoghiamo?
```

### Sessione con Gasparotto (controllo gestione, ~trimestrale)
```bash
hotelops bva                              # Top 30 scostamenti budget vs consuntivo per codice conto
hotelops bva --mese 3                     # Singolo mese
```

### Ciclo continuo
Ogni mese il modello si affina: le previsioni si aggiustano, gli snapshot tracciano se migliori. Il saldo banca reale + proiezione ti dice sempre se e quando rischi di andare in negativo.

## NanoClaw Agent Integration

NanoClaw (WhatsApp agent) is the query + alerting runtime. Read-only + pipeline control (no writes).
System prompt lives in the NanoClaw repo: `~/education/repos/AI_repos/nanoclaw/groups/hotelops/CLAUDE.md`.

### Pipeline triggers

| Trigger | Command |
|---------|---------|
| "Aggiorna banche" | `python -m ingest.orchestrate --only banca` |
| "Aggiorna tutto" | `python -m ingest.orchestrate` |
| "Caricato il Gasparotto" | `python -m ingest.orchestrate --pipeline gasparotto` |
| "Piano finanziario?" | Query `v_piano_finanziario_mensile` |
| "Budget vs consuntivo?" | Query `v_budget_vs_consuntivo` |
| "Ho un file da caricare" / file attachment | `hotelops classifica <file> --route --ingest` |
| "Classifica questo file" | `python -m ingest.classify <file>` |

## Governance Rules

- Every pipeline reads from its dedicated datahub folder (see Datahub Structure) and writes to BigQuery.
- Every fact row must carry all 5 dimensions.
- No speculative modules — pipelines are born from real data flows.
- Never modify `fatti/` manually — pipelines only.
- All budget data carries a `fonte` tag — never mix fonti without explicit filter.
- d_voci_piano_finanziario is the single mapping layer between PF voci and Esolver codici conto.

## Entities

### Società (legal entities) — vasi comunicanti

- **INTUR** — proprietà e aspetti finanziari (mutui, IVA, fatture). Possiede Hotel+Spiaggia+Immobili. Gestisce direttamente solo il **Lido** (spiaggia). Per tutto il resto è holding finanziaria. Riceve fitto ramo d'azienda da ORTI (€732K/anno, 6 rate da €122K).
- **ORTI** — gestione operativa: vendite, acquisti, costi di Hotel, Residence, CVM. Paga fitto a INTUR (conto 6511). È anche socio di INTUR (€3M aumento capitale). Tutti i movimenti gestionali sono ORTI tranne Lido.

**Relazione critica**: Se ORTI non genera cash → non paga fitto → INTUR non paga mutui → rischio default. Il fitto ORTI→INTUR (USCITE_CANONE_PASSIVO / ENTRATE_AFFITTI_INTUR) è intercompany e si cancella nel consolidato. Dettagli completi: `meta/reference/INTUR_ORTI_relationship.md`.

### Business Units
| business_unit_id | Nome canonico | Note |
|---|---|---|
| `HOTEL` | Hotel Panorama | Hotel 4* a Maiori, stagionale apr-ott |
| `RESIDENCE` | Angelina Residence | Appartamenti, tutto l'anno |
| `CVM` | Casa Vacanze Maiori | Appartamenti vacanza, tutto l'anno |
| `LIDO` | Lido / Spiaggia | Concessione balneare, INTUR |
| `HQ` | Sede / Amministrazione | Funzioni centrali |

### Banks
- **MPS** — Monte dei Paschi di Siena (conto principale)
- **MPS_KROSS** — MPS conto Kross (separato)
- **SELLA** — Banca Sella
- **INTESA** — Intesa Sanpaolo
- **BCP** — Banca di Credito Popolare (INTUR only, Torre del Greco)

#### Esolver bank account mapping (Cc# → banca_id)

| Società | Cc# | banca_id | Banca |
|---------|-----|----------|-------|
| ORTI | Cc1 | INTESA | Intesa Sanpaolo |
| ORTI | Cc2 | MPS_KROSS | MPS Kross |
| ORTI | Cc3 | MPS | Monte dei Paschi |
| INTUR | Cc1 | SELLA | Banca Sella |
| INTUR | Cc2 | MPS | Monte dei Paschi |
| INTUR | Cc3 | INTESA | Intesa Sanpaolo |
| INTUR | Cc4 | BCP | Banca di Credito Popolare |

## Deploy — NanoClaw Agent

L'agente WhatsApp gira in un container NanoClaw. La configurazione è in `deploy/`.

```
deploy/
├── nanoclaw_group_config.yaml   ← mounts, secrets, env, capabilities (reference)
├── architecture.mermaid         ← diagramma architetturale (render su mermaid.live)
└── DEPLOY.md                    ← procedura step-by-step
```

### Mounts del container

| # | Host | Container | Mode | Cosa |
|---|------|-----------|------|------|
| 1 | `~/dev/Projects/hotelops` | `/workspace/extra/hotelops-repo` | ro | Codice pipeline + CLI |
| 2 | `~/dev/projects/obsidian/Obsidian Vault/hotelops` | `/workspace/extra/obsidian-hotelops` | rw | Knowledge base (ontologia, procedure) |
| 3 | `~/Library/CloudStorage/GoogleDrive-.../hotelops_datahub` | `/workspace/extra/datahub` | rw | Dati grezzi (Google Drive) |
| 4 | *(Baileys-managed)* | `/workspace/group/uploads` | ro | File allegati WhatsApp |
| 5 | `~/.config/hotelops/hotelops-nanoclaw-key.json` | `/workspace/extra/secrets/hotelops-nanoclaw-key.json` | ro | Service account BQ |

### Configurazione NanoClaw

NanoClaw non usa docker-compose. L'architettura è:
- **macOS launchd** (`launchd/com.nanoclaw.plist`) → processo Node.js principale
- **Container Docker** → spawned on-demand per ogni agente, gestito dal codice Node
- **Config runtime** → SQLite DB (`registered_groups` table con `container_config`)
- **Security** → `~/.config/nanoclaw/mount-allowlist.json` (lista path montabili)

File del gruppo (`~/education/repos/AI_repos/nanoclaw/groups/hotelops/`):
- `CLAUDE.md` — system prompt dell'agente (source of truth)
- `group_config.yaml` — configurazione mounts/env (reference)
- `.env` — environment variables
- `python-requirements.txt` — pacchetti Python per il container
- `hotelops.db` — SQLite locale del gruppo

### Aggiornare il prompt dell'agente

```bash
# Edita direttamente nel repo NanoClaw (è il source of truth per il prompt)
vim ~/education/repos/AI_repos/nanoclaw/groups/hotelops/CLAUDE.md

# Rebuild container + restart (auto al prossimo messaggio WhatsApp)
docker ps --filter name=nanoclaw-hotelops --format '{{.Names}}' | xargs -r docker kill
cd ~/education/repos/AI_repos/nanoclaw && docker builder prune -f && ./container/build.sh
```

### Flusso file WhatsApp → BQ

```
WhatsApp allegato → Baileys → /workspace/group/uploads/{ts}-{file}
  → python -m ingest.classify <file> --route --datahub /workspace/extra/datahub --ingest
  → classify (10 detectors) → route (rename → Drive) → ingest (parse → BQ)
```

## Known Issues / Tech Debt

- **v_budget_vs_consuntivo**: SQL definition not in `core/bq/views/` — exists only in BigQuery. Should be versioned locally.
- **f_affidamenti**: table ID defined in config.py but no Pydantic schema or ingest pipeline yet.
- **f_chiusura_mensile**: referenced in CLAUDE.md but table doesn't exist in BQ yet. Created by `hotelops chiudi` (not yet run).
- **Registry not wired**: `core/registry.yaml` defines file types/dest_folders but classify.py and orchestrate.py still hardcode paths. Next refactor: read from registry.

## Dependencies

Python ≥3.11, version 0.3.0.

Core: `pyyaml`, `openpyxl`, `pandas`, `google-cloud-bigquery`, `pydantic`.
Optional: `bank-reconcile` (`.[reconcile]`), `streamlit + plotly + db-dtypes` (`.[dashboard]`).
Dev: `pytest`, `ruff` (`.[dev]`).

## Tests

```
tests/
├── test_classify.py        — File classifier: 65 tests, all 10 detectors + routing + lifecycle
├── test_contracts.py       — Schema validation tests
└── test_materialize.py     — Materialization tests
```

Run: `pytest`. Lint: `ruff check .` / `ruff format .`
