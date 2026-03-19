# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

hotelops is the financial data platform for Gruppo Panorama hotel operations. It ingests data from banks, ERP (Esolver), PMS (HotelCube), and manual budgets into BigQuery, then provides views for two audiences:

1. **Rosa (Tesoreria)** — Piano Finanziario: flussi di cassa mensili previsionali (entrate/uscite di cassa)
2. **Gasparotto (Controllo di Gestione)** — Budget vs Consuntivo: CE per codice conto, break-even, KPI operativi

**Architecture:** File grezzi → 18 pipeline di ingestione → 8 fact tables + 5 dimension tables in BigQuery → 6 views analitiche → CLI `hotelops` + NanoClaw (WhatsApp).

Code lives here. Raw data lives in the Datahub (Google Drive). Analytics live in BigQuery.

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

# ═══════════════════════════════════════════════════════════
# GENERATE EXCEL for Rosa session
# ═══════════════════════════════════════════════════════════

python -m actions.genera_piano_finanziario                          # → Piano_Finanziario_2026_YYYY-MM-DD.xlsx
python -m actions.genera_piano_finanziario --output ~/Desktop/PF.xlsx

# ═══════════════════════════════════════════════════════════
# ORCHESTRATOR — unified pipeline runner
# ═══════════════════════════════════════════════════════════

python -m pipelines.orchestrate                        # Run everything (sync + ingest all)
python -m pipelines.orchestrate --dry-run              # Parse + CSV, no BQ writes
python -m pipelines.orchestrate --no-sync              # Skip Drive sync
python -m pipelines.orchestrate --only banca           # Only bank group
python -m pipelines.orchestrate --only amministrativa  # Only accounting group
python -m pipelines.orchestrate --only dimensioni      # Only dimension tables
python -m pipelines.orchestrate --pipeline gasparotto  # Single pipeline

# ═══════════════════════════════════════════════════════════
# INDIVIDUAL PIPELINES — manual/debug
# ═══════════════════════════════════════════════════════════

python -m pipelines.banca.ingest --datahub /path/to/datahub --source ~/.cache/hotelops/tesoreria_staging
python -m pipelines.banca.ingest_accodamenti --datahub /path/to/datahub --staging ~/.cache/hotelops/accodamenti_staging
python -m pipelines.amministrativa.ingest_movimenti_contabili --datahub /path/to/datahub
python -m pipelines.amministrativa.ingest_gasparotto --file "Master Completo....xlsx" --societa ORTI
python -m pipelines.amministrativa.ingest_piano_finanziario_xlsx --dir ~/work/pianifinanziari --latest-only
python -m pipelines.amministrativa.ingest_bilancino --file bilancino.xls --societa ORTI --mese 2026-01
python -m pipelines.amministrativa.ingest_consumi_economato --source /path/to/economato_ingresso --datahub /path/to/datahub
python -m pipelines.amministrativa.ingest_coperti --source /path/to/coperti_ingresso --datahub /path/to/datahub
python -m pipelines.amministrativa.ingest_piano_conti_nuovo --file "Costi Ricavi 2025-2026 Budget.xlsx"
python -m pipelines.amministrativa.ingest_categorie --file "Costi Ricavi 2025-2026 Budget.xlsx"
python -m pipelines.amministrativa.ingest_budget_costi --mappatura MAPPATURA.xlsx --incidenza Incidenza.xlsx
python -m pipelines.amministrativa.ingest_voci_piano_finanziario  # loads d_voci from CSV
python -m actions.update_previsione --voce utenze --societa ORTI --mesi 4-12 --importo 22000
python -m actions.reconcile_banca --datahub /path/to/datahub --societa INTUR --conto SELLA --from 2025-01-01 --to 2025-01-31

