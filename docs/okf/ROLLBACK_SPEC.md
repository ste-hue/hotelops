# Rollback Specification — HotelOps OKF Lite

**Version**: 1.1 (audit & hardening pass)
**Date**: 2026-07-17
**Status**: Normative
**Scope**: All rollback and backup operations

---

## Purpose

Define the exact procedures for backup, rollback, and recovery.

**Rollback MUST restore vault to exact pre-migration state (byte-for-byte).**

---

## Backup Strategy

### Backup Format

**Type**: Filesystem copy (not archive, not diff).

**Rationale**: Instant restoration. No decompression. No diff application. Simple `cp -r`.

**Configuration (normative)**: `VAULT_DIR` and `BACKUP_ROOT` are **externally supplied** — CLI arguments or environment variables, per OKF_LITE_IMPLEMENTATION_SPEC.md § Configuration. This document never hardcodes them; every absolute path shown below is a **non-normative deployment example**.

```bash
# Externally supplied (CLI --vault / --backup-root, or env OKF_VAULT_DIR / OKF_BACKUP_ROOT)
VAULT_DIR="${OKF_VAULT_DIR:?must be supplied}"
BACKUP_ROOT="${OKF_BACKUP_ROOT:?must be supplied}"
# Derived, never independently configured:
BACKUP_DIR="$BACKUP_ROOT/$(date -u +%Y%m%d_%H%M%S)"
```

Non-normative deployment example (current machine):
```
OKF_VAULT_DIR   = /Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps
OKF_BACKUP_ROOT = /Users/stefanodellapietra/dev/Projects/obsidian/hotelops-backups
```

**Location constraint (normative)**: `BACKUP_ROOT` MUST be outside the Git repository that contains `VAULT_DIR` (in the example deployment the repo root is `Obsidian Vault/`, one level above HotelOps — a backup created next to HotelOps would be tracked by Git). Backups are timestamped — one directory per backup, never overwritten.

---

### Backup Algorithm

```bash
#!/bin/bash
set -euo pipefail

VAULT_DIR="${OKF_VAULT_DIR:?}"
BACKUP_ROOT="${OKF_BACKUP_ROOT:?}"
BACKUP_DIR="$BACKUP_ROOT/$(date -u +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_ROOT"

# Create backup (timestamped — never deletes or overwrites a previous backup)
cp -r "$VAULT_DIR" "$BACKUP_DIR"

echo "Backup created at $BACKUP_DIR"
```

**Verification (mandatory, at creation time)** — file count alone is too weak; checksums prove the copy is byte-faithful before any file is touched. **SHA-256 only** (portable: `shasum -a 256` exists on both macOS and Linux; macOS-only `md5 -r` and GNU-only `md5sum` are both non-normative and MUST NOT be used):
```bash
# Compare SHA-256 of ALL files (not just .md — the backup must restore everything)
(cd "$VAULT_DIR"  && find . -type f -print0 | sort -z | xargs -0 shasum -a 256) > /tmp/vault_sums.txt
(cd "$BACKUP_DIR" && find . -type f -print0 | sort -z | xargs -0 shasum -a 256) > /tmp/backup_sums.txt

if ! diff -q /tmp/vault_sums.txt /tmp/backup_sums.txt > /dev/null; then
    echo "ERROR: Backup verification failed (checksums differ)"
    exit 1
fi
echo "Backup verified (SHA-256 match)"
```

**Gate**: If backup verification fails → ABORT migration. No backup = no migration.

---

### Baseline Manifest

Written immediately after backup verification, by `vault_migrate.py --write-baseline <path>`. This is the **reference input for VAL-E-009** (body preservation) — the migrated file alone cannot prove its body is unchanged.

**Format**: JSON object, UTF-8, LF, keys sorted (deterministic). One entry per **in-scope** file (per the frozen scope predicate), keyed by path relative to `VAULT_DIR`:

```json
{
  "concepts/FINANCIAL_RULES.md": {
    "file_sha256": "9f2c…",
    "body_sha256": "1ab4…"
  },
  "decisions/2026-05-18_PF_Rotate_Design.md": {
    "file_sha256": "77e0…",
    "body_sha256": "c3d9…"
  }
}
```

