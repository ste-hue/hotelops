# Migration Invariants — HotelOps OKF Lite

**Version**: 1.1 (audit & hardening pass)
**Date**: 2026-07-17
**Status**: Normative
**Scope**: All vault migration operations

---

## Purpose

This document defines **immutable constraints** that MUST hold true before, during, and after any OKF Lite migration operation.

**Violation of any invariant = migration failure.**

---

## Invariant Categories

1. **Content Preservation** — markdown body unchanged
2. **Structure Preservation** — document structure unchanged
3. **Metadata Safety** — frontmatter merged, never replaced
4. **Determinism** — identical inputs → identical outputs
5. **Reversibility** — restore to exact pre-migration state
6. **Filesystem Stability** — no moves, renames, or deletions

---

## INV-001: Markdown Body Preservation

**Statement**: The markdown body (all content below frontmatter) MUST remain byte-identical after migration.

**Rationale**: Migration annotates metadata, never modifies content. Content changes require human review.

**Definition**: Markdown body = all bytes after closing `---` of frontmatter fence (or entire file if no frontmatter).

**Validation Method**:
```python
def validate_body_preservation(original_path, migrated_path):
    orig_body = extract_body(original_path)
    migr_body = extract_body(migrated_path)
    assert orig_body == migr_body, f"Body modified in {original_path}"
```

**Extraction Algorithm**:
```python
def extract_body(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # No frontmatter → entire file is body
    if not content.startswith('---\n'):
        return content

    # Find closing fence
    lines = content.split('\n')
    closing_fence_idx = None
    for i in range(1, len(lines)):
        if lines[i] == '---':
            closing_fence_idx = i
            break

    if closing_fence_idx is None:
        # Malformed frontmatter → treat as body
        return content

    # Body = everything after closing fence
    body_lines = lines[closing_fence_idx + 1:]
    return '\n'.join(body_lines)
```

**Rollback Condition**: If `orig_body != migr_body`, rollback file immediately.

**Test Cases**:
- File with no frontmatter → body = entire file
- File with frontmatter → body = content after `---`
- File with malformed frontmatter → body = entire file (fail-safe for the *validator* only; the migration itself never writes such files — it skips them with FM-E-004/FM-E-005 per FRONTMATTER_MERGE_SPEC.md)
- File whose `---` block is NOT at byte 0 (e.g., below an H1, like `concepts/FINANCIAL_RULES.md`) → that block is body, preserved byte-identical

---

## INV-002: Heading Hierarchy Preservation

**Statement**: All markdown headings (`#`, `##`, etc.) and their nesting levels MUST remain unchanged.

**Rationale**: Headings define document structure. Changes break Obsidian navigation, TOC, internal links.

**Validation Method**:
```python
def validate_headings(original_path, migrated_path):
    orig_headings = extract_headings(original_path)
    migr_headings = extract_headings(migrated_path)
    assert orig_headings == migr_headings, f"Headings modified in {original_path}"

def extract_headings(filepath):
    body = extract_body(filepath)
    headings = []
    for line in body.split('\n'):
        if line.startswith('#'):
            # Extract level and text
            match = re.match(r'^(#+)\s+(.*)', line)
            if match:
                level = len(match.group(1))
                text = match.group(2)
                headings.append((level, text))
    return headings
```

**Rollback Condition**: If heading structure differs, rollback.

---

## INV-003: Code Block Preservation

