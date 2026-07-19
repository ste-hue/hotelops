# HotelOps

HotelOps is a company operating system for hospitality.

It transforms fragmented operational reality (PMS, ERP, banks, Drive, email, manual Excel workflows) into:

- typed entities
- governed facts
- operational memory
- explicit business loops
- auditable actions

The architecture is built around:

- canonical truth
- explicit lineage
- narrow operational agents
- business verticals on top of shared infrastructure

---

## Visione

**HotelOps è il sistema attraverso cui una proprietà alberghiera indipendente acquisisce memoria, visibilità e capacità di governo, senza dipendere integralmente dalle persone che gestiscono ogni singola funzione.**

In termini operativi, HotelOps trasforma attività, decisioni e processi in un patrimonio condiviso, misurabile e migliorabile nel tempo.

## Tagline

**Dati, memoria operativa e governo: l'infrastruttura decisionale per l'hotel indipendente.**

## Versione tecnica (data pipelines)

HotelOps implementa pipeline dati per rendere osservabili i processi critici della gestione alberghiera, consolidare la memoria operativa e supportare decisioni ripetibili, tracciabili e progressivamente ottimizzabili.

---

## Repository Structure

```text
core/         # kernel: contracts, schemas, config, BQ views/loaders, lineage
ingest/       # acquisition + promotion into canonical/raw layers (GCS → BigQuery)
workspace/    # domain-wide evidence acquisition SDK (Gmail, Drive, Workspace APIs)
cli.py        # `hotelops` CLI — the operational surface

verticals/    # business-operational slices — one folder per capability,
              # each with its own README; `hub/` is the shared front door

docs/         # architecture, ADRs, procedures
tests/        # pytest suite
```

---

## Architectural Model

```text
Sources
  ↓
Raw evidence (GCS)
  ↓
Promotion + lineage
  ↓
Canonical facts (BigQuery)
  ↓
Semantic lenses
  ↓
Verticals / loops / operational surfaces
```

---

## Quickstart

```bash
pip install -e ".[dev]"
pytest
hotelops --help
```

---

## Operational Memory

HotelOps pairs the repo with a private Obsidian vault (outside this repo) as a
long-term reasoning and operational memory layer.

The vault contains:

- architectural decisions
- ontology and invariants
- per-session reflections with open-thread carry-over
- operational procedures
- project narratives
- organizational memory

The repo is operational truth for code and execution.
The vault is reasoning substrate and organizational memory.

---

## Principles

- One canonical truth per concept
- One financial event, three times: IMPEGNO, COMPETENZA, CASSA — lenses never mix them silently
- GCS is the ingestion boundary
- BigQuery is the operational truth layer
- Business logic lives once
- Verticals own business capability, not infrastructure
- Agents operate at decision edges, not as autonomous employees
- Authority decides truth: certified values outrank observed ones
- The facts pool holds actuals only; projections live in versioned artifacts
- Derived artifacts are regenerated from sources, never patched
- Nothing is dropped silently: unmapped, excluded, unknown are always surfaced
- The system adapts to how people actually work, not the reverse

---

## Read First

1. `docs/architecture/INVARIANTS.md`
2. `docs/architecture/AI_INSTRUCTIONS.md`
3. `docs/architecture/LE_3_DIMENSIONI.md`
4. `CLAUDE.md` — concepts, commands, domain rules (AI agents)
5. `AGENTS.md` — agent-agnostic operating instructions
6. `ONBOARDING.md` — human onboarding path