- `file_sha256`: SHA-256 of the file's full bytes
- `body_sha256`: SHA-256 of the UTF-8 encoding of the extracted body (`extract_body` per MIGRATION_INVARIANTS.md INV-001)

**Consumers**: `vault_lint.py --baseline` (VAL-E-009), rollback verification (batch restore must reproduce `file_sha256` for every restored file), determinism audits.

---

### Backup Metadata

**Audit Log Entry**:
```json
{
  "timestamp": "2026-07-17T10:30:00Z",
  "action": "backup",
  "vault_dir": "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps",
  "backup_dir": "/Users/stefanodellapietra/dev/Projects/obsidian/hotelops-backups/<timestamp>",
  "file_count": 354,
  "total_size_bytes": 1234567,
  "git_commit": "abc123def456"
}
```

**Git Commit Hash**: Capture current HEAD for reference.

---

## Rollback Strategy

### Full Rollback (Entire Vault)

**When**: Critical failure (duplicate IDs, mass corruption, invariant violation).

**Algorithm**:
```bash
#!/bin/bash

VAULT_DIR="${OKF_VAULT_DIR:?}"
BACKUP_DIR="${1:?usage: rollback.sh <backup_dir>}"   # e.g. $OKF_BACKUP_ROOT/<timestamp>

# Verify backup exists
if [ ! -d "$BACKUP_DIR" ]; then
    echo "ERROR: No backup found at $BACKUP_DIR"
    exit 1
fi

# Remove current vault
rm -rf "$VAULT_DIR"

# Restore from backup
cp -r "$BACKUP_DIR" "$VAULT_DIR"

# Verify restoration
if [ ! -d "$VAULT_DIR" ]; then
    echo "ERROR: Rollback failed"
    exit 1
fi

echo "Rollback complete. Vault restored to backup state."
```

**Verification**:
```bash
# Compare SHA-256 (portable; ALL files, not just .md)
(cd "$VAULT_DIR"  && find . -type f -print0 | sort -z | xargs -0 shasum -a 256) > /tmp/vault_checksums.txt
(cd "$BACKUP_DIR" && find . -type f -print0 | sort -z | xargs -0 shasum -a 256) > /tmp/backup_checksums.txt

diff /tmp/vault_checksums.txt /tmp/backup_checksums.txt

if [ $? -ne 0 ]; then
    echo "ERROR: Rollback verification failed (checksums differ)"
    exit 1
fi

echo "Rollback verified. Vault matches backup."
```

---

### Per-File Restore (Internal Primitive)

**Role (normative)**: NOT an error-handling policy. Under the batch-atomic transaction model (OKF_LITE_IMPLEMENTATION_SPEC.md § Transaction Model), a single file's failure aborts and rolls back the ENTIRE batch. `rollback_file` is the internal primitive that batch rollback iterates over its members.

**Algorithm**:
```python
import shutil
import os

def rollback_file(filepath, backup_dir):
    """
    Rollback single file from backup.

    Args:
        filepath: Relative path from vault root (e.g., concepts/FINANCIAL_RULES.md)
        backup_dir: Path to backup directory
    """
    vault_root = os.environ['OKF_VAULT_DIR']   # externally supplied, never hardcoded
    backup_root = backup_dir

    # Construct paths
    vault_filepath = os.path.join(vault_root, filepath)
    backup_filepath = os.path.join(backup_root, filepath)

    # Verify backup file exists
    if not os.path.exists(backup_filepath):
        raise FileNotFoundError(f"Backup file not found: {backup_filepath}")

    # Restore from backup
    shutil.copy2(backup_filepath, vault_filepath)

    # Verify restoration
    if not os.path.exists(vault_filepath):
        raise RuntimeError(f"Rollback failed: {vault_filepath}")

    # Verify content matches
    with open(vault_filepath, 'rb') as f1, open(backup_filepath, 'rb') as f2:
        if f1.read() != f2.read():
            raise RuntimeError(f"Rollback verification failed: {vault_filepath}")

    print(f"Rolled back: {filepath}")
```

