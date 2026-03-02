# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

hotelops is pipeline code for Gruppo Panorama data processing — an ETL and reconciliation system for hotel operations financial data. Code lives here; data lives in an external datahub (Google Drive `hotelops_datahub/`). Pipelines are orchestrated by a NanoClaw agent.

## Commands

```bash
# Install
pip install -e ".[dev]"

# Run pipelines
python -m pipelines.banca.ingest --datahub /path/to/datahub --all
python -m pipelines.banca.ingest --datahub /path/to/datahub --file FILENAME --dry-run

# Run actions
python -m actions.reconcile_banca --datahub /path/to/datahub --societa INTUR --conto SELLA --from 2025-01-01 --to 2025-01-31

# Test
pytest
pytest tests/ -k "test_name"

# Lint & format
ruff check .
ruff format .
```

## Architecture

Four layers: **Ontology** (Obsidian) → **Datahub** (Google Drive) → **Pipelines** (this repo) → **Agent** (NanoClaw).

### Code structure

- `pipelines/` — ETL modules that read from `ingresso/` and append to `fatti/`. Currently only `banca/ingest.py` (bank transaction ingestion supporting Sella CSV and MPS Excel formats).
- `actions/` — Runtime actions called by the agent. Currently `reconcile_banca.py` (matches bank transactions against ledger using `bank-reconcile` library's cascade matcher).
- `lib/` — Shared utilities. `datahub.py` provides `read_facts()` for reading CSV fact tables with column-based filtering.
- `tests/` — pytest test directory.

### Data model

Every fact row carries **5 dimensions**: `societa`, `business_unit`, `funzione`, `location`, `oggetto`. The datahub has this structure:
- `ingresso/` — raw input files
- `fatti/` — fact tables (CSV)
- `dimensioni/mappature/` — dimension mapping files
- `meta/` — logs and action run outputs

### Key patterns

- **Filename convention**: `YYYY-MM-DD__FUNZIONE__SOCIETA_BANCA__DETTAGLIO.ext` — metadata is extracted from filenames via `parse_filename()`.
- **Deduplication**: MD5 hash-based (`hash_riga` column) to prevent duplicate rows on re-runs.
- **Deterministic run IDs**: SHA256 hash of parameters for idempotent reconciliation runs.
- **Logging**: Pipeline logs go to `{datahub}/meta/pipeline/logs/`.

## Governance Rules

- Every pipeline reads from `ingresso/` and appends to `fatti/`.
- Every fact row must carry all 5 dimensions.
- Datahub `RULES.md` is authoritative — this repo enforces it in code.
- No speculative modules — pipelines are born from real data flows.

## Dependencies

Python ≥3.11. Core: `pyyaml`, `openpyxl`, `bank-reconcile`. Dev: `pytest`, `ruff`. Note: `pandas` is used implicitly by `ingest.py` for Excel reading but is not declared in pyproject.toml.