**Statement**: All fenced code blocks (` ``` `) MUST remain byte-identical, including:
- Opening fence (` ```language `)
- Code content
- Closing fence (` ``` `)

**Rationale**: Code blocks contain executable code, queries, examples. Any modification breaks functionality.

**Validation Method**:
```python
def validate_code_blocks(original_path, migrated_path):
    orig_blocks = extract_code_blocks(original_path)
    migr_blocks = extract_code_blocks(migrated_path)
    assert orig_blocks == migr_blocks, f"Code blocks modified in {original_path}"

def extract_code_blocks(filepath):
    body = extract_body(filepath)
    blocks = []
    in_block = False
    current_block = []

    for line in body.split('\n'):
        if line.startswith('```'):
            if in_block:
                # Closing fence
                current_block.append(line)
                blocks.append('\n'.join(current_block))
                current_block = []
                in_block = False
            else:
                # Opening fence
                current_block.append(line)
                in_block = True
        elif in_block:
            current_block.append(line)

    return blocks
```

**Rollback Condition**: If any code block differs, rollback.

---

## INV-004: Table Preservation

**Statement**: All markdown tables MUST remain byte-identical.

**Rationale**: Tables contain structured data. Modification breaks readability, queries.

**Validation Method**:
```python
def validate_tables(original_path, migrated_path):
    orig_tables = extract_tables(original_path)
    migr_tables = extract_tables(migrated_path)
    assert orig_tables == migr_tables, f"Tables modified in {original_path}"

def extract_tables(filepath):
    body = extract_body(filepath)
    tables = []
    in_table = False
    current_table = []

    for line in body.split('\n'):
        # Table row: starts with |
        if line.strip().startswith('|'):
            if not in_table:
                in_table = True
            current_table.append(line)
        else:
            if in_table:
                # End of table
                tables.append('\n'.join(current_table))
                current_table = []
                in_table = False

    # Handle table at EOF
    if current_table:
        tables.append('\n'.join(current_table))

    return tables
```

**Rollback Condition**: If any table differs, rollback.

---

## INV-005: Wikilink Preservation

**Statement**: All wikilinks (`[[...]]`) MUST remain byte-identical.

**Rationale**: Wikilinks are Obsidian cross-references. Modification breaks navigation.

**Validation Method**:
```python
def validate_wikilinks(original_path, migrated_path):
    orig_wikilinks = extract_wikilinks(original_path)
    migr_wikilinks = extract_wikilinks(migrated_path)
    assert orig_wikilinks == migr_wikilinks, f"Wikilinks modified in {original_path}"

def extract_wikilinks(filepath):
    body = extract_body(filepath)
    # Match [[anything]]
    pattern = r'\[\[([^\]]+)\]\]'
    return re.findall(pattern, body)
```

**Rollback Condition**: If wikilink count or content differs, rollback.

---

## INV-006: Dataview Preservation

**Statement**: All Dataview queries (` ```dataview ` blocks) MUST remain byte-identical.

**Rationale**: Dataview queries are executable. Modification breaks dynamic content generation.

**Validation Method**:
```python
def validate_dataview(original_path, migrated_path):
    orig_dataview = extract_dataview_queries(original_path)
    migr_dataview = extract_dataview_queries(migrated_path)
    assert orig_dataview == migr_dataview, f"Dataview queries modified in {original_path}"

def extract_dataview_queries(filepath):
    body = extract_body(filepath)
    queries = []
    in_dataview = False
    current_query = []

    for line in body.split('\n'):
        if line.startswith('```dataview'):
            in_dataview = True
            current_query.append(line)
        elif line.startswith('```') and in_dataview:
            current_query.append(line)
            queries.append('\n'.join(current_query))
            current_query = []
            in_dataview = False
        elif in_dataview:
            current_query.append(line)

    return queries
```

**Rollback Condition**: If Dataview query differs, rollback.

---

## INV-007: Frontmatter Merge, Never Replace

**Statement**: If a file has existing frontmatter, migration MUST merge new fields. Existing fields MUST NOT be deleted or modified unless explicitly specified in merge rules.

**Rationale**: Preserve user-authored metadata. Frontmatter may contain fields unknown to OKF (tags, aliases, custom fields).

**Validation Method**:
```python
def validate_frontmatter_merge(original_path, migrated_path):
    orig_fm = parse_frontmatter(original_path)
    migr_fm = parse_frontmatter(migrated_path)

    # All original keys must be present
    for key in orig_fm.keys():
        assert key in migr_fm, f"Key '{key}' removed from {original_path}"

    # Original values must be preserved (unless merge rule applies)
    for key, value in orig_fm.items():
        if key not in MERGE_OVERWRITE_KEYS:
            assert migr_fm[key] == value, f"Key '{key}' modified in {original_path}"
```

**MERGE_OVERWRITE_KEYS**: Keys that migration MAY write:
- `type` — replaced ONLY if the original value is an invalid enum AND appears in the Type Normalization Table (OKF_LITE_IMPLEMENTATION_SPEC.md § File Classification Rules); invalid values not in the table halt the file for human review (FM-E-007)
- `id` — added ONLY if missing (never overwrite existing)
- `authority` — added ONLY if missing (never overwrite existing)

All other keys: never written, never deleted, never reordered — their lines are byte-identical in the output (FRONTMATTER_MERGE_SPEC.md v1.1, line-preserving algorithm).

**Rollback Condition**: If any non-overwritable key is modified or deleted, rollback.

---

## INV-008: Determinism

**Statement**: Given identical input files and identical migration parameters, the migration MUST produce byte-identical output files.

**Rationale**: Reproducible builds. Diff-based review. Predictable CI/CD.

**Validation Method** (migration is in-place — there is no `--input/--output`;
test by cloning the vault twice and running in place):
```bash
cp -r "$VAULT_DIR" /tmp/run1 && cp -r "$VAULT_DIR" /tmp/run2
python vault_migrate.py --vault /tmp/run1 --all
python vault_migrate.py --vault /tmp/run2 --all