**Usage** (only ever called by batch rollback — never as a standalone recovery):
```python
def rollback_batch(batch_files, backup_dir):
    """Restore EVERY member of the failed batch. Batch-atomic."""
    for relpath in batch_files:
        rollback_file(relpath, backup_dir)
```

---

### Incremental Rollback (Staged Migration)

**Scenario**: Migrate Tier 1 → validate → migrate Tier 2 → validate. If Tier 2 fails, rollback only Tier 2.

**Algorithm**:
```python
def migrate_with_checkpoints(tiers, backup_dir):
    """
    Migrate in stages with rollback points.

    Args:
        tiers: List of (tier_name, file_list) tuples
        backup_dir: Path to backup directory

    Example:
        tiers = [
            ("Tier 1", tier1_files),
            ("Tier 2", tier2_files)
        ]
    """
    for tier_name, files in tiers:
        print(f"Migrating {tier_name} ({len(files)} files)...")

        # Checkpoint: snapshot current state
        checkpoint = create_checkpoint(files)

        # Migrate tier
        success = True
        for filepath in files:
            try:
                migrate_file(filepath, metadata)
            except Exception as e:
                log_error(f"Migration failed: {filepath}: {e}")
                success = False
                break

        # Validate tier
        if success:
            success = validate_tier(files)

        # Rollback tier if failed
        if not success:
            print(f"Rolling back {tier_name}...")
            rollback_checkpoint(checkpoint, backup_dir)
            raise MigrationError(f"{tier_name} migration failed")

        print(f"{tier_name} migration complete.")
```

**Checkpoint Format**:
```python
checkpoint = {
    "tier": "Tier 1",
    "files": ["concepts/FINANCIAL_RULES.md", "..."],
    "timestamp": "2026-07-17T10:30:00Z"
}
```

**Rollback Checkpoint**:
```python
def rollback_checkpoint(checkpoint, backup_dir):
    """Rollback all files in checkpoint."""
    for filepath in checkpoint['files']:
        rollback_file(filepath, backup_dir)
```

---

## Rollback Triggers

### Automatic Rollback

**Triggers**:
1. **VAL-E-009**: Body modified (INV-001 violation)
2. **VAL-E-007**: Duplicate IDs detected
3. **File write error**: Permission denied, disk full, etc.
4. **Validation failure**: Any MANDATORY validation fails post-migration

**Behavior**: Immediate rollback. No user confirmation needed.

---

### Manual Rollback

**Triggers**:
1. User requests rollback (pilot review, dissatisfaction)
2. Discovered issue post-migration (data loss, corruption)

**Command**:
```bash
python vault_migrate.py --rollback
```

**Behavior**: Restore from latest backup. Prompt for confirmation.

---

## Verification

### Post-Rollback Verification

**Algorithm**:
```python
def verify_rollback(vault_dir, backup_dir):
    """
    Verify vault matches backup after rollback.

    Returns:
        (is_valid, differences)
    """
    differences = []

    # Compare file lists
    vault_files = get_md_files(vault_dir)
    backup_files = get_md_files(backup_dir)

    if vault_files != backup_files:
        differences.append("File list mismatch")

    # Compare file contents
    for filepath in vault_files:
        vault_filepath = os.path.join(vault_dir, filepath)
        backup_filepath = os.path.join(backup_dir, filepath)

        with open(vault_filepath, 'rb') as f1, open(backup_filepath, 'rb') as f2:
            if f1.read() != f2.read():
                differences.append(f"Content mismatch: {filepath}")

    is_valid = len(differences) == 0

    return (is_valid, differences)
```

**Failure Behavior**:
```python
is_valid, diffs = verify_rollback(vault_dir, backup_dir)

if not is_valid:
    print("ERROR: Rollback verification failed")
    for diff in diffs:
        print(f"  - {diff}")
    sys.exit(1)
```

**Critical**: If rollback verification fails, backup/restore mechanism is broken. Manual intervention required.

---

