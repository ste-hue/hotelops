# Automation Contracts — HotelOps OKF Lite

**Version**: 1.1 (audit & hardening pass)
**Date**: 2026-07-17
**Status**: Normative
**Scope**: All automation scripts for OKF Lite migration

---

## Purpose

Define the exact interface contracts for all automation scripts.

**Scripts MUST conform to these specifications.**

---

## Script Inventory

| Script | Baseline ref | Purpose | Priority | Dependencies |
|--------|--------------|---------|----------|--------------|
| `vault_generate_ids.py` | AUTO-001 | Generate stable IDs | P0 (Blocker) | Classification rules |
| `vault_lint.py` | AUTO-002 | Validate OKF compliance | P0 (Blocker) | None |
| `vault_extract_wikilinks.py` | AUTO-004 | Extract wikilinks to references | P1 (Post-pilot) | vault_generate_ids.py |
| `vault_enrich_metadata.py` | AUTO-003 | Add Git-derived metadata | P2 (Optional) | Git history |
| `vault_migrate.py` | — (orchestrator) | Orchestrate full migration | P0 (Blocker) | vault_generate_ids.py + vault_lint.py ONLY (MVP MUST NOT depend on the deferred P1/P2 scripts) |

**Type source (normative)**: `vault_generate_ids.py` and `vault_migrate.py` need each file's `type` to build IDs and frontmatter. The type is resolved in this order:
1. Existing frontmatter `type:` if present and a valid enum value → use it
2. Existing frontmatter `type:` present but invalid → Type Normalization Table (OKF_LITE_IMPLEMENTATION_SPEC.md § File Classification Rules); unknown legacy value → FM-E-007, human review
3. No frontmatter / no `type:` → path-based classification (same section: directory mapping + root-file table)

Scripts MUST NOT invent types by any other means (no content sniffing, no LLM inference).

---

## AUTO-001: vault_generate_ids.py

### Purpose

Generate stable IDs for all markdown files and add to frontmatter.

---

### Inputs

**CLI Arguments**:
```bash
python vault_generate_ids.py [OPTIONS]

Options:
  --vault PATH          Vault root (REQUIRED; or env OKF_VAULT_DIR — never a built-in default)
  --file PATH           Process single file (relative to vault)
  --tier TIER           Process specific tier: 1 | 2 (Lite scope has exactly two tiers;
                        membership defined in OKF_LITE_IMPLEMENTATION_SPEC.md § File Classification Rules)
  --all                 Process all files
  --dry-run             Preview changes without writing
  --check-collisions    Check for ID collisions only
  --validate            Validate existing IDs only
  --force-regenerate    Regenerate IDs even if exist (DANGEROUS)
  --output FORMAT       Output format: text|json (default: text)
  --log FILE            Log file path (default: vault_generate_ids.log)
  --help                Show help
```

**Examples**:
```bash
# Dry-run all files
python vault_generate_ids.py --all --dry-run

# Process single file
python vault_generate_ids.py --file concepts/FINANCIAL_RULES.md

# Process Tier 1
python vault_generate_ids.py --tier 1

# Check collisions
python vault_generate_ids.py --check-collisions

# Validate existing IDs
python vault_generate_ids.py --validate
```

---

### Outputs

**Standard Output** (text format):
```
vault_generate_ids.py v1.0
Vault: /Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps
Mode: dry-run

Processing 239 files...

[GENERATE] concepts/FINANCIAL_RULES.md
  Type: concept
  Generated ID: concept:financial-rules
  Action: Add to frontmatter

[SKIP] decisions/2026-05-18_PF_Rotate_Design.md
  Reason: ID already exists (decision:2026-05-18-pf-rotate-design)

[COLLISION] loop:financial-rules
  Files:
    - loops/financial_rules.md
    - archive/FINANCIAL_RULES.md

Summary:
  Files processed: 239
  IDs generated: 235
  IDs skipped: 3 (already exist)
  Collisions detected: 1
  Errors: 0

Status: DRY-RUN (no files modified)
```

