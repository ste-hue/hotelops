---
name: save-game
description: >
  Checkpoint the hotelops CLAUDE.md so it accurately reflects the current codebase.
  Verifies concepts, pointers, and invariants against the repo — architecture layout,
  CLI surface, referenced paths, domain rules — then applies surgical fixes with no
  stale references. Use this skill whenever Stefano says "save game", "checkpoint",
  "update the claude.md", "sync the docs", or any variation of "make sure CLAUDE.md
  is up to date". Also use it proactively at the end of any session where significant
  code changes were made.
---

# Save Game — hotelops CLAUDE.md Checkpoint

You are updating the hotelops project's CLAUDE.md to match reality. CLAUDE.md is the
primary memory file every future session reads first: if it's wrong, every session
starts confused; if it's right, every session hits the ground running.

## Philosophy — concetti + puntatori, NON catalogo

Two golden rules, in tension by design:

1. **Every claim must be verifiable from the codebase.** No "I think this exists".
   Read the file, confirm it's there, confirm what it claims.
2. **CLAUDE.md holds only what does NOT regenerate**: architecture, invariants,
   domain (INTUR/ORTI), operational rules, pointers. **Catalogs live elsewhere** —
   the schema truth is BigQuery itself (`bq show` / INFORMATION_SCHEMA), curated
   detail is `core/bq/SCHEMA_CONTEXT.md` + the `hotelops-data-analyst` skill, the
   snapshot is `hotelops manifest` → `core/bq/manifest.yaml`.

The sbrinamento of 2026-06-18 cut CLAUDE.md from 525 to 178 lines by moving catalogs
out. A save that re-inflates it with table lists is a regression, not an update:
when you find a growing catalog (tables, views, per-file inventories), the fix is
to **move it out and leave a pointer**, not to refresh it in place.

## What to scan (in order)

### 1. Version, date, checkpoint blocks
- `pyproject.toml` → version; update the header line (`Last checkpoint | Version`).
- The `> **YYYY-MM-DD checkpoint:**` blocks near the top: write the new one from
  this session's real changes; keep at most the 2 most recent, older ones roll off
  (their content lives in STATUS.md / vault sessions, not here).

### 2. Architecture block
Verify the layer map against reality: `core/`, `ingest/`, `verticals/`
(`condges`, `reviews`, `spiaggia`, `hub`), `cli.py`. Check the claims about key
modules it names (e.g. `core/bq/write.py::bq_write_validated` as the only writer,
`core/lineage/`, `ingest/drive_fetch.py`) — the file must exist and still play
the stated role (read enough of it to confirm, don't assume).

### 3. Pointer integrity (the cheap, high-yield pass)
Extract every repo path CLAUDE.md references (backticked paths, docs, skills,
specs) and check each exists:

```bash
grep -oE '`[a-zA-Z0-9_./-]+\.(py|md|yaml|sql)`' CLAUDE.md | tr -d '`' | sort -u \
  | while read p; do [ -e "$p" ] || echo "STALE: $p"; done
```

The output is a **triage list, not a verdict**: expected false positives are
shorthand mentions (`pf_rotate/pf_writer.py` for the full `verticals/...` path)
and files cited *as* deleted ("app_scadenzario.py cancellato"). Judge each hit;
what remains is either a moved file (fix the pointer) or a removed one (remove
the claim). Also check referenced constants it singles out (e.g. orphan-constant
warnings) are still accurate in `core/config.py`.

### 4. CLI cheat-sheet
Compare the Commands block against `cli.py` subparsers (`grep "add_parser" cli.py`).
The cheat-sheet is deliberately partial ("la superficie completa è --help") — the
check is that every command it *does* show still exists with those flags, and that
major new commands (new verticals, new workspace actions) get a line.

### 5. Domain and rules sections
Entities, Banks/`ESOLVER_CC_MAP`, Financial Data/pf-rotate rules, Vertical Spiaggia,
Governance Rules: these are domain knowledge and change rarely — keep them stable
unless you can point at a specific stale fact. Where a claim is code-verifiable
(e.g. the Cc#→banca mapping vs `ESOLVER_CC_MAP` in
`ingest/flussi/ingest_scheda_contabile.py`), verify it.

### 6. Cross-check with STATUS.md
CLAUDE.md checkpoint ≠ STATUS.md diary. If the new checkpoint block would duplicate
what STATUS already narrates, compress: CLAUDE.md gets the durable one-liner +
pointer, STATUS keeps the story. Contradictions between the two → surface to
Stefano, don't silently pick one.

## How to write the update

1. **Surgical edits, not rewrites.** Preserve section order and headings. Fix
   facts, not prose. Use Edit for the 3-5 things that changed.
2. **Every changed line traceable** to something you verified in this scan.
3. **Anti-catalog pass**: if your update is adding a list of tables/files, stop —
   pointer + `hotelops manifest` instead.

## Verification pass

Pick 3-5 specific claims from the updated CLAUDE.md (a path, a CLI flag, a mapping,
a rule) and verify them directly against the codebase. Any failure → fix and check
3 more. Stop when a full pass comes back clean. If BQ-side claims can't be checked
(auth expired), say so — don't claim them verified.

## Output

Tell Stefano what changed, grouped:
- **Fixed** (was wrong, now correct)
- **Added** (was missing, now documented)
- **Removed** (was documented but no longer exists / rolled off to STATUS)
- **Verified** (spot-checked, confirmed correct)

Keep it concise — the point is confidence that the save is clean, not a report.
