# Implementation Backlog — HotelOps OKF Lite

**Version**: 1.1 (audit & hardening pass)
**Date**: 2026-07-17
**Status**: Work Breakdown
**Scope**: Engineering tasks for OKF Lite implementation

---

## Overview

This backlog transforms the OKF Lite architecture into executable engineering tasks.

**Total Estimated Effort**: 3-4 days (1 engineer)

---

## Priority Levels

- **P0**: Blocker (required for pilot)
- **P1**: High (required for mass migration)
- **P2**: Medium (post-MVP)
- **P3**: Low (deferred)

---

## Implementation Order

**Phase 1: Foundation** (Day 1)
- ISSUE-001: vault_generate_ids.py
- ISSUE-002: vault_lint.py

**Phase 2: Pilot** (Day 2 morning)
- ISSUE-003: Run pilot migration
- ISSUE-004: Resolve INVARIANTS duplication

**Phase 3: Mass Migration** (Day 2 afternoon + Day 3)
- ISSUE-005: vault_migrate.py orchestrator
- ISSUE-006: Migrate Tier 1
- ISSUE-007: Migrate Tier 2

**Phase 4: Post-MVP** (Week 2+)
- ISSUE-008: vault_extract_wikilinks.py
- ISSUE-009: vault_enrich_metadata.py
- ISSUE-010: CI validation workflow

---

## GitHub Issues

---

## ISSUE-001: Implement vault_generate_ids.py

**Priority**: P0 (Blocker)

**Complexity**: Medium (6 hours)

**Labels**: `automation`, `p0`, `day1`

---

### Title

Implement `vault_generate_ids.py` — Stable ID Generator

---

### Purpose

Generate stable, unique IDs for all vault documents and add to frontmatter.

---

### Scope

**In Scope**:
- CLI argument parsing (`--vault`, `--file`, `--all`, `--dry-run`, etc.)
- Filename → slug normalization (lowercase, hyphens, remove special chars)
- ID format: `<type>:<slug>`
- Collision detection (same ID, different files)
- Frontmatter merge (add `id:` field)
- Idempotence (skip if ID exists)
- Logging (JSON Lines format)
- Exit codes (0 = success, 1 = error, 2 = warning)
- Dry-run mode (preview without writing)

**In Scope (added v1.1)**:
- File classification per OKF_LITE_IMPLEMENTATION_SPEC.md § File Classification Rules
  (directory mapping, root-file table, Type Normalization Table) — many files have NO
  frontmatter, so the script CANNOT assume a `type` field exists
- Scope inventory output (`--all --dry-run --output json` → reviewed and frozen as
  `okf_scope_inventory.json`)
- Existing-ID preservation checks (FM-E-008: valid + type-consistent + unique, else
  flag for human review — never silently overwrite)

**Out of Scope**:
- Wikilink extraction (separate script)
- Git metadata (separate script)

---

### Dependencies

**None** (standalone script)

**Required Libraries**:
- `argparse` (CLI)
- `yaml` (frontmatter parsing)
- `re` (slug normalization)
- `os`, `pathlib` (filesystem)

---

### Acceptance Criteria

**Functional**:
- [ ] Generates ID for file with no `id:` field
- [ ] Preserves existing valid+type-consistent+unique `id:` (idempotence); flags
      unpreservable IDs as FM-E-008 (never overwrites)
- [ ] Classifies files with no frontmatter via path rules (root table + directories)
- [ ] Applies the scope predicate (exclusions, case-insensitive `_index.md`, hidden
      paths, symlinks, non-`.md`)
- [ ] Detects collisions (2+ files with same ID)
- [ ] Normalizes slug correctly (test cases in STABLE_ID_SPEC.md)
- [ ] Merges frontmatter without modifying body (INV-001)
- [ ] Validates ID format (`type:slug` pattern)
- [ ] Handles edge cases (empty filename, special chars, long names)

**CLI**:
- [ ] `--dry-run` previews without writing
- [ ] `--all` processes all markdown files
- [ ] `--file` processes single file
- [ ] `--check-collisions` checks collisions only
- [ ] `--validate` validates existing IDs
- [ ] Exit code 0 on success, 1 on error

**Performance**:
- [ ] Processes 239 files in < 10 seconds

**Testing**:
- [ ] Unit tests for slug normalization (10 test cases)
- [ ] Unit tests for collision detection
- [ ] Integration test on 4 pilot files
- [ ] Edge case tests (empty, numeric, special chars)

---