**Standard Output** (JSON format):
```json
{
  "version": "1.0",
  "vault": "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps",
  "mode": "dry-run",
  "timestamp": "2026-07-17T10:30:00Z",
  "summary": {
    "files_processed": 239,
    "ids_generated": 235,
    "ids_skipped": 3,
    "collisions": 1,
    "errors": 0
  },
  "actions": [
    {
      "file": "concepts/FINANCIAL_RULES.md",
      "type": "concept",
      "generated_id": "concept:financial-rules",
      "action": "generate"
    },
    {
      "file": "decisions/2026-05-18_PF_Rotate_Design.md",
      "action": "skip",
      "reason": "id_exists"
    }
  ],
  "collisions": [
    {
      "id": "loop:financial-rules",
      "files": [
        "loops/financial_rules.md",
        "archive/FINANCIAL_RULES.md"
      ]
    }
  ],
  "status": "dry-run"
}
```

**Log File** (JSON Lines):
```json
{"timestamp": "2026-07-17T10:30:00Z", "level": "INFO", "message": "Starting ID generation", "vault": "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps", "mode": "dry-run"}
{"timestamp": "2026-07-17T10:30:01Z", "level": "INFO", "file": "concepts/FINANCIAL_RULES.md", "action": "generate", "id": "concept:financial-rules"}
{"timestamp": "2026-07-17T10:30:02Z", "level": "WARN", "message": "Collision detected", "id": "loop:financial-rules", "files": ["loops/financial_rules.md", "archive/FINANCIAL_RULES.md"]}
{"timestamp": "2026-07-17T10:30:05Z", "level": "INFO", "message": "ID generation complete", "summary": {"files_processed": 239, "ids_generated": 235}}
```

---

### Exit Codes

- `0`: Success (all IDs generated or validated)
- `1`: Error (collision detected, file write error, invalid input)
- `2`: Warning (some files skipped, non-critical issues)

---

### Error Behavior

**Collision Detected**:
```python
if collisions:
    print(f"ERROR: {len(collisions)} ID collision(s) detected")
    for id, files in collisions.items():
        print(f"  {id}: {', '.join(files)}")
    sys.exit(1)
```

**File Write Error**:
```python
try:
    merge_frontmatter(filepath, {'id': generated_id})
except IOError as e:
    log_error(f"File write error: {filepath}: {e}")
    sys.exit(1)
```

**Invalid Type** (not resolvable via the Type Normalization Table):
```python
if resolved_type is None:   # FM-E-007
    log_error(f"Unresolvable type in {filepath} (FM-E-007)")
    if dry_run:
        continue        # inventory mode: flag for human review, keep scanning
    raise BatchAbort    # live batch: abort -> entire batch rolled back
```

---

### Logging

**Log Levels**:
- `DEBUG`: Detailed processing steps
- `INFO`: Normal operations (file processed, ID generated)
- `WARN`: Non-critical issues (collision, skip)
- `ERROR`: Critical failures (write error, invalid input)

**Log Format**: JSON Lines (machine-readable)

**Log Rotation**: Not required (short-lived script)

---

### Dry-Run Behavior

**When `--dry-run`**:
- Read all files
- Parse frontmatter
- Generate IDs
- Detect collisions
- **Do NOT write** any files
- Print preview of changes
- Exit 0 (success) even if collisions (preview mode)

**Purpose**: Safe preview before applying changes.

---

### Expected Side Effects

**With `--dry-run`**: None (read-only)

**Without `--dry-run`**:
- Modify frontmatter (add `id:` field)
- Create log file
- No file moves, renames, or deletions

---

### Idempotence

**Behavior**: Running script multiple times produces same result.

**Implementation** (existing IDs are preserved only if valid + type-consistent
+ unique — FM-E-008 otherwise; see FRONTMATTER_MERGE_SPEC §4.5):
```python
if 'id' in frontmatter:
    if id_preservable(frontmatter['id'], resolved_type, registry):
        log_info(f"Skipping {filepath}: valid ID already exists")
        continue          # preserve, don't regenerate
    log_error(f"Unpreservable ID in {filepath} (FM-E-008)")
    # dry-run: flag for human review; live batch: abort batch
```

**Exception**: `--force-regenerate` flag (dangerous, requires confirmation).

---

### Performance

**Expected**: 239 files in < 10 seconds.

**Optimization**: Batch file reads, parallel processing (optional).

---

## AUTO-002: vault_lint.py

### Purpose

Validate OKF Lite compliance for all files.

---

### Inputs