# Test / lint
pytest
ruff check .
ruff format .
```

## BigQuery Tables

### Fact tables

| Table | Description | Idempotency |
|-------|-------------|-------------|
| `f_banche_movimenti` | Bank transactions — MPS, MPS_KROSS, SELLA, INTESA × ORTI/INTUR | MD5 dedup |
| `f_movimenti_contabili` | Prima nota completa Esolver. ORTI 2025→, INTUR dic2024→. CodConto senza punti (570913). ~32K rows. | MD5 dedup |
| `f_budget_mensile` | Budget mensile per codice conto. Fonti: GASPAROTTO (112 conti, €4.08M ORTI), MAPPATURA (per BU), INCIDENZA (personale). | DELETE-INSERT per anno+fonte |
| `f_piano_finanziario_input` | Cash flow previsioni: 28 voci × 12 mesi. Fonti: PIANO_FINANZIARIO (from XLSX), CLI/NANOCLAW (manual updates). | MD5 dedup / DELETE-INSERT per fonte |
| `f_accodamenti` | Vendite da HotelCube PMS → Esolver: corrispettivi, caparre, fatture attive. | MD5 dedup |
| `f_bilancino` | Bilancio di verifica Esolver (export manuale). Solo leaf nodes. | MD5 dedup |
| `f_consumi_economato` | Consumi materie prime per reparto/prodotto. | MD5 dedup |
| `f_coperti_giornalieri` | Coperti pasto giornalieri per BU/tipo_ospite. | MD5 dedup |
| `f_chiusura_mensile` | Snapshot chiusura mese: previsione vs consuntivo per voce + saldo banca. Scritto da `hotelops chiudi`. Serve per tracciare l'accuratezza delle previsioni nel tempo. | DELETE-INSERT per societa+anno+mese |

### Dimension tables

| Table | Description | Rows | Update |
|-------|-------------|------|--------|
| `d_voci_piano_finanziario` | 28 voci PF mappate a codici conto Esolver via LIKE patterns. Source: `bq/dimensioni/d_voci_piano_finanziario.csv`. | 28 | WRITE_TRUNCATE |
| `d_piano_conti` | Piano dei conti 2026 — 160 conti CE con codice (dotted). | 160 | WRITE_TRUNCATE |
| `d_categorie_conti` | 167 mapping canonici: codice_conto → (tipo_costo, categoria_ce). | 167 | WRITE_TRUNCATE |
| `d_budget_costi_fissi` | Budget costi fissi INTUR+ORTI con split per BU. | 43 | Manual |
| `d_personale_mensile` | Costi personale mensili 2026 per Divisione. | 78 | Manual |

### Views

| View | Description | Source SQL |
|------|-------------|-----------|
| `v_piano_finanziario_mensile` | **THE view for Rosa**: Budget vs consuntivo per voce PF, rolling 18 mesi. Columns: importo_consuntivo, importo_budget, scostamento. | `bq/views/v_piano_finanziario_mensile.sql` |
| `v_piano_finanziario_consuntivo` | Actuals per voce PF (from f_movimenti_contabili + f_banche_movimenti via d_voci LIKE patterns). | `bq/views/v_piano_finanziario_consuntivo.sql` |
| `v_budget_vs_consuntivo` | **THE view for Gasparotto**: Budget vs actuals per cod_conto×mese. Status flags. | `bq/v_budget_vs_consuntivo.sql` |
| `v_pl_movimenti` | P&L: ricavi - costi per categoria CE. | `bq/views/v_pl_movimenti.sql` |
| `v_cashflow_mensile` | Cashflow mensile aggregato da banca. | `bq/views/v_cashflow_mensile.sql` |
| `v_incassi_per_canale` | Entrate bancarie per canale (POS, bonifico, contante). | `bq/views/v_incassi_per_canale.sql` |

### How the views connect

```
f_movimenti_contabili ──┐
                        ├─ JOIN d_voci_piano_finanziario (LIKE patterns) ──→ v_piano_finanziario_consuntivo
f_banche_movimenti ─────┘                                                          │
                                                                                    ├──→ v_piano_finanziario_mensile
f_budget_mensile ────── JOIN d_voci_piano_finanziario (LIKE patterns) ──────────────┤     (scaffold × consuntivo × budget × input)
                                                                                    │
f_piano_finanziario_input ── direct voce_id FK ────────────────────────────────────┘

f_movimenti_contabili ── JOIN d_categorie_conti ──→ v_budget_vs_consuntivo
f_budget_mensile ─────── FULL OUTER JOIN ──────────┘