# Outputs must be identical
diff -r /tmp/run1 /tmp/run2
# Exit code 0 = deterministic
```

**Sources of Non-Determinism to Eliminate**:
- Timestamps (use Git, not `datetime.now()`)
- Random UUIDs (use slug-based IDs)
- Dictionary iteration order (use `sorted()` on keys)
- Filesystem traversal order (use `sorted(glob())`)

**Rollback Condition**: If two runs produce different outputs, migration is non-deterministic → fail.

---

## INV-009: Idempotence

**Statement**: Running migration N times MUST produce the same result as running it once.

**Rationale**: Safe re-runs. Incremental updates. No accumulation of errors.

**Validation Method** (in-place: run once, snapshot, run again, compare):
```bash
cp -r "$VAULT_DIR" /tmp/pass1
python vault_migrate.py --vault /tmp/pass1 --all   # first pass
cp -r /tmp/pass1 /tmp/pass2
python vault_migrate.py --vault /tmp/pass2 --all   # second pass

# Pass1 and Pass2 must be identical
diff -r /tmp/pass1 /tmp/pass2
# Exit code 0 = idempotent
```

**Implementation Requirements**:
- If `id:` exists, skip generation
- If `type:` exists and valid, skip assignment
- If `authority:` exists, skip default assignment
- If frontmatter already OKF-compliant, skip entirely (no-op)

**Rollback Condition**: If second run modifies files, migration is not idempotent → fail.

---

## INV-010: Reversibility

**Statement**: Every migration operation MUST be reversible to the exact pre-migration state.

**Rationale**: Risk mitigation. Rollback on error. Pilot validation.

**Validation Method**:
```bash
# Backup (backup dir lives OUTSIDE the Git repository — see ROLLBACK_SPEC.md)
cp -r "$VAULT_DIR" "$BACKUP_DIR"

# Migrate (in place)
python vault_migrate.py --vault "$VAULT_DIR" --all

# Rollback
python vault_migrate.py --vault "$VAULT_DIR" --rollback

# Vault and backup must be byte-identical
diff -r "$VAULT_DIR" "$BACKUP_DIR"
# Exit code 0 = reversible
```

**Backup Format**: Exact filesystem copy (not archive, not diff) for instant restoration.

**Rollback Algorithm**: `rm -rf "$VAULT_DIR" && cp -r "$BACKUP_DIR" "$VAULT_DIR"` — safe here because the Git repository root (`Obsidian Vault/.git`) is OUTSIDE the HotelOps directory, and the backup is a full copy of HotelOps (markdown and non-markdown alike). See ROLLBACK_SPEC.md for paths and verification.

**Rollback Condition**: If rollback produces different result than original, backup/restore is broken → fail.

---

## INV-011: No File Moves

**Statement**: Migration MUST NOT move files to different directories.

**Rationale**: Preserve Obsidian folder structure. Avoid breaking relative links, organizational logic.

**Validation Method**:
```python
def validate_no_moves(original_dir, migrated_dir):
    orig_paths = get_relative_paths(original_dir)
    migr_paths = get_relative_paths(migrated_dir)
    assert orig_paths == migr_paths, "Files moved during migration"

def get_relative_paths(base_dir):
    paths = []
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if file.endswith('.md'):
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, base_dir)
                paths.append(rel_path)
    return set(paths)
```

**Rollback Condition**: If file paths differ, migration moved files → rollback.

---

## INV-012: No Renames

**Statement**: Migration MUST NOT rename files.

**Rationale**: Filename is Obsidian note ID. Renames break wikilinks, references, user navigation.

**Validation Method**:
```python
def validate_no_renames(original_dir, migrated_dir):
    orig_names = get_filenames(original_dir)
    migr_names = get_filenames(migrated_dir)
    assert orig_names == migr_names, "Files renamed during migration"

def get_filenames(base_dir):
    names = []
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if file.endswith('.md'):
                names.append(file)
    return set(names)
