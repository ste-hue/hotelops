# hotelops

Data engineering for Gruppo Panorama (INTUR + ORTI). Syncs raw bank files from Google Drive via rclone, parses and deduplicates them, and loads structured fact rows into BigQuery for analysis in Looker.

## Architecture

| Layer | Location | What |
|-------|----------|------|
| **Ingress** | Google Drive `hotelops_datahub/ingresso/` | Raw files uploaded by operations team |
| **Staging** | `~/.cache/hotelops/` | Local mirror synced by rclone |
| **Pipelines** | This repo | Parse → transform → deduplicate → BigQuery |
| **Warehouse** | BigQuery `hotelops-suite.hotelops` | Fact tables + views |
| **BI** | Looker | Dashboards on top of BigQuery |

## Pipelines

| Pipeline | Source | Destinations | Status |
|----------|--------|--------------|--------|
| `banca` | Sella CSV, MPS Excel, Intesa Excel | `f_banche_movimenti` | Active |
| `mastrino` | Accounting export (PDC) | `f_ledger_movimenti` | Pending real data |

## How it works

1. Rosa uploads bank exports to `TESORERIA_ingresso/` in Google Drive
2. `run_banca.sh` syncs them locally via rclone, then ingests
3. Ingest reads each file, deduplicates by content hash, appends only new rows to BigQuery
4. BigQuery views (`v_movimenti_classificati`, `v_cashflow_mensile`) classify movements and aggregate
5. Looker reads the views

## Usage

```bash
# Full pipeline (sync + ingest)
./run_banca.sh

# Dry run (no writes)
./run_banca.sh --dry-run   # not yet wired — pass via ingest directly:
python -m pipelines.banca.ingest --datahub "$DATAHUB" --dry-run

# Dev setup
pip install -e .
```

## Governance

- Pipeline code lives here. Data lives in Google Drive / BigQuery.
- Every pipeline reads from `ingresso/` and writes to BigQuery `hotelops` dataset.
- Every fact row carries 5 dimensions: societa, business_unit, funzione, location, oggetto.
- Ingestion is idempotent: content hash deduplication prevents double-counting.
- No speculative modules. Pipelines are born from real data flows.