## Audit Log

### Rollback Log Entry

```json
{
  "timestamp": "2026-07-17T10:35:00Z",
  "action": "rollback",
  "scope": "full|partial|tier",
  "vault_dir": "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps",
  "backup_dir": "/Users/stefanodellapietra/dev/Projects/obsidian/hotelops-backups/<timestamp>",
  "trigger": "validation_error|user_request|automatic",
  "files_rolled_back": 239,
  "reason": "Duplicate IDs detected (VAL-E-007)",
  "verification": "passed|failed",
  "duration_ms": 1234
}
```

**Log File**: `vault_migration.log` (append-only, JSON Lines format)

---

## Recovery Scenarios

### Scenario 1: Pilot Fails Validation

**Situation**: Pilot batch running. 1 of the 4 files fails VAL-E-009 (body modified).

**Action** (batch-atomic):
1. Batch aborts automatically → ALL 4 pilot files restored from backup
2. Log incident
3. Fix migration script
4. Re-run the whole pilot batch
5. Validate again

**Command** (automatic on failure; manual equivalent):
```bash
python vault_migrate.py --rollback --batch pilot
```

---

### Scenario 2: Tier 1 Complete, Tier 2 Fails

**Situation**: 74 Tier 1 files migrated successfully. 165 Tier 2 files started. 1 file fails.

**Action**:
1. Rollback all Tier 2 files (checkpoint restore)
2. Preserve Tier 1 (already validated)
3. Fix issue
4. Re-run Tier 2 migration

**Command**:
```bash
python vault_migrate.py --rollback-tier "Tier 2"
```

---

### Scenario 3: Mass Migration Complete, Duplicate IDs Found

**Situation**: All 239 files migrated. VAL-E-007 detects 2 duplicate IDs.

**Action**:
1. Rollback entire vault (full restore)
2. Identify collision (manual review)
3. Resolve (rename file or merge docs)
4. Re-run migration

**Command**:
```bash
python vault_migrate.py --rollback
```

---

### Scenario 4: User Requests Rollback (Post-Review)

**Situation**: Migration complete. User reviews vault, dissatisfied with results.

**Action**:
1. Rollback entire vault
2. Collect feedback
3. Adjust architecture/implementation
4. Re-run migration

**Command**:
```bash
python vault_migrate.py --rollback --confirm
```

**Prompt**:
```
WARNING: This will restore vault to pre-migration state.
All OKF metadata will be removed.
Continue? [y/N]:
```

---

### Scenario 5: Backup Lost or Corrupted

**Situation**: Rollback requested, but backup directory missing or corrupted.

**Action**:
1. Check Git history (vault is under version control)
2. `git reset --hard <pre-migration-commit>`
3. If Git unavailable → manual recovery from user's local copy

**Prevention**: ALWAYS verify backup after creation. Commit pre-migration state to Git.

---

## Backup Retention

### Retention Policy (normative — resolved 2026-07-17, gate c)

**Single policy**: keep every backup for **at least 7 days after the post-migration validation passes**. Cleanup is **always manual** — no script ever deletes a backup automatically (an automated cleanup that misjudges "validated" destroys the only rollback path).

```bash
# Manual, after >=7 days from validated migration (non-normative example paths)
find "$OKF_BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +7 -print
# review the list, then delete explicitly:  rm -rf "$OKF_BACKUP_ROOT/<timestamp>"
```

(v1.0 offered two contradictory policies — delete-after-validation vs 7-day hold; the 7-day hold wins: disk is cheap, backups are timestamped and outside the repo, and Obsidian/Git give no second safety net for non-committed edits.)

---

### Multiple Backups (Incremental)

**Scenario**: Long migration with multiple stages.

**Strategy**: Create timestamped backups per stage.

```bash
BACKUP_DIR="/Users/stefanodellapietra/dev/Projects/obsidian/hotelops-backups/$(date +%Y%m%d_%H%M%S)"
cp -r "$VAULT_DIR" "$BACKUP_DIR"
```