**CLI Arguments**:
```bash
python vault_lint.py [OPTIONS]

Options:
  --vault PATH       Vault root (REQUIRED; or env OKF_VAULT_DIR — never a built-in default)
  --file PATH        Lint single file (relative to vault)
  --tier TIER        Lint specific tier: 1 | 2
  --all              Lint all files
  --level LEVEL      Validation level: mandatory|recommended|informational (default: recommended)
  --profile PROFILE  Phase profile: pre|post|vault (default: post; see VALIDATION_SPEC § Validation Profiles)
  --baseline PATH    SHA-256 baseline manifest (required for VAL-E-009; skipped with INFO if absent)
  --strict           Treat warnings as errors (exit 1 on warnings)
  --format FORMAT    Output format: text|json (default: text)
  --fix              Auto-fix errors (if possible)
  --log FILE         Log file path (default: vault_lint.log)
  --help             Show help
```

**Examples**:
```bash
# Lint all files (errors + warnings)
python vault_lint.py --all

# Lint errors only
python vault_lint.py --all --level mandatory

# Lint with strict mode (warnings = errors)
python vault_lint.py --all --strict

# Lint single file
python vault_lint.py --file concepts/FINANCIAL_RULES.md

# Lint and auto-fix
python vault_lint.py --all --fix
```

---

### Outputs

**Standard Output** (text format):
```
vault_lint.py v1.0
Vault: /Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps
Level: recommended

Linting 239 files...

[PASS] concepts/FINANCIAL_RULES.md
[ERROR] concepts/orphan.md
  [VAL-E-002] Missing required field 'type'
[WARN] loops/draft.md
  [VAL-W-005] Missing operational fields (owner, cadence)

Summary:
  Files linted: 239
  PASS: 235
  ERRORS: 2
  WARNINGS: 15
  INFO: 42

Errors:
  [VAL-E-002] 1 file missing 'type'
  [VAL-E-006] 1 file with ID type mismatch

Warnings:
  [VAL-W-001] 15 files missing 'authority'
  [VAL-W-005] 1 file missing operational fields

Status: FAILED (2 errors)
```

**Standard Output** (JSON format):
```json
{
  "version": "1.0",
  "vault": "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps",
  "level": "recommended",
  "timestamp": "2026-07-17T10:30:00Z",
  "summary": {
    "files_linted": 239,
    "pass": 235,
    "errors": 2,
    "warnings": 15,
    "info": 42
  },
  "results": [
    {
      "file": "concepts/FINANCIAL_RULES.md",
      "status": "pass",
      "errors": [],
      "warnings": [],
      "info": []
    },
    {
      "file": "concepts/orphan.md",
      "status": "error",
      "errors": [
        {"code": "VAL-E-002", "message": "Missing required field 'type'"}
      ]
    }
  ],
  "status": "failed"
}
```

---

### Exit Codes

- `0`: Success (no errors, warnings OK)
- `1`: Errors (mandatory validation failed)
- `2`: Warnings (if `--strict` enabled)

---

### Error Behavior

**Validation Error**:
```python
if errors_found:
    print(f"ERROR: {len(errors_found)} validation error(s)")
    sys.exit(1)
```

**Auto-Fix** (if `--fix`):
```python
if args.fix and error.fixable:
    fix_error(filepath, error)
    log_info(f"Fixed {error.code} in {filepath}")
```

**Fixable Errors**:
- `VAL-E-011`: Line endings (normalize to Unix)
- Others: Not auto-fixable (require manual intervention)

---

### Logging

**Same format as AUTO-001** (JSON Lines).

---

### Expected Side Effects

**Without `--fix`**: None (read-only)

**With `--fix`**:
- Normalize line endings (if VAL-E-011)
- No other modifications

---

## AUTO-004: vault_extract_wikilinks.py

> **Numbering note**: baseline numbering (CORE_VS_LITE_MATRIX, HOTELOPS_OKF_LITE_PROFILE) assigns **AUTO-004** to the wikilink extractor and **AUTO-003** to Git enrichment. v1.0 of this document swapped them; corrected here.

### Purpose

Extract wikilinks from markdown body and populate `references:` field.

---

### Inputs