### Implementation Notes

**Reference**: STABLE_ID_SPEC.md (exact algorithm)

**Test Cases**:
```python
assert normalize_slug("CASSA_VS_COMPETENZA_sources") == "cassa-vs-competenza-sources"
assert normalize_slug("2026-05-18_PF_Rotate_Design") == "2026-05-18-pf-rotate-design"
assert normalize_slug("Plan (2026)") == "plan-2026"
```

**Collision Handling**: Fail migration (strict mode). No auto-resolution.

---

### Estimated Effort

**6 hours**:
- 2h: Core logic (slug normalization, ID generation)
- 2h: CLI, logging, dry-run
- 1h: Collision detection
- 1h: Testing

---

## ISSUE-002: Implement vault_lint.py

**Priority**: P0 (Blocker)

**Complexity**: Medium (4 hours)

**Labels**: `automation`, `p0`, `day1`

---

### Title

Implement `vault_lint.py` — OKF Lite Validator

---

### Purpose

Validate OKF Lite compliance for all vault files.

---

### Scope

**In Scope**:
- CLI argument parsing (`--vault`, `--all`, `--level`, `--strict`, etc.)
- Validation rules (11 MANDATORY, 7 RECOMMENDED, 4 INFORMATIONAL)
- Severity levels (error, warning, info)
- Summary report (text and JSON formats)
- Exit codes (0 = pass, 1 = errors, 2 = warnings if strict)
- Auto-fix (normalize line endings only)

**Out of Scope**:
- Complex auto-fixes (require manual intervention)
- Performance optimization (239 files is manageable)

---

### Dependencies

**None** (standalone script)

**Required Libraries**:
- `argparse`
- `yaml`
- `re`
- Standard library

---

### Acceptance Criteria

**Functional**:
- [ ] Validates all 11 MANDATORY rules (VAL-E-001 through VAL-E-011)
- [ ] Validates all 7 RECOMMENDED rules (VAL-W-001 through VAL-W-007)
- [ ] Validates all 4 INFORMATIONAL rules (VAL-I-001 through VAL-I-004)
- [ ] Reports errors, warnings, info separately
- [ ] Summary report (files linted, pass/fail counts)
- [ ] JSON output format (machine-readable)

**CLI**:
- [ ] `--all` lints all files
- [ ] `--file` lints single file
- [ ] `--level mandatory|recommended|informational`
- [ ] `--profile pre|post|vault` (phase profiles — the pre-flight gate uses `pre`)
- [ ] `--baseline PATH` (SHA-256 manifest input for VAL-E-009; INFO-skip if absent)
- [ ] `--strict` treats warnings as errors
- [ ] `--fix` auto-fixes line endings
- [ ] Exit code 0 on pass, 1 on errors, 2 on warnings (if strict)

**Performance**:
- [ ] Lints 239 files in < 5 seconds

**Testing**:
- [ ] Unit tests for each validation rule
- [ ] Integration test on 4 pilot files
- [ ] Test strict mode (warnings → exit 1)

---

### Implementation Notes

**Reference**: VALIDATION_SPEC.md (all rules)

**Validation Order**: UTF-8 → YAML → type → id → date → body → warnings → info

**Auto-Fix**: Only VAL-E-011 (line endings). Others require manual fix.

---

### Estimated Effort

**4 hours**:
- 2h: Validation rules (22 rules)
- 1h: CLI, reporting
- 1h: Testing

---

## ISSUE-003: Run Pilot Migration (4 Files)

**Priority**: P0 (Blocker)

**Complexity**: Low (2 hours)

**Labels**: `migration`, `pilot`, `p0`, `day2`

---

### Title

Execute OKF Lite Pilot Migration (4 Files)

---

### Purpose

Validate migration process on 4 representative files before mass migration.

---

### Scope

**Files** (paths relative to VAULT_DIR):
1. `IDENTITY.md` (constitutional, no frontmatter)
2. `concepts/FINANCIAL_RULES.md` (concept — NOTE: its `---` block sits below the H1,
   so it is NOT frontmatter; expected behavior = new block prepended, legacy block
   preserved in body. Not corruption.)
3. `decisions/2026-05-18_PF_Rotate_Design.md` (decision, perfect frontmatter)
4. `workstreams/HUB.md` (workstream_hub, Dataview queries)

**Steps**:
1. Backup 4 files
2. Run `vault_generate_ids.py --file` on each
3. Validate with `vault_lint.py --file`
4. Manual review (body preservation, frontmatter correctness)
5. Git diff review
6. Approve or rollback

