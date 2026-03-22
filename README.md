# hotelops

Financial data platform for Gruppo Panorama hotel operations. Ingests data from banks (MPS, Sella, Intesa), ERP (Esolver), PMS (HotelCube), and manual budgets into BigQuery, then provides CLI tools and Excel reports for treasury management and budget control.

Two legal entities: **ORTI** (hotel operations) and **INTUR** (asset holding). Two audiences: **Rosa** (tesoreria — cash flow forecasts) and **Gasparotto** (controllo gestione — budget vs actuals).

## Quick Start

```bash
pip install -e ".[dev]"
hotelops health        # Check data freshness
hotelops pf            # Piano Finanziario ORTI
hotelops saldo         # Bank balance + 12-month cash projection
```

## Architecture

```
Google Drive (datahub)          BigQuery (hotelops-suite)              CLI / Excel
───────────────────       ──────────────────────────────       ──────────────────
  Bank exports     ─┐     8 fact tables                        hotelops pf
  Esolver exports   ├──→  5 dimension tables           ──→     hotelops bva
  Budget files      │     6 analytical views                   hotelops saldo
  PF XLSX          ─┘     1 snapshot table                     hotelops chiudi
                                                               genera_piano_finanziario.py
                    18 ingest pipelines
                    1 orchestrator
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `hotelops pf` | Piano Finanziario: budget vs consuntivo per voce, per mese |
| `hotelops bva` | Budget vs Consuntivo: per codice conto, top N by delta |
| `hotelops chiudi` | Monthly close: forecast vs actual + bank balance + save snapshot |
| `hotelops saldo` | Bank balance (real, from snapshots) + forward cash projection |
| `hotelops health` | Health check: data freshness, gaps, alerts |
| `hotelops previsione` | Write/update budget forecasts to BigQuery |
| `hotelops voci` | List all 28 Piano Finanziario voci and their mappings |

## Monthly Routine

**Days 1-5: Update data**
```bash
python -m pipelines.orchestrate     # Sync Drive + ingest everything
hotelops health                     # Verify freshness
```

**Day 5: Close previous month**
```bash
hotelops chiudi                     # Compare forecast vs actual, save snapshot
hotelops chiudi --societa INTUR     # Same for INTUR
```

**Session with Rosa (treasury)**
```bash
python -m actions.genera_piano_finanziario --output ~/Desktop/PF_2026.xlsx
hotelops previsione utenze 4-12 28000        # Update forecast after review
hotelops saldo                                # Will we drown?
```

**Session with Gasparotto (budget control)**
```bash
hotelops bva                        # Top 30 variances by account code
hotelops bva --mese 3               # Single month
```

## BigQuery Tables

**Fact tables:** f_banche_movimenti, f_movimenti_contabili, f_budget_mensile, f_piano_finanziario_input, f_accodamenti, f_bilancino, f_consumi_economato, f_coperti_giornalieri, f_chiusura_mensile, f_saldi_banca_snapshot

**Dimension tables:** d_voci_piano_finanziario (28 voci), d_piano_conti (160 accounts), d_categorie_conti (167 mappings), d_budget_costi_fissi, d_personale_mensile

**Views:** v_piano_finanziario_mensile, v_piano_finanziario_consuntivo, v_budget_vs_consuntivo, v_cashflow_mensile, v_pl_movimenti, v_incassi_per_canale

## Project Structure

```
cli.py                          CLI entry point (hotelops command)
pipelines/
  orchestrate.py                Unified pipeline runner
  banca/                        Bank + PMS pipelines
  amministrativa/               Accounting, budget, consumption (18 scripts)
actions/
  genera_piano_finanziario.py   Excel generator for Rosa
  update_previsione.py          Write forecasts to BQ
  reconcile_banca.py            Bank vs ledger reconciliation
lib/
  schemas.py                    Pydantic models for all fact tables
bq/
  views/                        BigQuery view SQL (6 views)
  dimensioni/                   Dimension CSV sources
  v_budget_vs_consuntivo.sql    BVA view definition
meta/
  reference/                    PDC files, INTUR-ORTI relationship map
```

## Requirements

Python ≥ 3.11. GCP authentication: `gcloud auth application-default login` as `stefano@panoramagroup.it`. BigQuery project: `hotelops-suite`, dataset: `hotelops`.

See [CLAUDE.md](CLAUDE.md) for the complete system documentation including data model, sign conventions, known issues, and stakeholder workflows.
