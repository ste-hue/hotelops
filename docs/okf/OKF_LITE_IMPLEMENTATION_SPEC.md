# OKF Lite Implementation Specification — HotelOps

**Version**: 1.1
**Date**: 2026-07-17
**Status**: Normative
**Type**: Implementation Contract

**v1.1 changes**: Added Configuration (externally supplied `VAULT_DIR`/`BACKUP_ROOT`), Migration Scope (frozen predicate: exclusions, hidden paths, symlinks, non-Markdown, case-insensitive `_index.md`), File Classification Rules (directory mapping, root-file table, Type Normalization Table, human-review triggers, frozen scope inventory), and Transaction Model (batch-atomic — per-file-continue withdrawn). Fixed: pre-flight gate now uses validation Profile PRE (the v1.0 full-mandatory gate could never pass on an un-migrated vault), pilot file paths, baseline SHA-256 manifest as the VAL-E-009 reference, in-place determinism/idempotence tests.

---

## Document Purpose

This specification transforms the approved HotelOps OKF Lite architecture into a **deterministic, executable implementation contract**.

**Target Audience**: Any engineer (human or AI) implementing the OKF Lite migration.

**Contract Guarantee**: Two independent implementations following this spec MUST produce identical results (byte-for-byte vault state).

---

## Specification Documents

This implementation spec consists of 8 normative documents:

| Document | Purpose | Status |
|----------|---------|--------|
| **OKF_LITE_IMPLEMENTATION_SPEC.md** | Master spec (this document) | Normative |
| **MIGRATION_INVARIANTS.md** | Immutable constraints (15 invariants) | Normative |
| **FRONTMATTER_MERGE_SPEC.md** | Exact frontmatter merge algorithm | Normative |
| **STABLE_ID_SPEC.md** | Stable ID generation algorithm | Normative |
| **VALIDATION_SPEC.md** | All validation rules (22 rules) | Normative |
| **ROLLBACK_SPEC.md** | Backup and rollback procedures | Normative |
| **AUTOMATION_CONTRACTS.md** | Script interface contracts (5 scripts) | Normative |
| **IMPLEMENTATION_BACKLOG.md** | Engineering tasks (10 issues, 3.25 days) | Work Breakdown |

**Normative Status**: Implementations MUST conform to normative specs. Deviation = non-compliance.

---

## Architecture Baseline

The following architecture documents are **approved and frozen**:

- **HOTELOPS_OKF_LITE_PROFILE.md** — Type system, authority, metadata, relations
- **CORE_VS_LITE_MATRIX.md** — Simplification rationale
- **SIMPLIFICATION_DECISIONS.md** — Design decisions
- **MVP_REQUIREMENTS.md** — Compliance definition
- **DEFERRED_FEATURES.md** — Roadmap
- **REVISED_PILOT_PLAN.md** — 4-file pilot

**Implementation MUST NOT modify architecture**. Architecture phase is complete.

---

## Configuration (Normative)

All scripts receive their environment via **externally supplied configuration** — CLI arguments or environment variables. Specifications and scripts MUST NOT hardcode machine-specific absolute paths.

| Variable | Meaning | Supplied via |
|----------|---------|--------------|
| `VAULT_DIR` | Absolute path to the HotelOps vault root | `--vault` (required) or env `OKF_VAULT_DIR` |
| `BACKUP_ROOT` | Absolute path to the backup area. MUST be outside the Git repository containing `VAULT_DIR` | `--backup-root` or env `OKF_BACKUP_ROOT` |

Derived (never independently configured): `BACKUP_DIR = $BACKUP_ROOT/<UTC timestamp YYYYMMDD_HHMMSS>` — one directory per backup, never overwritten.

**Deployment example (non-normative, current machine only)**:
```
VAULT_DIR   = /Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps
BACKUP_ROOT = /Users/stefanodellapietra/dev/Projects/obsidian/hotelops-backups
```
(Here the Git repository root is `Obsidian Vault/`, one level above `VAULT_DIR` — which is why `BACKUP_ROOT` sits outside it, as a sibling of `Obsidian Vault/`.)

Wherever any specification document shows an absolute path, read it as a **non-normative deployment example** of the corresponding variable.

---

## Migration Scope (Frozen)

The scope predicate below is total: for every filesystem object under `VAULT_DIR`, it decides in-scope / out-of-scope with no judgment calls. Checked in order; first match wins.