---

### Dependencies

- ISSUE-001 (vault_generate_ids.py)
- ISSUE-002 (vault_lint.py)

---

### Acceptance Criteria

**Per-File**:
- [ ] IDENTITY.md: Frontmatter added, body preserved
- [ ] FINANCIAL_RULES.md: Frontmatter merged, existing fields preserved
- [ ] PF_Rotate_Design.md: ID added, existing frontmatter preserved
- [ ] HUB.md: Dataview queries preserved, frontmatter added

**Validation**:
- [ ] All 4 files pass `vault_lint.py` (0 errors)
- [ ] Body unchanged (INV-001 verified)
- [ ] No collisions
- [ ] Git diff reviewed (only frontmatter changed)

**Go/No-Go Decision**:
- [ ] If pilot succeeds → proceed to mass migration
- [ ] If pilot fails → rollback, fix scripts, retry

---

### Estimated Effort

**2 hours**:
- 1h: Run pilot (4 files × 15 min)
- 1h: Manual review, validation

---

## ISSUE-004: Resolve INVARIANTS Duplication

**Priority**: P0 (Blocker)

**Complexity**: Low (1 hour)

**Labels**: `governance`, `p0`, `day2`

---

### Title

Resolve INVARIANTS.md Duplication (KB-002 Gap)

---

### Purpose

Declare canonical source for INVARIANTS.md (vault vs repo).

---

### Scope

**Problem**: INVARIANTS.md exists in both vault (`architecture/INVARIANTS.md`) and repo (`docs/architecture/INVARIANTS.md`).

**Options**:
1. Vault = canonical, repo = copy (add pointer)
2. Repo = canonical, vault = copy (add pointer)
3. Merge into single file (one location)