v_piano_finanziario_mensile ──→ `hotelops chiudi` ──→ f_chiusura_mensile (snapshot delta)
f_banche_movimenti ───────────┘                        (traccia accuratezza previsioni)
```

## Architecture

### Code structure

- `cli.py` — **CLI entry point** (`hotelops` command). Subcommands: pf, bva, chiudi, saldo, health, previsione, voci.
- `pipelines/orchestrate.py` — Unified pipeline runner. Sync → classify → ingest → manifest.
- `pipelines/banca/` — Bank and PMS pipelines (fetch_drive, ingest, ingest_accodamenti)
- `pipelines/amministrativa/` — Accounting, budget, consumption (18 pipeline scripts)
  - `ingest_gasparotto.py` — Gasparotto Master Budget. MANUAL_COD_MAP aligned to PDC 2026 (20 codes remapped from old 61.xx → new 63.05.xx/65.90.xx).
  - `ingest_piano_finanziario_xlsx.py` — PF XLSX parser. Voce mapping aligned to d_voci_piano_finanziario.
  - `ingest_voci_piano_finanziario.py` — Loads d_voci dimension from CSV.
- `actions/update_previsione.py` — Write budget forecasts to f_piano_finanziario_input (DELETE-INSERT per voce×mese×fonte). Has natural language voce aliases.
- `actions/genera_piano_finanziario.py` — Generate PF Excel from BQ for Rosa session. Color-coded: nero=consuntivo, blu=previsione, verde=formula.
- `actions/reconcile_banca.py` — Bank vs ledger reconciliation.
- `tools/budget_wizard.py` — Interactive budget input with BQ historical data.
- `lib/schemas.py` — Pydantic models: BudgetMensileRow, PianoFinanziarioInputRow, etc.
- `bq/views/` — BigQuery view SQL definitions (6 views).
- `bq/dimensioni/` — Dimension CSV sources (d_voci_piano_finanziario.csv).
- `bq/SCHEMA_CONTEXT.md` — Comprehensive BQ schema documentation.
- `nanoclaw_hotelops_prompt.md` — System prompt for NanoClaw WhatsApp agent.
- `meta/reference/` — PDC 2025 vs 2026 reference files.

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
- 17 USCITE (Salari, Utenze, Materie Prime, Tasse, Mutui, Commissioni, Consulenze, Marketing, Servizi Produzione, etc.)
- fonte=ESOLVER: joins via cod_conto_pattern LIKE
- fonte=BANCHE: joins via banca_tipo_pat LIKE on tipo_movimento
- fonte=MANUALE: only via f_piano_finanziario_input.voce_id FK

Source CSV: `bq/dimensioni/d_voci_piano_finanziario.csv`. Loaded by: `ingest_voci_piano_finanziario.py`.

### Budget sources

| Fonte | Scope | Granularity | Where |
|-------|-------|-------------|-------|
| GASPAROTTO | Full CE (112 conti, €4.08M ORTI) | Company-level, 1/12 monthly | f_budget_mensile |
| MAPPATURA | Fixed/variable costs | Per BU (HOTEL, RESIDENCE, CVM, LIDO) | f_budget_mensile |
| INCIDENZA | Payroll costs | Per divisione | f_budget_mensile |
| PIANO_FINANZIARIO | Cash flow (28 voci, €5.7M entrate) | ORTI+INTUR monthly | f_piano_finanziario_input |
| CLI/NANOCLAW | Manual forecast updates | Per voce × mese | f_piano_finanziario_input |

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
| Piano Finanziario XLSX | `~/work/pianifinanziari/` (11 files ORTI+INTUR) |
| Mappatura Costi | `~/work/artifacts/MAPPATURA DEI COSTI_v_2.xlsx` |
| Incidenza Personale | `~/work/artifacts/Incidenza_costi_personale.xlsx` |
| hotelops repo | `~/dev/Projects/hotelops` |
| NanoClaw repo | `~/education/repos/AI_repos/nanoclaw` |

## Stakeholders and their needs (from meeting 17.03.2026)

### Rosa (Amministrazione — Tesoreria)
- Uses: `hotelops pf`, `genera_piano_finanziario.py`
- Needs: monthly cash flow forecast (entrate/uscite di cassa)
- Her process: checks open payables in Esolver, estimates revenues from prior year, asks commercialista for taxes
- Goal: prevent liquidity crises in critical months

### Gasparotto/Roberto (Consulente — Controllo di Gestione)
- Uses: `hotelops bva`
- Needs: CE budget vs consuntivo per codice conto, break-even analysis
- Goal: shift from backward-looking budget (copy 2025) to strategic zero-based budgeting
- Wants: seasonality-adjusted budget (not flat 1/12), operational KPIs (cost per room, per cover)

### Key decisions from 17.03.2026 meeting
- Operational year is Nov-Oct (not calendar year) due to hotel seasonality
- 2026 is the transition year to real governance — "bussola decisionale"
- Antonio sending 2023-2025 monthly revenue data for seasonality analysis
- Next meeting: April 17, 2026

## Monthly Routine (la routine mensile)

### Giorno 1-5: Aggiorna i dati
```bash
python -m pipelines.orchestrate           # Sync Drive + ingest banche, movimenti, tutto
hotelops health                           # Verifica freshness: banche aggiornate? movimenti recenti?
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
python -m actions.genera_piano_finanziario --output ~/Desktop/PF_2026.xlsx  # Excel con saldo banca reale
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

