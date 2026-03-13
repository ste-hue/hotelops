# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

hotelops is the ETL and analytics pipeline for Gruppo Panorama hotel operations. It ingests financial data from multiple sources (banks, ERP, PMS) into BigQuery for reporting and reconciliation.

**Four layers:** Ontology (Obsidian) → Datahub (Google Drive `hotelops_datahub/`) → Pipelines (this repo) → Agent (NanoClaw via WhatsApp).

Code lives here. Raw data lives in the Datahub. Analytics live in BigQuery.

## GCP

- **Project:** `hotelops-suite`
- **Dataset:** `hotelops`
- **Auth:** `gcloud` authenticated as `stefano@panoramagroup.it`

## Commands

```bash
# Install
pip install -e ".[dev]"

# Run bank pipeline (fetch from Drive + ingest to BQ)
./run_banca.sh

# Run pipelines directly
python -m pipelines.banca.ingest --datahub /path/to/datahub --source ~/.cache/hotelops/tesoreria_staging
python -m pipelines.banca.ingest --datahub /path/to/datahub --source ~/.cache/hotelops/tesoreria_staging --dry-run

# Run actions
python -m actions.reconcile_banca --datahub /path/to/datahub --societa INTUR --conto SELLA --from 2025-01-01 --to 2025-01-31

# Test
pytest
pytest tests/ -k "test_name"

# Lint & format
ruff check .
ruff format .

# Check last ingested date per bank+società
bq query --use_legacy_sql=false --project_id=hotelops-suite 'SELECT societa_id, banca_id, MAX(data_operazione) AS ultima_data, DATE_DIFF(CURRENT_DATE("Europe/Rome"), MAX(data_operazione), DAY) AS giorni_indietro FROM hotelops.f_banche_movimenti GROUP BY societa_id, banca_id ORDER BY banca_id, societa_id'
```

## BigQuery Tables

| Table | Description |
|-------|-------------|
| `f_banche_movimenti` | Bank transactions — all banks, all entities |

**Useful agent queries:**
```sql
-- Check what to download per bank+società (last real transaction date, no footers)
SELECT societa_id, banca_id, MAX(data_operazione) AS ultima_data,
  DATE_DIFF(CURRENT_DATE('Europe/Rome'), MAX(data_operazione), DAY) AS giorni_indietro
FROM hotelops.f_banche_movimenti
GROUP BY societa_id, banca_id ORDER BY banca_id, societa_id

-- Monthly cashflow
SELECT DATE_TRUNC(data_operazione, MONTH) AS mese, banca_id,
  SUM(importo_netto) AS netto
FROM hotelops.f_banche_movimenti
GROUP BY 1, 2 ORDER BY 1 DESC
LIMIT 24
```

## Architecture

### Code structure

- `pipelines/` — ETL modules. Read from Drive staging, write to BigQuery.
  - `banca/fetch_drive.py` — rclone sync from Google Drive `tesoreria_ingresso` to local staging
  - `banca/ingest.py` — bank transaction ingestion. Supports: Sella CSV, Sella XLS, MPS Excel (pre-2026), MPS Excel (2026 format), Intesa Excel
- `actions/` — Runtime actions callable by the agent.
  - `reconcile_banca.py` — matches bank transactions against ledger using `bank-reconcile` cascade matcher
- `lib/` — Shared utilities:
  - `datahub.py` — `read_facts()` for reading CSV fact tables with column-based filtering
  - `contracts.py` — `validate_columns()` + `SchemaViolationError` for fail-fast schema validation
- `bq/` — BigQuery view definitions (SQL)
- `tests/` — pytest test directory

### Data model

Every fact row carries **5 dimensions**: `societa_id`, `business_unit_id`, `funzione_id`, `location_id`, `oggetto_id`.

Datahub folder structure:
- `ingresso/` — raw input files (never modified)
- `fatti/` — fact tables (CSV mirror, append-only)
- `dimensioni/mappature/` — dimension mapping CSVs
- `meta/` — logs, action run outputs, run registry

### Key patterns

- **Filename convention**: `YYYY-MM-DD__FUNZIONE__SOCIETA_BANCA__DETTAGLIO.ext` — metadata extracted via `infer_meta()`
- **Deduplication**: MD5 hash (`hash_riga`) on `societa + banca + data_operazione + importo_netto + descrizione` — safe to re-run
- **Footer filtering**: rows with `descrizione` matching "Totale (€)", "Totale", or starting with "Saldo al" are skipped at ingest
- **Data contracts**: `validate_columns()` called at ingestion — raises `SchemaViolationError` on missing columns, fail fast
- **Lineage**: `file_sorgente` + `riga_sorgente` on every row trace back to source file and line
- **Action run lifecycle**: actions write `metrics.json` with `status: running/completed/failed` + append to `runs.csv`
- **Logging**: `{datahub}/meta/pipeline/logs/`

## NanoClaw Agent Integration

NanoClaw (WhatsApp agent) can interact with this system. When acting as the hotelops agent it should:

**Answer operational questions** by querying BigQuery views:
- "Da quando scaricare le banche?" → `SELECT * FROM hotelops.v_ultima_data_banca`
- "Com'è il cashflow?" → `SELECT * FROM hotelops.v_cashflow_mensile ORDER BY mese DESC LIMIT 3`

**Trigger pipelines** when told new bank files are ready:
- Run `./run_banca.sh` in `/Users/stefanodellapietra/dev/Projects/hotelops`

**Report results** after pipeline runs:
- How many rows ingested per bank
- Any errors or schema violations
- Updated `v_ultima_data_banca` after ingest

## Governance Rules

- Every pipeline reads from `ingresso/` and appends to `fatti/` (and BigQuery).
- Every fact row must carry all 5 dimensions.
- Datahub `RULES.md` is authoritative — this repo enforces it in code.
- No speculative modules — pipelines are born from real data flows.
- Never modify `fatti/` manually — pipelines only.

## Entities

- **INTUR** — main operating company
- **ORTI** — secondary entity
- Banks: **MPS**, **MPS_KROSS**, **SELLA**, **INTESA**

## Dependencies

Python ≥3.11. Core: `pyyaml`, `openpyxl`, `bank-reconcile`, `pandas`, `google-cloud-bigquery`. Dev: `pytest`, `ruff`.