```

**Rollback Condition**: If filename set differs, migration renamed files → rollback.

---

## INV-013: No Automatic Content Rewriting

**Statement**: Migration MUST NOT rewrite markdown prose, even to "improve" it.

**Rationale**: Content is human-authored. Automated rewriting breaks voice, introduces errors, violates trust.

**Examples of FORBIDDEN rewrites**:
- Fix typos
- Reformat prose
- Rewrite headings
- Change wikilink syntax
- Normalize whitespace in body
- Convert dates in prose
- Reorder sections

**Allowed modifications**:
- Add/merge frontmatter (metadata only, not body)

**Validation Method**: INV-001 (body preservation) covers this.

**Rollback Condition**: If body differs, content was rewritten → rollback.

---

## INV-014: Encoding Preservation

**Statement**: Migration MUST NOT change any file's encoding or line endings. All migrated files are UTF-8 with Unix line endings (`\n`) — enforced by **rejecting** non-conforming files at pre-flight (VAL-E-010/VAL-E-011, FM-E-001/002/003), **never by silently converting them**. Silent conversion would change body bytes and violate INV-001. The only sanctioned conversion is the explicit, user-invoked `vault_lint.py --fix`, run before migration, after backup.

**Rationale**: Obsidian uses UTF-8. Mixed encodings break rendering. Consistent line endings required for Git.

**Validation Method**:
```python
def validate_encoding(filepath):
    with open(filepath, 'rb') as f:
        content = f.read()

    # Must decode as UTF-8
    try:
        content.decode('utf-8')
    except UnicodeDecodeError:
        raise AssertionError(f"{filepath} is not UTF-8")

    # Must use Unix line endings
    if b'\r\n' in content:
        raise AssertionError(f"{filepath} has Windows line endings")
    if b'\r' in content:
        raise AssertionError(f"{filepath} has Mac line endings")
```

**Rollback Condition**: If encoding changes, rollback.

---

## INV-015: Git Cleanliness

**Statement**: Migration MUST NOT modify `.git/` directory or Git metadata.

**Rationale**: Git history is canonical. Migration annotates files, doesn't rewrite history.

**Validation Method**:
```bash
# Before migration
git_hash_before=$(git rev-parse HEAD)

# Migrate
python vault_migrate.py --vault "$VAULT_DIR" --all

# After migration
git_hash_after=$(git rev-parse HEAD)

# HEAD must not change
assert $git_hash_before == $git_hash_after
```

**Note**: Migration produces uncommitted changes (working tree dirty). Commit is manual, post-validation.

**Rollback Condition**: If `.git/` is modified, rollback.

---

## Invariant Validation Matrix

| Invariant | Check | Frequency | Failure Action |
|-----------|-------|-----------|----------------|
| INV-001 | Body preservation | Per file | Rollback file |
| INV-002 | Heading preservation | Per file | Rollback file |
| INV-003 | Code block preservation | Per file | Rollback file |
| INV-004 | Table preservation | Per file | Rollback file |
| INV-005 | Wikilink preservation | Per file | Rollback file |
| INV-006 | Dataview preservation | Per file | Rollback file |
| INV-007 | Frontmatter merge | Per file | Rollback file |
| INV-008 | Determinism | Per run (dual run test) | Fail migration |
| INV-009 | Idempotence | Per run (dual pass test) | Fail migration |
| INV-010 | Reversibility | Per run (backup/restore test) | Fail migration |
| INV-011 | No moves | Per run (path set comparison) | Rollback all |
| INV-012 | No renames | Per run (filename set comparison) | Rollback all |
| INV-013 | No content rewriting | Per file (covered by INV-001) | Rollback file |
| INV-014 | Encoding preservation | Per file | Rollback file |
| INV-015 | Git cleanliness | Per run (HEAD comparison) | Fail migration |

---

## Invariant Enforcement

**Pre-Migration**:
- Validate vault is Git-clean (no uncommitted changes) OR create backup
- Validate all files are UTF-8

**During Migration**:
- Validate each file after modification (INV-001 through INV-007, INV-013, INV-014)
- Rollback file immediately on violation

**Post-Migration**:
- Validate entire vault (INV-008 through INV-012, INV-015)
- Rollback entire migration on violation

**Continuous**:
- CI runs invariant tests on every commit
- Prevent merge if invariants violated

---

## Exemptions

**None.**

Every invariant applies to every file in every migration.

Special cases must be handled by migration logic, not by violating invariants.

---

## Audit Log

Every migration MUST log:
- Timestamp (ISO 8601)
- Migration script version
- Input directory
- Output directory
- Files modified
- Invariants validated
- Violations detected
- Rollbacks performed

**Format**: JSON Lines (`.jsonl`) for machine parsing.

**Example**:
```json
{"timestamp": "2026-07-17T10:30:00Z", "script": "vault_generate_ids.py v1.0", "input": "vault/", "output": "vault/", "files_modified": 4, "invariants_ok": true, "violations": [], "rollbacks": 0}
```

---

**End of Migration Invariants**

**Status**: These invariants are **normative**. Violation = migration failure.