## Current status (as of 2026-03-20)

### Deployed to BQ
- All 6 views deployed and working
- f_budget_mensile: 1380 rows (GASPAROTTO) + 837 rows (MAPPATURA+INCIDENZA)
- f_piano_finanziario_input: 213 rows (PIANO_FINANZIARIO fonte)
- d_voci_piano_finanziario: 28 voci
- d_piano_conti: 160 CE accounts (needs reload if reset — source: Costi Ricavi file)
- d_categorie_conti: 167 mappings (needs reload if reset — source: Costi Ricavi file)

### Known data issues
- USCITE_SALARI gen/feb: consuntivo €5.5K vs budget €170K — salari possibly not yet booked in Esolver for those months
- USCITE_VARIE_EXT: budget negative (-€29K) — mapping issue in Gasparotto, needs investigation
- USCITE_SERVIZI_PRODUZIONE: consuntivo but zero budget — new voce 57.01.50 (€680K) not in Gasparotto Master
- Gasparotto budget uses flat 1/12 monthly split — needs seasonality adjustment
- PF XLSX data from September 2025 — stale, needs update with Rosa

### Pending work
- Fix data anomalies (salari, varie_ext budget negativo)
- Seasonality: load 2023-2025 revenue data when Antonio provides it
- Partite aperte fornitori: import from Esolver as new fact table for predictive outflows
- Operational KPIs (cost per room, per cover) — needs occupancy data
- NanoClaw deployment: mount BQ credentials in container

## NanoClaw Agent Integration

NanoClaw (WhatsApp agent) is the query + alerting runtime. Read-only + pipeline control (no writes).
System prompt: `nanoclaw_hotelops_prompt.md`.

### Pipeline triggers

| Trigger | Command |
|---------|---------|
| "Aggiorna banche" | `python -m pipelines.orchestrate --only banca` |
| "Aggiorna tutto" | `python -m pipelines.orchestrate` |
| "Caricato il Gasparotto" | `python -m pipelines.orchestrate --pipeline gasparotto` |
| "Piano finanziario?" | Query `v_piano_finanziario_mensile` |
| "Budget vs consuntivo?" | Query `v_budget_vs_consuntivo` |

## Governance Rules

- Every pipeline reads from `ingresso/` and appends to `fatti/` (and BigQuery).
- Every fact row must carry all 5 dimensions.
- No speculative modules — pipelines are born from real data flows.
- Never modify `fatti/` manually — pipelines only.
- All budget data carries a `fonte` tag — never mix fonti without explicit filter.
- d_voci_piano_finanziario is the single mapping layer between PF voci and Esolver codici conto.

## Entities

### Società (legal entities)

- **INTUR** — proprietà e aspetti finanziari (mutui, IVA, fatture, riconciliazione bancaria). Gestisce direttamente solo il **Lido** (spiaggia). Per tutto il resto è holding finanziaria.
- **ORTI** — gestione operativa: vendite, acquisti, costi di Hotel, Residence, CVM. Tutti i movimenti gestionali sono ORTI tranne Lido.

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

## Dependencies

Python ≥3.11. Core: `pyyaml`, `openpyxl`, `bank-reconcile`, `pandas`, `google-cloud-bigquery`, `esolver-accodamenti`, `pydantic`. Dev: `pytest`, `ruff`.