**Example**:
```
obsidian-hotelops.backup.20260717_100000  # Pre-migration
obsidian-hotelops.backup.20260717_103000  # Post-Tier-1
obsidian-hotelops.backup.20260717_110000  # Post-Tier-2
```

**Rollback**: Select appropriate backup timestamp.

---

## Git Integration

### Pre-Migration Commit

**Recommendation**: Commit vault state before migration.

```bash
cd "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps"
git add .
git commit -m "Pre-migration checkpoint: OKF Lite implementation"
```

**Benefit**: Git history serves as backup. Rollback via `git reset`.

---

### Post-Migration Commit

**After Validation**:
```bash
git add .
git commit -m "OKF Lite migration complete (239 files)"
```

**Benefit**: Migration is tracked in version control.

---

### Rollback via Git

**Alternative to filesystem backup**:
```bash
# Find pre-migration commit
git log --oneline | grep "Pre-migration"

# Rollback
git reset --hard <commit-hash>
```

**Advantage**: No separate backup directory needed.

**Disadvantage**: Requires vault under Git control. Not all vaults are.

---

## Disaster Recovery

### Scenario: Backup AND Git Lost

**Situation**: Backup deleted, Git history corrupted.

**Recovery**:
1. Check Obsidian Sync (if enabled)
2. Check cloud backup (Google Drive, Dropbox)
3. Check user's local machine (vault may be synced)
4. Worst case: Reconstruct from memory + BQ data

**Prevention**: ALWAYS have multiple backup sources.

---

## Testing Rollback

### Test Procedure

**Before Production**:
1. Create test vault (copy of production)
2. Run migration
3. Deliberately corrupt file (break INV-001)
4. Verify automatic rollback
5. Run full rollback
6. Verify byte-for-byte match

**Test Script**:
```python
def test_rollback():
    """Test rollback mechanism."""
    # Setup
    test_vault = "/tmp/test_vault"
    shutil.copytree("/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps", test_vault)

    # Backup
    backup_dir = f"{test_vault}.backup"
    shutil.copytree(test_vault, backup_dir)

    # Corrupt file
    corrupt_file(f"{test_vault}/concepts/test.md")

    # Rollback
    rollback_full(test_vault, backup_dir)

    # Verify
    assert verify_rollback(test_vault, backup_dir)

    print("Rollback test PASSED")
```

---

## CLI Interface

```bash
# Full rollback
python vault_migrate.py --rollback

# Rollback specific file
python vault_migrate.py --rollback-file concepts/FINANCIAL_RULES.md

# Rollback tier
python vault_migrate.py --rollback-tier "Tier 2"

# Verify backup
python vault_migrate.py --verify-backup

# List backups
python vault_migrate.py --list-backups

# Cleanup old backups
python vault_migrate.py --cleanup-backups --older-than 7
```

---

## Error Handling

### Backup Creation Fails

**Error**: Disk full, permission denied, backup directory unwritable.

**Behavior**: ABORT migration. Do not proceed without backup.

**Message**:
```
ERROR: Backup creation failed
  Reason: {error_message}
  Action: Ensure sufficient disk space and write permissions
  Migration aborted.
```

---

### Rollback Fails

**Error**: Backup directory missing, corrupted, or files differ.

**Behavior**: ALERT user immediately. Escalate to manual recovery.

**Message**:
```
CRITICAL ERROR: Rollback failed
  Reason: {error_message}
  Action: Manual recovery required
  1. Check backup directory: {backup_dir}
  2. Restore from Git: git reset --hard <commit>
  3. Contact support if unable to recover
```

---

### Verification Fails Post-Rollback

**Error**: After rollback, vault != backup (checksums differ).

**Behavior**: CRITICAL ALERT. Rollback mechanism broken.

**Message**:
```
CRITICAL ERROR: Rollback verification failed
  Vault and backup differ after rollback
  This indicates a critical bug in rollback mechanism
  Action: Do NOT proceed. Investigate immediately.
  Differences:
    {list_of_differences}
```

---

**End of Rollback Specification**

**Status**: Normative. Rollback MUST restore vault byte-for-byte. Verification MUST pass.
