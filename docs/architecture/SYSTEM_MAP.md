# HotelOps System Map

Purpose: give agents and humans a compact map of the system boundaries. This is
not a catalog. BigQuery schemas, source definitions, and command surfaces remain
source-of-truth in their owning files.

## Core

`core/` is the platform kernel.

Contains:
- Typed data contracts in `core/schemas.py`.
- BigQuery table/view IDs in `core/config.py`.
- BigQuery write gate in `core/bq/write.py`.
- Source registry and lineage state in `core/source_registry.yaml` and
  `core/lineage/`.
- Shared parsers/helpers that are not owned by a vertical.

Must not contain:
- Streamlit UI logic.
- Vertical-specific workflows.
- One-off repair scripts.
- Business decisions hidden as helper defaults.

Rule: if a value enters canonical BigQuery, it must cross the validation gate
and preserve lineage expectations from `docs/architecture/INVARIANTS.md`.

## Ingest

`ingest/` captures reality and promotes it into governed facts.

Standard flow:

```text
source file
  -> hotelops intake / drive fetch
  -> raw object in GCS + f_raw_objects
  -> parser selected by source registry
  -> Pydantic row model
  -> bq_write_validated
  -> canonical BigQuery f_* / d_*
```

Boundaries:
- Raw is immutable evidence.
- Parsers interpret file shape, not dashboard needs.
- Deduplication and lifecycle must match source semantics: APPEND for events,
  SNAPSHOT for state.
- Direct parser-to-BQ paths are legacy or exceptional; new work should use the
  lineage path.

Watch for drift:
- New source without `core/source_registry.yaml`.
- Parser that writes with `load_table_from_json` directly.
- File identity based only on path instead of content/raw object.
- Hidden manual corrections inside parser code.

## Verticals

`verticals/` contains business-operational products built on top of core facts.

Active verticals:
- `verticals/condges/`: treasury, controlling, PF/cash/BVA surfaces.
- `verticals/reviews/`: guest review scrape, NLP classification, alerts.
- `verticals/spiaggia/`: beach/lido revenue and reconciliation surfaces.
- `verticals/hub/`: Streamlit app-store/viewer and static launcher publishing.

Verticals may:
- Render UI.
- Orchestrate workflows for a named audience.
- Call services that write canonical data through core gates.

Verticals must not:
- Invent their own canonical truth.
- Duplicate row-selection logic already owned by a canonical view.
- Write directly to BigQuery from UI code.
- Bypass source registry, lineage, or Pydantic schemas.

Pattern: surface code should delegate to service modules when it needs to
change governed state.

## Workspace

`workspace/` is the domain-wide acquisition layer for operational evidence:
Drive, Gmail, projects, attachments, and related discovery flows.

It is not a canonical destination. Its job is to find and prepare evidence for
the raw/intake path or for explicit human review.

Watch for drift:
- Workspace code writing canonical facts directly.
- Project-specific files becoming platform assumptions.
- Credentials or local machine paths leaking into reusable code.

## Docs, Meta, Vault

`docs/` holds technical architecture, ADRs, procedures, specs, and plans.

`meta/` holds agent skills, gardener automation, and reference material that is
useful to operate the repo but is not runtime product code.

The Obsidian vault is the reasoning and memory layer. It can be stale. Repo plus
BigQuery are operational truth for technical facts.

Rules:
- `STATUS.md` is the live operational diary.
- `docs/architecture/` is for durable architecture.
- Vault session notes are memory; verify against repo/BQ before acting.
- Do not update generated indexes manually.

## Data Boundaries

Allowed in repo:
- Code.
- Tests and fixtures.
- Schemas, source registry, SQL views, ADRs, procedures.
- Small representative fixtures needed by tests.

Avoid in repo:
- Real raw exports.
- Generated Excel/PDF/dashboard outputs.
- Local credentials.
- Large snapshots.
- Exploratory vendor examples unless explicitly quarantined and gitignored.

Expected non-code data locations:
- Raw evidence: GCS, tracked by lineage.
- BigQuery: canonical/semantic operational truth.
- Local generated artifacts: `output/`, temp dirs, or explicitly ignored paths.
- Obsidian: reasoning/session memory, not canonical data.

## Production Entrypoints

CLI:
- `hotelops intake`
- `hotelops promote`
- `hotelops lineage`
- `hotelops deploy-views`
- `hotelops manifest`
- `hotelops pf`, `bva`, `chiudi`, `saldo`, `health`
- Vertical commands under `hotelops reviews`, PF rotation/generation, and related
  condges flows.

Scheduled or deployed surfaces:
- Cloud Run hub viewer from root `Dockerfile`.
- Cloudflare static launcher under `verticals/hub/publish/`.
- Review daily script in `scripts/reviews-daily.sh`.
- Spiaggia corrispettivi daily script in
  `scripts/spiaggia-corrispettivi-daily.sh`.
- Gardener automation under `meta/gardener/`.

Production entrypoints should be documented where they live. Undocumented cron,
manual script, or external deployment path is architectural drift.

## Things Not To Touch Casually

- `core/schemas.py`: changes alter canonical contracts.
- `core/source_registry.yaml`: changes alter source identity and promotion.
- `core/bq/write.py`: validation and write gate.
- `core/bq/views/*.sql`: semantic truth for consumers.
- `core/bq/dimensioni/*.csv`: canonical dimensions/mappings.
- `docs/architecture/INVARIANTS.md`: system constitution.
- `STATUS.md`: live memory; update only with verified state.
- `CLAUDE.md` / `AGENTS.md`: agent boot memory.
- `meta/gardener/`: unattended automation mandate.

## Drift Review Checklist

When reviewing a branch or Claude Code output, ask:

- Did any vertical write to BigQuery directly?
- Did any parser bypass intake/raw lineage?
- Did row-selection or dedup logic move into a UI/consumer?
- Did a source appear without registry/source definition updates?
- Did a schema, view, or mapping change without tests or explicit rationale?
- Did generated artifacts or real data enter the repo?
- Did a commit mix feature, refactor, formatting, docs, and data changes?
- Can every new number answer: source file, transformation, rule, timestamp,
  confidence level?
- If reloaded, is the result idempotent?
- If two sources disagree, is the precedence explicit and centralized?

