# HotelOps — Copilot Instructions

HotelOps is the Company OS for Gruppo Panorama (hotel + beach operations): it
ingests banks, ERP (Esolver), PMS (HotelCube) and manual budgets into BigQuery
and serves business verticals (condges, reviews, spiaggia, hub). BigQuery is the
source of truth.

**This file is a short reminder injected into every request — not the
constitution.** The canonical rules live in `docs/architecture/INVARIANTS.md`
(I1–I10); repo mechanics in `AGENTS.md`; live operational state in `STATUS.md`.
When in doubt, read those. Surface drift, do not silently reconcile it.

## Non-negotiable invariants

- **I1** — Every BigQuery fact write goes through
  `core.bq.write.bq_write_validated`. Never bypass the validation gate.
- **I2** — Table lifecycle is semantic: APPEND (immutable facts) or SNAPSHOT
  (state at a date). Never incidental.
- **I4** — Every financial answer declares its temporal dimension: CASSA,
  COMPETENZA, or IMPEGNO.
- **I8** — Row-selection, dedup, precedence, and source-conflict resolution live
  in the canonical view — never in CLI glue, Streamlit pages, or generated
  answers.
- **I9** — New ingest passes through a tracked GCS Raw Object (lineage); no
  direct parser-to-BQ for new sources.
- **I10** — Hub apps are registry-driven. Sensitive surfaces (writes,
  irreversible actions, reserved data) need an explicit `sensitive` flag, a
  nominative grant, a server-side re-check, and a fail-closed default. IAP
  authenticates identity; it is not application authorization.

## Architecture rules

- `core/` must not import `verticals/`.
- New user-facing apps register through the hub registry
  (`verticals/hub/registry.py`), not ad-hoc mounts.
- No speculative modules: a pipeline starts from a real source file and a real
  loop target.
- Keep changes surgical; do not refactor untouched code.

## Process

- Write a spec before architectural changes; an implementation plan before large
  modifications.
- Prefer extending existing verticals over building parallel systems.
- Preserve backward compatibility unless explicitly approved.
- Read `STATUS.md` before any multi-step plan, migration, or cutover.
