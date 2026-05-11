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

## Repository Structure

```text
core/         # kernel, contracts, ontology, canonical rules, validation
ingest/       # acquisition + promotion into canonical/raw layers
workspace/    # domain-wide evidence acquisition SDK (Gmail, Drive, Workspace APIs)

verticals/    # business-operational slices
  condges/    # treasury + controlling
  reviews/    # guest feedback intelligence

docs/         # architecture, ADRs, procedures
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

## Operational Memory

HotelOps uses an Obsidian vault as a long-term reasoning and operational memory layer.

Vault path:

```text
/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps
```

The vault contains:

- architectural decisions
- ontology and invariants
- session reflections
- operational procedures
- project narratives
- organizational memory

The repo is operational truth for code and execution.
The vault is reasoning substrate and organizational memory.

---

## Principles

- One canonical truth per concept
- GCS is the ingestion boundary
- BigQuery is the operational truth layer
- Business logic lives once
- Verticals own business capability, not infrastructure
- Agents operate at decision edges, not as autonomous employees

---

## Read First

1. `docs/architecture/INVARIANTS.md`
2. `docs/architecture/AI_INSTRUCTIONS.md`
3. `docs/architecture/LE_3_DIMENSIONI.md`
4. `CLAUDE.md`