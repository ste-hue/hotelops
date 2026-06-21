# AGENTS.md

Guidance for Codex and other agentic coding tools in this repository.

AGENTS.md is an entrypoint, not a second constitution. The canonical invariants
live in `docs/architecture/INVARIANTS.md`; this file points to them and keeps only
the repo-specific operating habits an agent needs before touching code.

## Read First

For any non-trivial work, read in this order:

1. `docs/architecture/INVARIANTS.md` — system constitution, I1-I10.
2. `docs/architecture/AI_INSTRUCTIONS.md` — layer model, canonical registry,
   operational loop, anti-goals.
3. `docs/architecture/LE_3_DIMENSIONI.md` — CASSA / COMPETENZA / IMPEGNO.
4. `STATUS.md` — live operational diary, open fronts, recent drift.
5. This file — Codex-facing repo mechanics.

If these disagree, prefer the canonical architecture docs for durable rules and
`STATUS.md` for current operational state. Do not silently reconcile drift:
surface it.

## Project Shape

HotelOps is the Company OS for Gruppo Panorama operations. BigQuery is the
operational source of truth; code is the executable model; the Obsidian vault is
reasoning memory and can be stale unless verified against repo + BigQuery.

Main layers:

- `core/` — schemas, config, BigQuery write gate, source registry, lineage,
  canonical helpers. It must not import verticals.
- `ingest/` — file reality capture: intake / drive fetch -> Raw Object in GCS ->
  parser -> Pydantic -> `bq_write_validated`.
- `verticals/` — business surfaces for named humans: condges, reviews, spiaggia,
  hub.
- `cli.py` — `hotelops` CLI entrypoint.

For the compact boundary map, see `docs/architecture/SYSTEM_MAP.md` if present.

## Non-Negotiables

- BigQuery fact writes go through `core.bq.write.bq_write_validated` (I1).
- Table lifecycle is semantic: APPEND or SNAPSHOT, never incidental (I2).
- New ingest work uses Raw Object / GCS lineage when the source is in the GCS
  regime; direct parser-to-BQ paths are legacy or exceptional (I9).
- Every financial answer declares the temporal dimension: CASSA, COMPETENZA, or
  IMPEGNO (I4).
- Row-selection, dedup, precedence, and source conflict resolution live in
  canonical views, not Streamlit pages, CLI glue, or agent answers (I8).
- Hub apps are registry-driven. Sensitive surfaces require explicit grants and
  server-side re-checks; IAP is authentication, not application authorization
  (I10).
- No speculative modules. New pipelines start from real source files and a real
  loop target.
- Keep changes surgical. Do not refactor nearby code unless the task requires it.

## Status Discipline

Read `STATUS.md` before any multi-step plan, migration, cutover, branch triage, or
cross-cutting change. If the plan conflicts with STATUS, stop and name the
conflict.

Do not update STATUS from memory. Verify with git, files, BigQuery, or the current
conversation, then keep entries concise.

## Data And Domain Pointers

- Complete BigQuery schema: BigQuery itself (`bq show`, `INFORMATION_SCHEMA`).
- Curated schema context: `core/bq/SCHEMA_CONTEXT.md`.
- Partial manifest snapshot: `core/bq/manifest.yaml`, regenerated with
  `hotelops manifest`.
- Source registry: `core/source_registry.yaml`.
- Architecture docs and ADRs: `docs/architecture/`, `docs/adr/`.

Durable domain facts that matter often:

- Societa: `ORTI` operates Hotel / Residence / CVM; `INTUR` owns assets and runs
  Lido directly.
- Beach revenue per day = banco INTUR + alloggiati ORTI. Moolty is operational
  detail for banco, not an addend.
- `f_saldi_banca_chiusura_mensile` is the cash-control anchor.
- `d_voci_piano_finanziario` is the single PF voice mapping layer.
- Budget rows always carry `fonte`; do not mix sources without the canonical
  selection rule.

## Commands

Use `hotelops --help` for the live surface. Common checks:

```bash
pytest
ruff check .
ruff format .
hotelops manifest
hotelops deploy-views --dry-run
```

Do not run `pip install -e` from a git worktree. It can break the editable install.

## Git Hygiene

- Never use `git add .` or `git add -A` when there are unrelated untracked files.
- Never use `git checkout main -- .` on a dirty tree.
- `verticals-v2` is frozen; do not touch it.
- Keep commits logically atomic.
- Before committing, verify `git branch --show-current` is the branch you intend.

## Agent Artifacts

`CLAUDE.md` remains the richer Claude Code boot file. Do not turn AGENTS.md into a
clone of it. If another tool needs instructions, prefer a short tool-specific
entrypoint that references `AGENTS.md` and `docs/architecture/INVARIANTS.md`
instead of restating the constitution.

`.agents/` may contain local Codex/source-command skill exports. Treat it as agent
tooling, not product code, unless Stefano explicitly decides to version it.
