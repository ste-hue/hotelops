# hotelops

Pipeline code for Gruppo Panorama data processing.

## Architecture

| Layer | Location | What |
|-------|----------|------|
| **Ontology** | Obsidian `Work/HotelOps/` | Entities, relationships, strategy |
| **Datahub** | Google Drive `hotelops_datahub/` | 5D dimensional model, facts, raw ingress |
| **Pipelines** | This repo | Code that transforms raw → facts |
| **Agent** | NanoClaw `groups/hotelops/` | Runtime that orchestrates all three |

## Governance

- Pipeline code lives here. Data lives in the datahub.
- Every pipeline reads from `ingresso/` and appends to `fatti/`.
- Every fact row carries 5 dimensions: societa, business_unit, funzione, location, oggetto.
- Datahub `RULES.md` is law. This repo enforces it in code.
- No speculative modules. Pipelines are born from real data flows.

## Pipelines

| Pipeline | Source | Status |
|----------|--------|--------|
| `banca` | Sella CSV, MPS Excel | Active |

## Usage

```bash
hotelops                # teleport here
pip install -e .        # install in dev mode

# The agent calls these, or run manually:
python -m pipelines.banca.ingest --all
python -m pipelines.banca.ingest --file FILENAME --dry-run
```
