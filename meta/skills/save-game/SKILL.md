---
name: save-game
description: >
  Checkpoint the hotelops CLAUDE.md so it accurately reflects the current codebase.
  Scans config.py, schemas.py, SQL views, dimension CSVs, ingest pipelines, condges modules,
  CLI entry points, and root files — then rewrites CLAUDE.md with no stale references.
  Use this skill whenever Stefano says "save game", "checkpoint", "update the claude.md",
  "sync the docs", or any variation of "make sure CLAUDE.md is up to date". Also use it
  proactively at the end of any session where significant code changes were made.
---

# Save Game — hotelops CLAUDE.md Checkpoint

You are updating the hotelops project's CLAUDE.md to match reality. This is a context engineering task: CLAUDE.md is the primary memory file that future Claude sessions read to understand the project. If it's wrong, every future session starts confused. If it's right, every future session hits the ground running.

## Philosophy

Think of CLAUDE.md as a save file in a video game. The codebase is the game world — it changes constantly. CLAUDE.md is the snapshot that lets you reload exactly where you left off. Your job is to walk through the world, compare it to the last save, and write a new save that's perfectly aligned.

**The golden rule: every claim in CLAUDE.md must be verifiable from the codebase.** No "I think this table exists." No "this file is probably at...". Read the file, confirm it's there, confirm what it contains.

## What to scan

Work through these sources in order. For each one, extract the facts and compare them against what CLAUDE.md currently claims.

### 1. Version and metadata
- `pyproject.toml` → version number, dependencies, optional deps, entry points
- Update the checkpoint date to today
- Update the version if it changed

### 2. Schema layer (this is the most important part)

**config.py** (`core/config.py`):
- Extract every `F_*`, `D_*`, `V_*` constant. These are the canonical table/view IDs.
- Any new table ID that's not in CLAUDE.md needs to be added.
- Any table ID in CLAUDE.md that's gone from config.py needs to be removed.

**schemas.py** (`core/schemas.py`):
- Extract every Pydantic model class. Each one corresponds to a fact table.
- Note the fields — these tell you column names and types.
- Check if any model has been added, removed, or had fields changed since the last save.

**View SQL files** (`core/bq/views/*.sql`):
- List every .sql file. Each one is a view.
- For each view, scan the first ~20 lines for the column list and key JOINs.
- Cross-reference: does CLAUDE.md list this view? Is the description still accurate?
- Check for views referenced in CLAUDE.md that have no .sql file (like v_budget_vs_consuntivo which is BQ-only — that's fine, but it should be noted).

**Dimension CSVs** (`core/bq/dimensioni/*.csv`):
- Count rows (wc -l minus header) to verify documented row counts.
- Check column headers match what CLAUDE.md describes.

### 3. Pipeline layer

**ingest/orchestrate.py**:
- Read it to confirm the pipeline groups (banca, amministrativa, dimensioni) and available flags.

**ingest/banca/**:
- List all .py files. Each one is a pipeline. Compare against CLAUDE.md's pipeline inventory.

**ingest/amministrativa/**:
- List all .py files. Same drill — are they all documented?

### 4. Vertical layer

**condges/**:
- List all .py files. Check each one is documented with its current purpose.
- Read the first 20 lines of app.py to verify imports are correct (this has had bugs before).

### 5. CLI

**cli.py**:
- Read the argparse/click setup to confirm subcommand names and flags match what CLAUDE.md documents.
- Count total lines (it's a useful reference).

### 6. Root files

- `ls` the repo root. Check that every file CLAUDE.md mentions exists, and that significant files that exist are mentioned.
- Pay special attention to: nanoclaw prompt file name, BRIEF docs, CHANGELOG, meta/ contents.

### 7. Deprecated directories

- Check which deprecated dirs (lib/, pipelines/, actions/, dashboard/, bq/, _archive/) still exist.
- If any have been removed since last save, update the list.

## How to write the update

Don't start from scratch. Read the current CLAUDE.md, then apply surgical fixes:

1. **Preserve the structure.** The section order and headings in CLAUDE.md are deliberate. Don't reorganize unless something is clearly wrong.

2. **Fix facts, not prose.** If a table count changed from 28 to 30, change the number. Don't rewrite the surrounding paragraph.

3. **Use the Edit tool for small changes.** If only 3-5 things changed, use targeted edits rather than a full rewrite. If many things changed (new tables, new pipelines, restructured code), a full rewrite of the affected sections is fine.

4. **The "Known Issues / Tech Debt" section is special.** Remove issues that have been fixed. Add new ones you discover during the scan (e.g., missing SQL files, import bugs, undefined schemas). This section is the "bugs I noticed while saving" list.

5. **Keep the INTUR/ORTI relationship docs, stakeholder notes, and monthly routine sections stable** unless you find specific stale references in them. These are domain knowledge, not code facts — they change rarely.

## Verification pass

After writing the update, do a quick verification:

- Pick 3-5 specific claims from the updated CLAUDE.md (a table name, a file path, a row count, a CLI flag) and verify them directly against the codebase.
- If any fail, fix them and check 3 more.
- Stop when a full pass of spot-checks comes back clean.

## Output

When done, tell Stefano what changed in a brief summary. Group changes into:
- **Fixed** (was wrong, now correct)
- **Added** (was missing, now documented)
- **Removed** (was documented but no longer exists)
- **Verified** (was correct, confirmed still correct)

Keep the summary concise — the point is confidence that the save is clean, not a lengthy report.