**RESOLVED 2026-07-17: Option 2** — the decision was already made on 2026-04-30 and is declared INSIDE both files (`canonical: repo` frontmatter). Repo (`docs/architecture/INVARIANTS.md`, updated 2026-06-21, includes I10) is canonical; the vault copy is a stale mirror (2026-05-08, 114 diff lines behind). Remaining work for this issue: refresh the vault copy from repo OR reduce it to a stub (manual edit, Stefano's choice), and verify the migration exception (no auto `authority: canonical` on the vault copy — see spec § Rule 3-bis).

---

### Dependencies

**None**

---

### Acceptance Criteria

- [ ] Decision documented (which is canonical)
- [ ] Canonical file has `authority: canonical`
- [ ] Copy file has pointer (comment or frontmatter field)
- [ ] No ambiguity on which to trust

**Example** (vault canonical):

`architecture/INVARIANTS.md`:
```yaml
---
type: architecture
id: architecture:invariants
authority: canonical
---
```

`repo/docs/architecture/INVARIANTS.md`:
```markdown
---
type: architecture
id: architecture:invariants
authority: canonical
canonical_vault_version: architecture/INVARIANTS.md   # path relative to VAULT_DIR
---

<!-- This file is synced from vault. Do not edit directly. -->
```

---

### Estimated Effort

**1 hour**:
- 30 min: Decision + annotation
- 30 min: Validation

---

## ISSUE-005: Implement vault_migrate.py Orchestrator

**Priority**: P0 (Blocker)

**Complexity**: Medium (4 hours)

**Labels**: `automation`, `orchestration`, `p0`, `day2`

---

### Title

Implement `vault_migrate.py` — Migration Orchestrator

---

### Purpose

Orchestrate full OKF Lite migration (backup, migrate, validate, rollback).

---

### Scope

**In Scope**:
- Backup vault (full-tree filesystem copy, SHA-256 verified) + baseline manifest
  (`--write-baseline`: file + body hashes, the VAL-E-009 reference input)
- Run `vault_generate_ids.py`
- Run `vault_lint.py` (`--profile pre` before, `--baseline` after)
- Verify invariants (body preservation vs baseline, uniqueness)
- Batch-atomic rollback: ANY error in a batch restores the ENTIRE batch
  (per-file-continue is withdrawn; see § Transaction Model)
- Staged migration (Tier 1 batch → commit → Tier 2 batch)
- CLI (`--pilot`, `--tier`, `--all`, `--rollback [--batch]`, `--write-baseline`)
- Progress reporting
- Audit logging
- MVP dependency rule: uses vault_generate_ids.py + vault_lint.py ONLY — MUST NOT
  depend on vault_extract_wikilinks.py or vault_enrich_metadata.py (deferred)

**Out of Scope**:
- Git operations (manual commit post-migration)

---

### Dependencies

- ISSUE-001 (vault_generate_ids.py)
- ISSUE-002 (vault_lint.py)
- ISSUE-003 (pilot validates scripts work)

---

### Acceptance Criteria

**Functional**:
- [ ] Creates backup before migration
- [ ] Runs ID generation
- [ ] Validates pre-migration (mandatory errors = abort)
- [ ] Migrates files (adds type, id, authority)
- [ ] Validates post-migration
- [ ] Verifies invariants (body preservation)
- [ ] Rollbacks on failure
- [ ] Logs all operations (JSON Lines)

**CLI**:
- [ ] `--pilot` runs 4-file pilot
- [ ] `--tier 1` migrates Tier 1 only
- [ ] `--all` migrates all files
- [ ] `--rollback` restores from backup
- [ ] `--dry-run` previews without writing

**Rollback**:
- [ ] Rollback restores byte-for-byte
- [ ] Verification checksums match

**Testing**:
- [ ] Integration test (pilot)
- [ ] Rollback test (corrupt file → rollback → verify)

---

### Estimated Effort

**4 hours**:
- 2h: Orchestration logic
- 1h: Backup/rollback
- 1h: Testing

---

## ISSUE-006: Migrate Tier 1 (74 Files)

**Priority**: P0 (Blocker)

**Complexity**: Low (1 hour)

**Labels**: `migration`, `tier1`, `p0`, `day3`

---

### Title

Execute Tier 1 Mass Migration (74 Files)

---

### Purpose

Migrate all Tier 1 files (constitutional core, high-value knowledge).

---

### Scope

**Files**: 74 Tier 1 files (constitutional, concept, architecture)

**Steps**:
1. Checkpoint (backup Tier 1)
2. Run `vault_migrate.py --tier 1`
3. Validate (linter)
4. Spot check 10 random files
5. Git commit

---

### Dependencies

- ISSUE-005 (vault_migrate.py)

---

### Acceptance Criteria

- [ ] 74/74 files migrated
- [ ] Linter passes (0 errors, warnings OK)
- [ ] Spot check: 10 files reviewed, body preserved
- [ ] Git commit created

---

### Estimated Effort

**1 hour**:
- 10 min: Run migration
- 30 min: Spot check
- 20 min: Git commit, review

---

## ISSUE-007: Migrate Tier 2 (165 Files)

**Priority**: P0 (Blocker)

**Complexity**: Low (2 hours)

**Labels**: `migration`, `tier2`, `p0`, `day3`

---

### Title

Execute Tier 2 Mass Migration (165 Files)

---

### Purpose

Migrate all Tier 2 files (operational memory: decisions, sessions, loops).

---

### Scope

**Files**: 165 Tier 2 files

**Steps**:
1. Checkpoint (backup Tier 2)
2. Run `vault_migrate.py --tier 2`
3. Validate (linter)
4. Spot check 20 random files
5. Git commit

---

### Dependencies

- ISSUE-006 (Tier 1 complete)

---

### Acceptance Criteria

- [ ] 165/165 files migrated
- [ ] Linter passes (0 errors)
- [ ] Spot check: 20 files reviewed
- [ ] Git commit created

---

### Estimated Effort

**2 hours**:
- 10 min: Run migration
- 1h: Spot check
- 50 min: Git commit, final validation

---

## ISSUE-008: Implement vault_extract_wikilinks.py

**Priority**: P1 (Post-MVP)

**Complexity**: Low (3 hours)

**Labels**: `automation`, `relations`, `p1`, `week2`

---

### Title

Implement `vault_extract_wikilinks.py` — Wikilink Extractor

---

### Purpose

Extract wikilinks from markdown body and populate `references:` field.

---

### Scope

**In Scope**:
- Parse markdown body for `[[...]]` wikilinks
- Resolve wikilink → file → ID
- Add `references: [id1, id2]` to frontmatter
- Handle unresolved wikilinks (log warning)
- Merge with existing `references` field (don't replace)

**Out of Scope**:
- Bidirectional references (separate script)
- Manual relations (supersedes, owned_by)

---

### Dependencies

- ISSUE-006, ISSUE-007 (all IDs generated)

---

### Acceptance Criteria

- [ ] Extracts wikilinks from 22 files
- [ ] Resolves wikilinks to IDs
- [ ] Adds `references:` to frontmatter
- [ ] Preserves existing `references` (merge)
- [ ] Logs unresolved wikilinks (warnings)

---

### Estimated Effort

**3 hours**:
- 1h: Wikilink parsing
- 1h: ID resolution
- 1h: Testing

---

## ISSUE-009: Implement vault_enrich_metadata.py

**Priority**: P2 (Optional)

**Complexity**: Low (2 hours)

**Labels**: `automation`, `metadata`, `p2`, `week2`

---

### Title

Implement `vault_enrich_metadata.py` — Git Metadata Enricher

---

### Purpose

Backfill `created` and `last_updated` from Git history.

---

### Scope

**In Scope**:
- Query Git log for first commit (created)
- Query Git log for last commit (last_updated)
- Add to frontmatter
- Skip if fields already exist (idempotence)

**Out of Scope**:
- Complex Git queries (merges, renames)
- Non-Git vaults (require Git)

---

### Dependencies

- ISSUE-006, ISSUE-007 (all files migrated)
- Git history available

---

### Acceptance Criteria

- [ ] Extracts `created` from first commit
- [ ] Extracts `last_updated` from last commit
- [ ] Adds to frontmatter
- [ ] Skips if fields exist
- [ ] Handles files not in Git (log warning)

---

### Estimated Effort

**2 hours**:
- 1h: Git log queries
- 1h: Testing

---

## ISSUE-010: Setup CI Validation Workflow

**Priority**: P2 (Post-MVP)

**Complexity**: Low (1 hour)

**Labels**: `ci`, `validation`, `p2`, `week2`

---

### Title

Setup GitHub Actions CI for OKF Lite Validation

---

### Purpose

Run `vault_lint.py` on every commit to vault.

---

### Scope

**In Scope**:
- GitHub Actions workflow
- Run `vault_lint.py --all --strict`
- Block merge on errors
- Report validation status

**Out of Scope**:
- Automated fixes (require manual review)

---

### Dependencies

- ISSUE-002 (vault_lint.py)

---

### Acceptance Criteria

- [ ] Workflow runs on every push
- [ ] Runs `vault_lint.py --all`
- [ ] Fails CI if errors detected
- [ ] Reports validation summary

**Workflow File** (`.github/workflows/okf-validate.yml`):
```yaml
name: OKF Lite Validation

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: pip install pyyaml
      - name: Validate vault
        run: python scripts/vault_lint.py --all --strict
```

---

### Estimated Effort

**1 hour**:
- 30 min: Workflow creation
- 30 min: Testing

---

## Summary

| Issue | Priority | Complexity | Effort | Phase |
|-------|----------|------------|--------|-------|
| ISSUE-001 | P0 | Medium | 6h | Day 1 |
| ISSUE-002 | P0 | Medium | 4h | Day 1 |
| ISSUE-003 | P0 | Low | 2h | Day 2 |
| ISSUE-004 | P0 | Low | 1h | Day 2 |
| ISSUE-005 | P0 | Medium | 4h | Day 2 |
| ISSUE-006 | P0 | Low | 1h | Day 3 |
| ISSUE-007 | P0 | Low | 2h | Day 3 |
| ISSUE-008 | P1 | Low | 3h | Week 2 |
| ISSUE-009 | P2 | Low | 2h | Week 2 |
| ISSUE-010 | P2 | Low | 1h | Week 2 |

**Total P0 (MVP)**: 20 hours (2.5 days)

**Total P1-P2 (Post-MVP)**: 6 hours (0.75 days)

**Grand Total**: 26 hours (3.25 days)

---

## Critical Path

**Day 1** (8 hours):
- ISSUE-001: vault_generate_ids.py (6h)
- ISSUE-002: vault_lint.py (4h) — overlap 2h

**Day 2** (7 hours):
- ISSUE-003: Pilot (2h)
- ISSUE-004: INVARIANTS (1h)
- ISSUE-005: vault_migrate.py (4h)

**Day 3** (3 hours):
- ISSUE-006: Tier 1 (1h)
- ISSUE-007: Tier 2 (2h)

**Week 2** (6 hours):
- ISSUE-008: Wikilinks (3h)
- ISSUE-009: Git metadata (2h)
- ISSUE-010: CI (1h)

**Total Critical Path**: 2.5 days (MVP) + 0.75 days (Post-MVP) = **3.25 days**

---

**End of Implementation Backlog**

**Status**: Ready for execution. Issues can be created in GitHub/Linear/Jira from this spec.