1. **Symlinks**: never followed, never migrated. A symlink anywhere in scope → log WARN, out-of-scope. (Backup: symlinks are copied as symlinks; they are restored but never edited.)
2. **Hidden paths**: any path component starting with `.` (e.g. `.obsidian/`, `.DS_Store`, `.trash/`) → out-of-scope for migration; included in backup/restore.
3. **Non-Markdown files**: extension ≠ `.md` (case-sensitive) → out-of-scope for migration; included in backup/restore. (Backup and rollback always operate on the **entire** `VAULT_DIR` tree; migration only ever writes `.md` files.)
4. **Excluded directories** (deferred tiers/types): path starts with `_archive/`, `ontology/`, `reports/`, `docs/`, `journal/`, `protocols/`, `relationships/`, `strategia/`, `threads/` → out-of-scope (ontology deferred per SD-008; reports/index deferred per SD-001; rest are Tier 3-5 in the baseline inventory).
5. **Index files**: filename lowercased equals `_index.md` → out-of-scope (`index` type deferred). **Case-insensitive is mandatory**: the vault contains both `sessions/_INDEX.md` and `decisions/_index.md`.
6. **Excluded root files**: `INDEX.md`, `LOOPS.md`, `WHERE_WE_ARE.md` → out-of-scope (typed `index` in OKF_FILE_MANIFEST; index deferred). `COCKPIT_EXPORT.md` → out-of-scope (self-described "snapshot export per AI", report-family; `report` type is deferred — resolved 2026-07-17, gate 1).
7. **Everything else ending in `.md`** under the mapped directories (§ Classification Rule 2) or listed in the root-file table (§ Classification Rule 3) → **in-scope**.
8. A `.md` file matching none of the above (new unmapped directory, unlisted root file) → out-of-scope + log WARN — signals vault drift; human adds a rule or an exclusion.

---

## File Classification Rules

**Added in v1.1** — closes the largest v1.0 gap: no deliverable defined how a file receives its `type`. Classification is fully deterministic; the only human step is explicit and bounded (Rule 5).

### Rule 2 — Directory mapping (deterministic default)

| Path prefix | Type | Tier |
|-------------|------|------|
| `concepts/` | `concept` | 1 |
| `architecture/` | `architecture` | 1 |
| `decisions/` | `decision` | 2 |
| `plans/` | `decision` (plan→decision merge, SD-001) | 2 |
| `sessions/` | `session` | 2 |
| `loops/` | `loop` | 2 |
| `procedures/` | `loop` (procedure→loop merge, SD-001) | 2 |
| `workstreams/` | `workstream_hub` | 2 |
| `verticals/` | `vertical` | 2 |

### Rule 3 — Root-file table (explicit, per file)

| File | Type | Tier | Confidence |
|------|------|------|------------|
| `IDENTITY.md` | `constitutional` | 1 | High |
| `KERNEL.md` | `constitutional` | 1 | High (legacy `type: kernel` normalizes) |
| `PLATFORM.md` | `constitutional` | 1 | High |
| `GRUPPO_PANORAMA.md` | `constitutional` | 1 | High (legacy `type: gruppo_consolidato` normalizes) |
| `SUPPLIERS_STRATEGY.md` | `concept` | 1 | High (per OKF_FILE_MANIFEST) |
| `log.md` | `log` | 2 | High |
| `KICKOFF_PROMPT.md` | `loop` (procedure→loop, SD-001) | 2 | **Resolved 2026-07-17** (gate 1, Stefano): loop atipico — pointer operativo di inizio sessione. Legacy `type: kickoff_prompt` normalizza. Optional manual edits post-migrazione: `owner: platform`, `cadence: on-session-start` (senza, VAL-W-005/W-007 warnano, non bloccano) |
| `COCKPIT_EXPORT.md` | — excluded | — | **Resolved 2026-07-17** (gate 1): report-family snapshot ("export per AI", fermo al 2026-06-08), esclusa come `WHERE_WE_ARE.md`; sarà `report` quando il tipo deferred arriverà |

### Rule 3-bis — Per-file exceptions

| File | Exception |
|------|-----------|
| `architecture/INVARIANTS.md` | Legacy `type: invariants` → `architecture` (Normalization Table), but **authority is NOT auto-assigned** (the default for `architecture` would be `canonical`; this file declares `canonical: repo` — it is a stale mirror of `repo/docs/architecture/INVARIANTS.md`, the true SSOT since 2026-04-30). Migration inserts `type` and `id` only. |