**CLI Arguments**:
```bash
python vault_extract_wikilinks.py [OPTIONS]

Options:
  --vault PATH       Vault root (REQUIRED; or env OKF_VAULT_DIR)
  --file PATH        Process single file
  --all              Process all files with wikilinks
  --dry-run          Preview without writing
  --output FORMAT    Output format: text|json
  --log FILE         Log file path
  --help             Show help
```

---

### Outputs

**Standard Output**:
```
vault_extract_wikilinks.py v1.0

Processing 22 files with wikilinks...

[EXTRACT] concepts/FINANCIAL_RULES.md
  Found 3 wikilinks: [[IDENTITY]], [[KERNEL]], [[CASSA_VS_COMPETENZA]]
  Resolved IDs:
    - constitutional:identity
    - constitutional:kernel
    - concept:cassa-vs-competenza-sources
  Action: Add references: [constitutional:identity, constitutional:kernel, concept:cassa-vs-competenza-sources]

[SKIP] sessions/2026-06-04_esolver_p0.md
  Reason: references field already exists

Summary:
  Files processed: 22
  Wikilinks extracted: 18
  Skipped: 4 (references already exist)
  Unresolved wikilinks: 0

Status: SUCCESS
```

---

### Exit Codes

- `0`: Success
- `1`: Error (unresolved wikilink, file write error)
- `2`: Warning (some wikilinks unresolved)

---

### Error Behavior

**Unresolved Wikilink**:
```python
if not resolve_wikilink_to_id(wikilink):
    log_warn(f"Unresolved wikilink: [[{wikilink}]] in {filepath}")
    # Continue, add placeholder or skip
```

---

### Expected Side Effects

**With `--dry-run`**: None

**Without `--dry-run`**:
- Add `references:` field to frontmatter
- Preserve existing `references` if present (merge, don't replace)

---

## AUTO-003: vault_enrich_metadata.py

### Purpose

Backfill `created` and `last_updated` from Git history.

---

### Inputs

**CLI Arguments**:
```bash
python vault_enrich_metadata.py [OPTIONS]

Options:
  --vault PATH       Vault root (REQUIRED; or env OKF_VAULT_DIR)
  --file PATH        Process single file
  --all              Process all files
  --dry-run          Preview without writing
  --git-dir PATH     Path to .git directory (default: auto-detect)
  --output FORMAT    Output format: text|json
  --log FILE         Log file path
  --help             Show help
```

---

### Outputs

**Standard Output**:
```
vault_enrich_metadata.py v1.0

Processing 239 files...

[ENRICH] concepts/FINANCIAL_RULES.md
  created: 2026-04-20 (from Git: first commit)
  last_updated: 2026-07-12 (from Git: last commit)

[SKIP] decisions/2026-05-18_PF_Rotate_Design.md
  Reason: created and last_updated already exist

Summary:
  Files processed: 239
  Enriched: 180
  Skipped: 59 (metadata already exists)

Status: SUCCESS
```

---

### Exit Codes

- `0`: Success
- `1`: Error (Git not available, file write error)

---

### Error Behavior

**Git Not Available**:
```python
if not is_git_repo(vault_dir):
    log_error("Git repository not found")
    sys.exit(1)
```

---

### Expected Side Effects

- Add `created:` and `last_updated:` to frontmatter
- No modification if fields already exist

---

## ORCH-001: vault_migrate.py

> **Numbering note**: the orchestrator has no AUTO number — baseline AUTO-005 is the (deferred) bidirectional consistency checker.

### Purpose

Orchestrate full OKF Lite migration.

---

### Inputs

**CLI Arguments**:
```bash
python vault_migrate.py [OPTIONS]

Options:
  --vault PATH           Vault root (REQUIRED; or env OKF_VAULT_DIR)
  --backup-root PATH     Backup area (REQUIRED; or env OKF_BACKUP_ROOT; must be
                         outside the Git repo containing the vault). Backups land in
                         $BACKUP_ROOT/<UTC-timestamp>/
  --write-baseline PATH  Write the SHA-256 baseline manifest (file + body hashes
                         of all in-scope files) — reference input for VAL-E-009
  --tier TIER            Migrate specific tier: 1 | 2
  --all                  Migrate all files
  --pilot                Run pilot only (4 files)
  --rollback             Rollback to backup (full vault)
  --rollback --batch B   Rollback one batch (pilot | tier1 | tier2) — the normal
                         failure path; per-file rollback is an internal primitive only
  --dry-run              Preview migration
  --output FORMAT        Output format: text|json
  --log FILE             Log file path
  --help                 Show help
```

**Examples**:
```bash
# Run pilot
python vault_migrate.py --pilot

# Migrate Tier 1
python vault_migrate.py --tier 1

# Migrate all (with backup)
python vault_migrate.py --all

# Rollback
python vault_migrate.py --rollback
```

---

### Outputs

**Standard Output**:
```
vault_migrate.py v1.0

Step 1: Backup
  Creating backup at /Users/stefanodellapietra/dev/Projects/obsidian/hotelops-backups/<timestamp>...
  Backup complete (354 files, 1.2 MB)

Step 2: Generate IDs
  Running vault_generate_ids.py --all...
  Generated 235 IDs, 3 skipped, 0 collisions

Step 3: Validate Pre-Migration
  Running vault_lint.py --all --profile pre...
  PASS (0 errors)

Step 4: Migrate Frontmatter
  Processing 239 files...
  Modified: 235
  Skipped: 4 (already compliant)

Step 5: Validate Post-Migration
  Running vault_lint.py --all...
  PASS (0 errors, 15 warnings)

Step 6: Verify Invariants
  Checking body preservation...
  PASS (239/239 files)

Summary:
  Files migrated: 239
  Errors: 0
  Warnings: 15
  Duration: 45 seconds

Status: SUCCESS
```

---

### Exit Codes

- `0`: Success
- `1`: Error (migration failed, validation failed)

---

### Error Behavior

**Validation Failure**:
```python
if validation_failed:
    log_error("Post-migration validation failed")
    rollback_all()
    sys.exit(1)
```

---

### Expected Side Effects

- Create backup directory
- Modify frontmatter (all files)
- Create log file

---

### Safety Invariant (normative)

`vault_migrate.py` exposes **no option to bypass backup or validation** — by design, not by omission. Backup + verification + baseline manifest ALWAYS run before any write; POST/VAULT validation ALWAYS runs after. Development iterations run against a **scratch copy** of the vault (`cp -r "$VAULT_DIR" /tmp/scratch`), never against the real vault with reduced safety. Implementations MUST NOT add bypass flags.

---

### Execution Sequence

**Full Migration** (batch-atomic; MVP uses only vault_generate_ids.py + vault_lint.py):
1. Backup vault (full tree, SHA-256 verified) + write baseline manifest (`--write-baseline`)
2. Validate pre-migration (`vault_lint.py --profile pre` — NOT the full mandatory set,
   which cannot pass on an un-migrated vault)
3. Freeze scope inventory (dry-run, human-reviewed `okf_scope_inventory.json`)
4. Migrate frontmatter per batch (add type, id, authority — FRONTMATTER_MERGE_SPEC)
5. Validate post-migration per file (`vault_lint.py --baseline <manifest>`) and
   vault-wide (`--profile vault`); any failure -> rollback the whole batch
6. Commit the sealed batch to Git before the next batch
7. Wikilink extraction / Git enrichment: NOT part of this sequence (deferred P1/P2)

**Rollback**:
1. Verify backup exists
2. Restore from backup
3. Verify restoration (checksums)

---

## Common Patterns

### Logging

**All scripts MUST log to JSON Lines format**:
```python
import json
import sys
from datetime import datetime

def log(level, message, **kwargs):
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": level,
        "message": message,
        **kwargs
    }
    print(json.dumps(entry), file=sys.stderr)
```

---

### Error Handling

**All scripts MUST handle errors gracefully**:
```python
try:
    process_file(filepath)
except FileNotFoundError:
    log("ERROR", f"File not found: {filepath}")
    sys.exit(1)
except Exception as e:
    log("ERROR", f"Unexpected error: {e}")
    sys.exit(1)
```

---

### Progress Reporting

**All scripts MUST report progress for long operations**:
```python
for i, filepath in enumerate(files):
    print(f"Processing {i+1}/{len(files)}: {filepath}")
    process_file(filepath)
```

---

### Dry-Run Mode

**All scripts MUST support `--dry-run`**:
```python
if args.dry_run:
    print("DRY-RUN: Would modify {filepath}")
else:
    modify_file(filepath)
```

---

**End of Automation Contracts**

**Status**: Normative. All automation scripts MUST conform to these interfaces.