### Rule 4 — Existing `type:` conflict resolution

1. Frontmatter `type:` present and **valid enum** → it wins over the directory mapping, even if different. Log INFO. (Never fight the author.)
2. Frontmatter `type:` present but **invalid** → **Type Normalization Table**:

| Legacy value | Normalizes to |
|--------------|---------------|
| `business_logic` | `concept` |
| `kernel` | `constitutional` |
| `gruppo_consolidato` | `constitutional` |
| `procedure` | `loop` |
| `kickoff_prompt` | `loop` |
| `invariants` | `architecture` |
| `architecture_audit` | `architecture` |
| `architecture_explanation` | `architecture` |
| `catalog` | `concept` |
| `plan` | `decision` |
| `Decision` | `decision` |
| `Decisione Architetturale` | `decision` |
| `Decisione Architetturale (Parking Lot)` | `decision` |
| `Decisione Tecnica` | `decision` |
| `Decisione Strategica` | `decision` |

   Matching is **exact string** (case-sensitive, full value including any parenthetical). Any invalid value NOT in this table → **FM-E-007, human review** (never guess).

   **Reality note**: the baseline's claim that decisions have "100% perfect frontmatter" is false — 11 of 61 decision files carry the Italian legacy variants above (observed 2026-07-17). The pilot file `2026-05-18_PF_Rotate_Design.md` is genuinely `type: decision`.
3. No frontmatter / no `type:` → Rule 3 (root) or Rule 2 (directory).

### Rule 5 — Human review triggers (the confidence threshold)

Classification is rule-based, so confidence is binary: rule-covered (high) or flagged (low). Human review (Stefano, at the pilot gate) is REQUIRED when:

1. The file is marked LOW in the root-file table (0 today — the 2 original LOW files were resolved 2026-07-17 at gate 1: KICKOFF_PROMPT→loop, COCKPIT_EXPORT→excluded)
2. FM-E-007 fires (invalid legacy type not in the normalization table)
3. An existing `id:` fails preservation checks (FM-E-008, see FRONTMATTER_MERGE_SPEC)
4. The scope inventory deviates from expected counts by more than ±5 files per tier — signals vault drift or a rule bug

**No file is ever migrated with a guessed type.** Unresolved = excluded from the batch and logged.

### Scope inventory (the authoritative file list)

The baseline's counts (74 + 165 = 239) are a **snapshot from 2026-07-16 and the vault is alive** (on 2026-07-17 the rules yield ≈238 rule-covered files + 2 review-pending; sessions/ has already grown by one). Therefore:

1. Before the pilot: `vault_generate_ids.py --all --dry-run --output json` — the output IS the classified inventory (path, type, tier, proposed id, action)
2. Human reviews it (including LOW-confidence files) and commits it as `okf_scope_inventory.json`
3. The committed inventory is the **frozen scope** for the migration run. Scripts operate on it, not on live re-classification. Expected magnitudes: Tier 1 ≈ 68, Tier 2 ≈ 171; deviation > ±5 per tier → stop, reconcile.

---

## Transaction Model (Normative)

**One model, everywhere: batch-atomic.**

- A **batch** is the file set of one invocation: `--pilot` (4 files), `--tier 1`, `--tier 2`, or `--all` (per the frozen inventory).
- Before any write: full-tree backup + SHA-256 baseline manifest (see ROLLBACK_SPEC).
- During the batch: files are migrated one at a time, each immediately POST-validated.
- **Any error anywhere in the batch** (migration error FM-E-00x on an in-scope file, any MANDATORY validation failure, any invariant violation, any I/O error) → **abort the batch and restore every file of the batch from the backup**. No partially migrated batch is ever left on disk.
- Vault-wide checks (VAL-E-007 uniqueness) run after the batch; failure → same batch rollback.
- A batch that completes cleanly is sealed with a Git commit before the next batch starts. Tier 2 failure therefore never touches committed Tier 1 (this preserves the baseline's staged Tier 1 → Tier 2 plan: the stage IS the batch).
- Per-file restore exists only as an internal primitive used by batch rollback — it is not an error-handling policy. (v1.0's "rollback file, log, continue to next file" is withdrawn.)

Files excluded pre-batch (FM-E-007/FM-E-008 human-review flags discovered during the *dry-run inventory*) are not batch members and do not trigger rollback; the batch simply doesn't contain them. The same condition discovered *live during a batch* is an error → batch rollback (it means the frozen inventory was stale).

---

## Implementation Principles

### Determinism

**Requirement**: Identical inputs → identical outputs (byte-for-byte).

**Validation** (migration is in-place — no `--output` flag exists; test on two clones):
```bash
cp -r "$VAULT_DIR" /tmp/run1 && cp -r "$VAULT_DIR" /tmp/run2
python vault_migrate.py --vault /tmp/run1 --all
python vault_migrate.py --vault /tmp/run2 --all

# Outputs must be identical
diff -r /tmp/run1 /tmp/run2
# Exit code 0 = deterministic
```

**Sources of Non-Determinism** (MUST eliminate):
- Timestamps (`datetime.now()`) — use Git timestamps or fixed values
- Random UUIDs — use slug-based IDs
- Dictionary iteration order — use `sorted()` on keys
- Filesystem traversal order — use `sorted(glob())`
- Floating-point operations — avoid or use deterministic rounding

---

### Idempotence

**Requirement**: Running migration N times = running it once.

**Validation** (in-place: run, snapshot, run again, compare):
```bash
cp -r "$VAULT_DIR" /tmp/pass1
python vault_migrate.py --vault /tmp/pass1 --all
cp -r /tmp/pass1 /tmp/pass2
python vault_migrate.py --vault /tmp/pass2 --all

# Pass1 and Pass2 must be identical
diff -r /tmp/pass1 /tmp/pass2
# Exit code 0 = idempotent
```

**Implementation**:
- If field exists, skip (don't regenerate)
- Check preconditions before modifying
- Use checksums to detect no-op cases

---

### Reversibility

**Requirement**: Every operation can be undone (byte-for-byte restoration).

**Validation**: See ROLLBACK_SPEC.md

**Implementation**:
- Backup before modification
- Verify backup after creation
- Rollback = filesystem copy (not diff, not archive)
- Verify restoration checksums

---

### Testability

**Requirement**: All algorithms have unit tests.

**Minimum Coverage**:
- Slug normalization: 10 test cases
- ID generation: 8 test cases
- Frontmatter merge: 6 test cases
- Validation rules: 1 test per rule (22 tests)
- Rollback: 3 scenarios

---

## Migration Workflow

### Phase 1: Pre-Migration

**Steps**:
1. **Git Checkpoint**: Commit current vault state
   ```bash
   git add .
   git commit -m "Pre-migration checkpoint: OKF Lite"
   ```

2. **Backup + Baseline Hashes**: Full-tree filesystem backup, then a SHA-256 baseline manifest of every in-scope file (full-file hash AND body hash). The body hashes are the reference input for VAL-E-009 — the migrated file alone cannot prove its body is unchanged.
   ```bash
   cp -r "$VAULT_DIR" "$BACKUP_DIR"
   python vault_migrate.py --vault "$VAULT_DIR" --write-baseline okf_baseline_manifest.json
   ```
   (Manifest format and verification: ROLLBACK_SPEC.md § Baseline Manifest.)

3. **Pre-Flight Validation**: Profile PRE only — encoding, line endings, YAML parseability, date formats. NOT the full mandatory set: VAL-E-002…007 check the very fields migration adds and would always fail pre-migration (see VALIDATION_SPEC.md § Validation Profiles).
   ```bash
   python vault_lint.py --vault "$VAULT_DIR" --all --profile pre
   # Must exit 0 (no errors)
   ```

4. **Scope Inventory + Collision Check**: Generate the classified inventory (dry-run), review it — including the LOW-confidence root files — and freeze it as `okf_scope_inventory.json`. Collisions must be zero.
   ```bash
   python vault_generate_ids.py --vault "$VAULT_DIR" --all --dry-run --output json > okf_scope_inventory.json
   python vault_generate_ids.py --vault "$VAULT_DIR" --check-collisions
   # Must exit 0 (no collisions)
   ```

**Go/No-Go**: If any step fails → FIX MANUALLY before proceeding.

---

### Phase 2: Pilot (4 Files)

**Purpose**: Validate migration on representative sample.

**Files** (paths relative to `VAULT_DIR` — v1.0 omitted them):
1. `IDENTITY.md` — constitutional, no frontmatter
2. `concepts/FINANCIAL_RULES.md` — concept, legacy `type: business_logic`, large (341 lines). **Reality note**: its `---` block sits BELOW the H1, so it is NOT frontmatter (fence not at byte 0) — expected pilot behavior is a new block prepended and the legacy block preserved in the body (FRONTMATTER_MERGE_SPEC.md, Example 4 reality note). Do not flag this as corruption.
3. `decisions/2026-05-18_PF_Rotate_Design.md` — decision, perfect frontmatter
4. `workstreams/HUB.md` — workstream_hub, Dataview queries

**Steps** (the pilot is a batch — same transaction model as mass migration; no ad-hoc `.backup` files):
1. **Dry-Run Preview + Unified Diff**
   ```bash
   python vault_migrate.py --vault "$VAULT_DIR" --pilot --dry-run
   # Emits proposed per-file changes and a unified diff (pilot_git_diff preview)
   ```

2. **Apply Pilot Batch** (backup + baseline manifest already exist from Phase 1)
   ```bash
   python vault_migrate.py --vault "$VAULT_DIR" --pilot
   # Batch-atomic: any error → all 4 files restored from backup automatically
   ```

3. **Validate**
   ```bash
   python vault_lint.py --vault "$VAULT_DIR" --file IDENTITY.md \
       --baseline okf_baseline_manifest.json
   # Repeat for the other 3 files. Must exit 0.
   ```

4. **Manual Review**
   - Open each file in Obsidian
   - Verify frontmatter added/merged
   - Verify body unchanged (visual inspection)
   - Check Dataview queries render (workstreams/HUB.md)

5. **Git Diff Review**
   ```bash
   git diff
   # Only frontmatter should change, only in the 4 pilot files
   ```

6. **Approval Decision**
   - If all 4 files pass → **GO** (proceed to mass migration)
   - If any file fails → **NO-GO** (rollback batch, fix scripts, retry pilot)

**Rollback** (if NO-GO — restores the whole pilot batch from backup):
```bash
python vault_migrate.py --vault "$VAULT_DIR" --rollback --batch pilot
```

---

### Phase 3: Mass Migration

**Approach**: Staged migration (Tier 1 → Tier 2) with checkpoints.

---

#### Stage 3.1: Tier 1 (≈68 files — authoritative count = frozen inventory)

**Files**: Constitutional, concepts, architecture (high-value core knowledge), per the frozen inventory

**Steps**:
1. **Checkpoint**
   ```bash
   git add .
   git commit -m "Checkpoint: Pre-Tier-1 migration"
   ```

2. **Migrate**
   ```bash
   python vault_migrate.py --vault "$VAULT_DIR" --tier 1
   ```

3. **Validate**
   ```bash
   python vault_lint.py --vault "$VAULT_DIR" --tier 1 --baseline okf_baseline_manifest.json
   # Must exit 0
   ```

4. **Spot Check** (10 random files)
   - Open in Obsidian
   - Verify body unchanged
   - Verify frontmatter correct

5. **Git Diff**
   ```bash
   git diff
   # Review all changes (only frontmatter)
   ```

6. **Commit**
   ```bash
   git add .
   git commit -m "OKF Lite: Tier 1 migration complete (74 files)"
   ```

**Rollback** (if validation fails):
```bash
git reset --hard HEAD~1  # Rollback to checkpoint
```

---

#### Stage 3.2: Tier 2 (≈170 files — authoritative count = frozen inventory)

**Files**: Decisions, sessions, loops, workstreams, verticals, log (operational memory), per the frozen inventory

**Steps**: Same as Tier 1

**Checkpoint**:
```bash
git commit -m "Checkpoint: Pre-Tier-2 migration"
```

**Migrate**:
```bash
python vault_migrate.py --vault "$VAULT_DIR" --tier 2
```

**Spot Check**: 20 random files

**Commit**:
```bash
git commit -m "OKF Lite: Tier 2 migration complete (165 files)"
```

---

### Phase 4: Post-Migration Validation

**Steps**:

1. **Full Vault Validation**
   ```bash
   python vault_lint.py --vault "$VAULT_DIR" --all --baseline okf_baseline_manifest.json
   # Must exit 0
   ```

2. **Invariant Verification**
   - INV-007: ID uniqueness (vault-wide)
   - INV-008: Determinism (dual-run test)
   - INV-009: Idempotence (dual-pass test)
   - INV-010: Reversibility (rollback test)

3. **Manual Smoke Test**
   - Open vault in Obsidian
   - Navigate to 5 random files
   - Verify rendering correct
   - Check Dataview queries work
   - Check wikilinks resolve

4. **Final Commit**
   ```bash
   git add .
   git commit -m "OKF Lite migration complete (239 files)"
   ```

5. **Cleanup Backup** (after 7 days, manual)
   ```bash
   rm -rf "$BACKUP_DIR"
   ```

---

## Critical Path Timeline

### Day 1: Build Automation (8 hours)

**Morning** (4 hours):
- ISSUE-001: Build `vault_generate_ids.py` (slug normalization, ID generation, collision detection)
- Unit tests (10 test cases)

**Afternoon** (4 hours):
- ISSUE-002: Build `vault_lint.py` (22 validation rules)
- Unit tests (22 test cases)

**Deliverables**:
- `vault_generate_ids.py` (working, tested)
- `vault_lint.py` (working, tested)

---

### Day 2: Pilot + Orchestration (7 hours)

**Morning** (3 hours):
- ISSUE-003: Run pilot (4 files, manual review)
- ISSUE-004: Resolve INVARIANTS duplication (declare canonical)

**Afternoon** (4 hours):
- ISSUE-005: Build `vault_migrate.py` (orchestrator: backup, migrate, validate, rollback)
- Integration test (pilot)

**Deliverables**:
- Pilot validated (4 files migrated, approved)
- INVARIANTS resolved
- `vault_migrate.py` (working)

---

### Day 3: Mass Migration (3 hours)

**Morning** (1 hour):
- ISSUE-006: Migrate Tier 1 (74 files)
- Spot check (10 files)
- Git commit

**Afternoon** (2 hours):
- ISSUE-007: Migrate Tier 2 (165 files)
- Spot check (20 files)
- Git commit
- Final validation

**Deliverables**:
- 239 files migrated
- Vault OKF Lite compliant
- Git history clean

**Total MVP Time**: **2.5 days** (20 hours)

---

### Week 2: Post-MVP Enhancements (6 hours)

**Optional** (defer if needed):
- ISSUE-008: Extract wikilinks (3 hours)
- ISSUE-009: Enrich Git metadata (2 hours)
- ISSUE-010: CI validation (1 hour)

---

## Validation Gates

**Every phase MUST pass validation before proceeding.**

| Phase | Gate | Condition | Failure Action |
|-------|------|-----------|----------------|
| Pre-Migration | Pre-flight check | Linter passes (mandatory) | Fix manually |
| Pre-Migration | Collision check | 0 collisions | Rename files |
| Pilot | File validation | 4/4 pass linter | Rollback, fix scripts |
| Pilot | Manual review | Body preserved, frontmatter correct | Rollback |
| Pilot | Go/No-Go | Approval decision | No-Go → rollback |
| Tier 1 | Linter | all Tier 1 files pass | Rollback batch (tier) |
| Tier 1 | Spot check | 10/10 correct | Rollback batch (tier) |
| Tier 2 | Linter | all Tier 2 files pass | Rollback batch (tier) |
| Tier 2 | Spot check | 20/20 correct | Rollback batch (tier) |
| Post-Migration | Vault-wide validation | all in-scope files pass, 0 collisions | Rollback all |
| Post-Migration | Smoke test | Obsidian renders correctly | Investigate |

**Zero Tolerance**: Any validation failure = STOP, ROLLBACK, FIX.

---

## Error Handling Policy

**Single policy: batch-atomic** (see § Transaction Model). v1.0's per-file "rollback file, log, continue" is **withdrawn** — it could leave a half-migrated batch on disk.

### Any Error During a Batch

**Behavior**: Abort the batch, restore EVERY file of the batch from backup, log, exit 1.

**Example**:
```python
try:
    for filepath in batch_files:
        migrate_file(filepath)
        validate_file(filepath)          # POST profile, incl. VAL-E-009 vs baseline
    validate_id_uniqueness(vault)        # VAULT profile
except (MigrationError, ValidationError, OSError) as e:
    log_error(f"Batch failed at {filepath}: {e}")
    rollback_batch(batch_files, backup_dir)   # restore all batch members
    sys.exit(1)
```

**Rationale**: A batch either lands whole and validated, or it never happened. Committed prior batches (e.g. Tier 1) are untouched by a later batch's rollback.

---

### Script/Setup Errors (before any write)

**Behavior**: Fail fast. No backup (or failed backup verification) = no migration.

**Example**:
```python
try:
    backup_vault()
    verify_backup_checksums()
except IOError as e:
    log_error(f"Backup failed: {e}")
    print("ABORT: Cannot proceed without verified backup")
    sys.exit(1)
```

---

## Compliance Definition

**"OKF Lite Compliant"** means:

### REQUIRED (R1-R4)

1. ✅ Every Tier 1-2 file has `type:` field (valid enum)
2. ✅ Every file has `id: type:slug` (stable, unique)
3. ✅ Linter passes (YAML valid, type valid, dates valid)
4. ✅ INVARIANTS duplication resolved

**Minimum to declare success**: R1-R4 ONLY.

### RECOMMENDED (W1-W2)

5. ⚠️ Every Tier 1 file has `authority:`
6. ⚠️ Type-specific fields present (decisions/sessions/loops/workstreams)

**Warnings OK**. Log and review, but don't block.

### OPTIONAL (O1-O3)

7. ➕ Wikilinks extracted to `references:`
8. ➕ Git metadata enriched
9. ➕ Manual relations added

**Deferred to Week 2+**.

---

## Testing Strategy

### Unit Tests

**Coverage**: Every algorithm has tests.

**Files**:
- `test_slug_normalization.py` (10 test cases)
- `test_id_generation.py` (8 test cases)
- `test_frontmatter_merge.py` (6 test cases)
- `test_validation_rules.py` (22 test cases)
- `test_rollback.py` (3 scenarios)

**Run**:
```bash
pytest tests/ -v
```

---

### Integration Tests

**Coverage**: End-to-end workflows.

**Tests**:
1. **Pilot Test**: Migrate 4 pilot files, validate, rollback
2. **Idempotence Test**: Run migration twice, compare outputs
3. **Determinism Test**: Run migration on same input twice, compare
4. **Rollback Test**: Migrate, corrupt file, rollback, verify

**Run**:
```bash
pytest tests/integration/ -v
```

---

### Manual Tests

**Coverage**: Human verification.

**Checklist**:
- [ ] Obsidian opens vault without errors
- [ ] 5 random files render correctly
- [ ] Dataview queries work (HUB.md)
- [ ] Wikilinks resolve
- [ ] Frontmatter displays in properties pane
- [ ] No file loss (file count unchanged)
- [ ] No body corruption (spot check 20 files)

---

## Rollback Scenarios

See ROLLBACK_SPEC.md for detailed procedures.

**Quick Reference**:

| Scenario | Trigger | Action |
|----------|---------|--------|
| Pilot fails | Validation error | Rollback 4 pilot files |
| Tier 1 fails | Linter error | Rollback Tier 1 batch from backup (Git reset = fallback) |
| Tier 2 fails | Linter error | Rollback Tier 2 batch from backup (Git reset = fallback) |
| Duplicate IDs | Post-migration | Rollback entire vault |
| User dissatisfied | Manual request | Rollback entire vault (Git reset) |
| Backup lost | Disaster | Git reset to pre-migration commit |

**Rollback Command**:
```bash
python vault_migrate.py --rollback
# OR
git reset --hard <pre-migration-commit>
```

---

## Acceptance Criteria

**MVP is COMPLETE when**:

### Functional

- [ ] All in-scope files migrated (per frozen inventory, ≈238)
- [ ] R1: All files have `type:` (valid enum)
- [ ] R2: All files have `id:` (stable, unique, `type:slug` format)
- [ ] R3: Linter passes (0 errors, warnings OK)
- [ ] R4: INVARIANTS duplication resolved

### Invariants

- [ ] INV-001: Body preservation (all in-scope files, verified against the SHA-256 baseline manifest)
- [ ] INV-007: Frontmatter merge, never replace
- [ ] INV-008: Determinism (dual-run test passes)
- [ ] INV-009: Idempotence (dual-pass test passes)
- [ ] INV-010: Reversibility (rollback test passes)
- [ ] INV-011: No file moves
- [ ] INV-012: No file renames
- [ ] INV-013: No content rewriting

### Validation

- [ ] All MANDATORY rules pass (VAL-E-001 through VAL-E-011)
- [ ] No duplicate IDs (VAL-E-007)
- [ ] UTF-8 encoding (VAL-E-010)
- [ ] Unix line endings (VAL-E-011)

### Testing

- [ ] Unit tests pass (100% coverage on algorithms)
- [ ] Integration tests pass (4 workflows)
- [ ] Manual smoke test pass (Obsidian renders correctly)

### Documentation

- [ ] Git history clean (meaningful commits)
- [ ] Audit log complete (all operations logged)
- [ ] Backup retained (7 days or until validated)

**Sign-Off**: Stefano approves migration (manual review, spot checks pass).

---

## Final Question

**Could an engineer who has never seen the HotelOps vault implement the migration correctly using only these specifications?**

### Answer: YES — as of v1.1. (The honest answer for v1.0 was NO.)

v1.0 claimed "Remaining Ambiguities: NONE" while containing at least ten determinism-breaking defects, discovered and fixed in the v1.1 audit:

1. Slug algorithm contradicted its own examples (delete vs. replace-with-hyphen) — fixed: replace-with-hyphen, normative
2. `workstream_hub` IDs failed the spec's own regex; one test case contradicted the frozen baseline — fixed: enum-anchored ID pattern
3. Pre-flight gate could never pass (full mandatory set requires the fields migration adds) — fixed: validation Profiles PRE/POST/VAULT
4. VAL-E-008 rejected every existing decision/session (unquoted YAML dates parse as `datetime.date`, not `str`) — fixed
5. Merge algorithm re-serialized frontmatter (alphabetical keys, comment loss, flow→block), contradicting the pilot plan's expected outputs — fixed: line-preserving insertion algorithm (v1.1)
6. Malformed-YAML policy was self-contradictory (fail-safe shown, strict "recommended") — fixed: strict-fail, single policy
7. Silent CRLF normalization violated INV-001/INV-014 — fixed: reject, never convert (explicit `--fix` only)
8. No file classification or scope rules existed at all — fixed: § Migration Scope + § File Classification Rules
9. Machine/sandbox paths were baked into normative text — fixed: § Configuration (externally supplied `VAULT_DIR`/`BACKUP_ROOT`)
10. Error handling mixed per-file-continue with staged rollback — fixed: § Transaction Model (batch-atomic)

Plus: VAL-E-009 now has a defined reference input (SHA-256 baseline manifest — the migrated file alone cannot prove body preservation); existing IDs are preserved only when valid, type-consistent and unique (FM-E-008 otherwise); checksums are portable SHA-256; `vault_migrate.py` no longer depends on deferred post-MVP scripts; status enums are grounded in observed vault values; and `concepts/FINANCIAL_RULES.md`'s real layout (fence below the H1 — not frontmatter) is documented as an expected pilot deviation.

**Remaining decisions — human, explicit, and gated (not spec ambiguities)**:

1. ~~KICKOFF_PROMPT.md / COCKPIT_EXPORT.md classification~~ — **RESOLVED 2026-07-17**: KICKOFF_PROMPT → `loop` (legacy type in normalization table), COCKPIT_EXPORT → excluded (report-family)
2. ~~INVARIANTS canonical declaration~~ — **RESOLVED 2026-07-17**: the files themselves already decided it on 2026-04-30 — BOTH copies carry `canonical: repo` frontmatter ("Migrated from Obsidian vault"). **Repo is canonical** (`docs/architecture/INVARIANTS.md`, last updated 2026-06-21, includes I10); the vault copy is a stale mirror (2026-05-08, 114 diff lines behind). v1.1's earlier vault-canonical recommendation was wrong — it ignored the declaration inside the files. Migration exception: `architecture/INVARIANTS.md` gets `type: architecture` (legacy `invariants` normalizes) but NO auto `authority: canonical` — authority is omitted (mirror, not SSOT). Refreshing or stubbing the stale vault copy is a manual, post-migration chore (INV-013: migration never rewrites content).
3. **Scope inventory sign-off** — the frozen `okf_scope_inventory.json` is reviewed and committed by a human before the pilot; the baseline's 239 is a 2026-07-16 snapshot of a living vault (~238 rule-covered + 2 review-pending on 2026-07-17)

An engineer with zero HotelOps context can now: read these 8 specs, implement the 5 scripts against exact interfaces, run the gated workflow, and produce byte-identical results — pausing only at the three explicitly marked human gates.

---

**End of OKF Lite Implementation Specification**

**Status**: Normative. This is the implementation contract. Conformance = OKF Lite compliance.

**Version**: 1.1 (2026-07-17)

**Next Action**: Execute ISSUE-001 (build vault_generate_ids.py).
