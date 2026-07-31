# Validation Specification — HotelOps OKF Lite

**Version**: 1.1 (audit & hardening pass)
**Date**: 2026-07-17
**Status**: Normative
**Scope**: All validation checks for OKF Lite compliance

---

## Purpose

Define every validation rule, severity level, and failure behavior.

**Validation MUST be deterministic**: Same input → same validation result.

---

## Validation Levels

### MANDATORY (Errors)

**Behavior**: Block migration. Rollback. Exit non-zero.

**Transaction semantics (normative)**: under the batch-atomic model (OKF_LITE_IMPLEMENTATION_SPEC.md § Transaction Model), any per-file phrasing in this document — "Rollback file", "Skip file" — means: **during a live batch, the error aborts the batch and the ENTIRE batch is restored from backup**. "Skip file" retains its literal meaning only in dry-run/inventory mode (the file is flagged and excluded from the future batch) and in standalone linting.

**Rationale**: Violation breaks vault integrity or OKF compliance.

**User Action**: Fix manually before proceeding.

---

### RECOMMENDED (Warnings)

**Behavior**: Log warning. Continue migration. Exit zero (success with warnings).

**Rationale**: Best practice violation, but not critical. Vault remains usable.

**User Action**: Review warnings, fix if time permits.

---

### INFORMATIONAL (Info)

**Behavior**: Log info. Continue migration. No effect on exit code.

**Rationale**: Diagnostic information, not a problem.

**User Action**: No action required.

---

## Validation Rules

---

## MANDATORY Rules (Errors)

---

### VAL-E-001: YAML Frontmatter Valid

**Purpose**: Ensure frontmatter is parseable.

**Check**:
```python
import yaml

def validate_yaml(filepath):
    """Validate YAML frontmatter is parseable."""
    content = read_file(filepath)

    if not content.startswith('---\n'):
        return True  # No frontmatter = valid

    fm_dict, body = parse_frontmatter(content)

    if fm_dict is None:
        return False  # Parse failed

    return True
```

**Failure Message**:
```
ERROR [VAL-E-001]: Invalid YAML frontmatter in {filepath}
  Line {line}: {error_message}
  Fix: Correct YAML syntax manually
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Rollback file. Do not proceed.

**Rationale**: Malformed YAML corrupts metadata. Manual inspection required.

---

### VAL-E-002: Type Field Present

**Purpose**: Ensure every file has `type:` field.

**Check**:
```python
def validate_type_present(filepath):
    """Validate type field exists."""
    fm = parse_frontmatter_dict(filepath)
    return 'type' in fm
```

**Failure Message**:
```
ERROR [VAL-E-002]: Missing required field 'type' in {filepath}
  Fix: Add 'type: <valid_type>' to frontmatter
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Rollback file. Do not proceed.

**Rationale**: `type` is the only globally required field (R1 requirement). Without type, classification is impossible.

---

### VAL-E-003: Type Field Valid Enum

**Purpose**: Ensure `type` is one of 9 valid values.

**Check**:
```python
VALID_TYPES = {
    'constitutional',
    'concept',
    'architecture',
    'decision',
    'session',
    'loop',
    'workstream_hub',
    'vertical',
    'log'
}

def validate_type_enum(filepath):
    """Validate type is valid enum value."""
    fm = parse_frontmatter_dict(filepath)

    if 'type' not in fm:
        return False  # Caught by VAL-E-002

    type_value = fm['type']

    return type_value in VALID_TYPES
```

**Failure Message**:
```
ERROR [VAL-E-003]: Invalid type '{type_value}' in {filepath}
  Valid types: constitutional, concept, architecture, decision, session, loop, workstream_hub, vertical, log
  Fix: Correct type to valid enum value
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Rollback file. Do not proceed.

**Rationale**: Invalid type breaks type-specific rules, linter, queries.

---

### VAL-E-004: ID Field Present

**Purpose**: Ensure every file has `id:` field.

**Check**:
```python
def validate_id_present(filepath):
    """Validate id field exists."""
    fm = parse_frontmatter_dict(filepath)
    return 'id' in fm
```

**Failure Message**:
```
ERROR [VAL-E-004]: Missing required field 'id' in {filepath}
  Fix: Run vault_generate_ids.py to generate stable ID
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Rollback file. Do not proceed.

**Rationale**: Stable ID required for cross-references (R2 requirement).

---

### VAL-E-005: ID Format Valid

**Purpose**: Ensure ID matches `type:slug` pattern.

**Check**:
```python
import re

def validate_id_format(filepath):
    """Validate ID format."""
    fm = parse_frontmatter_dict(filepath)

    if 'id' not in fm:
        return False  # Caught by VAL-E-004

    id = fm['id']

    # Type prefix = exact enum value. A generic [a-z]+ prefix would wrongly
    # reject workstream_hub (underscore). Slug allows [a-z0-9-] only.
    VALID_TYPES = (
        'constitutional', 'concept', 'architecture', 'decision',
        'session', 'loop', 'workstream_hub', 'vertical', 'log'
    )
    pattern = r'^(' + '|'.join(VALID_TYPES) + r'):[a-z0-9-]+$'
    return re.match(pattern, id) is not None
```

**Failure Message**:
```
ERROR [VAL-E-005]: Invalid ID format '{id}' in {filepath}
  Expected: <type>:<slug> (e.g., concept:financial-rules)
  Fix: Correct ID format or regenerate
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Rollback file. Do not proceed.

**Rationale**: Invalid format breaks ID parsing, queries, references.

---

### VAL-E-006: ID Type Prefix Matches Type Field

**Purpose**: Ensure ID type prefix matches document type.

**Check**:
```python
def validate_id_type_match(filepath):
    """Validate ID type prefix matches type field."""
    fm = parse_frontmatter_dict(filepath)

    if 'id' not in fm or 'type' not in fm:
        return False  # Caught by VAL-E-002, VAL-E-004

    id = fm['id']
    type = fm['type']

    id_type = id.split(':')[0]

    return id_type == type
```

**Failure Message**:
```
ERROR [VAL-E-006]: ID type mismatch in {filepath}
  ID type: {id_type}
  Document type: {type}
  Fix: Regenerate ID or correct type field
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Rollback file. Do not proceed.

**Rationale**: Mismatch indicates incorrect classification or ID generation error.

---

### VAL-E-007: ID Uniqueness (Vault-Wide)

**Purpose**: Ensure no duplicate IDs across vault.

**Check**:
```python
def validate_id_uniqueness(vault_dir):
    """Validate all IDs are unique."""
    id_to_files = {}

    for filepath in find_all_md_files(vault_dir):
        fm = parse_frontmatter_dict(filepath)

        if 'id' not in fm:
            continue  # Caught by VAL-E-004

        id = fm['id']

        if id not in id_to_files:
            id_to_files[id] = []

        id_to_files[id].append(filepath)

    # Find duplicates
    duplicates = {id: files for id, files in id_to_files.items() if len(files) > 1}

    return (len(duplicates) == 0, duplicates)
```

**Failure Message**:
```
ERROR [VAL-E-007]: Duplicate ID detected
  ID: {id}
  Files:
    - {filepath1}
    - {filepath2}
  Fix: Rename one file or merge documents
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Fail migration. Do not proceed.

**Rationale**: Duplicate IDs break cross-references (ambiguous target).

---

### VAL-E-008: Date Field Format (If Present)

**Purpose**: Ensure date fields use YYYY-MM-DD format.

**Check**:
```python
import re
import datetime

def validate_date_format(filepath):
    """Validate date field format.

    CRITICAL: the vault's existing frontmatter uses UNQUOTED dates
    (`date: 2026-05-18`), which yaml.safe_load returns as datetime.date
    objects, NOT strings. A str-only check would fail every existing
    decision and session file (all 100% compliant per the baseline).
    Both representations are valid:
      - datetime.date object (from an unquoted YAML date) -> always valid
      - str matching ^\d{4}-\d{2}-\d{2}$ (quoted date)     -> valid
      - anything else (int, float, malformed string, datetime with time)
                                                            -> invalid
    """
    fm = parse_frontmatter_dict(filepath)

    date_fields = ['date', 'created', 'last_updated', 'adopted', 'last_refresh']

    for field in date_fields:
        if field in fm:
            date_value = fm[field]

            if isinstance(date_value, datetime.date) and not isinstance(date_value, datetime.datetime):
                continue  # Unquoted YAML date — valid

            if isinstance(date_value, str) and re.match(r'^\d{4}-\d{2}-\d{2}$', date_value):
                continue  # Quoted YYYY-MM-DD string — valid

            return (False, field, date_value)

    return (True, None, None)
```

**Failure Message**:
```
ERROR [VAL-E-008]: Invalid date format in {filepath}
  Field: {field}
  Value: {date_value}
  Expected: YYYY-MM-DD (e.g., 2026-07-17)
  Fix: Correct date format
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Rollback file. Do not proceed.

**Rationale**: Invalid date format breaks date-based queries, sorting.

---

### VAL-E-009: Body Preservation (Post-Migration)

**Purpose**: Ensure markdown body unchanged after migration.

**Reference input (normative)**: The migrated file alone cannot prove its body is unchanged — this rule REQUIRES the pre-migration reference, supplied as the **SHA-256 baseline manifest** written at backup time (ROLLBACK_SPEC.md § Baseline Manifest; `vault_migrate.py --write-baseline`). The manifest records, per in-scope file, the SHA-256 of the full file AND of the extracted body. `vault_lint.py` receives it via `--baseline PATH`. If no baseline is supplied (standalone lint of an already-migrated vault), VAL-E-009 is **skipped with INFO** — it is only evaluable in a migration context. The orchestrator MUST always supply it.

**Check**:
```python
import hashlib

def validate_body_preserved(filepath, migrated_content, baseline_manifest):
    """Validate body unchanged against the pre-migration baseline."""
    entry = baseline_manifest.get(relpath(filepath))
    if entry is None:
        return False  # in-scope file missing from baseline = error

    migr_body_hash = hashlib.sha256(
        extract_body(migrated_content).encode('utf-8')).hexdigest()

    return migr_body_hash == entry['body_sha256']
```

**Failure Message**:
```
ERROR [VAL-E-009]: Markdown body modified during migration
  File: {filepath}
  Fix: Rollback, investigate migration script bug
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Rollback file immediately. Log incident.

**Rationale**: Body modification violates INV-001 (content preservation).

---

### VAL-E-010: Encoding UTF-8

**Purpose**: Ensure all files are UTF-8 encoded.

**Check**:
```python
def validate_utf8(filepath):
    """Validate file is UTF-8."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            f.read()
        return True
    except UnicodeDecodeError:
        return False
```

**Failure Message**:
```
ERROR [VAL-E-010]: File is not UTF-8 encoded
  File: {filepath}
  Fix: Convert to UTF-8 manually
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Skip file. Do not migrate.

**Rationale**: Non-UTF-8 files violate INV-014. Obsidian requires UTF-8.

---

### VAL-E-011: Line Endings Unix

**Purpose**: Ensure files use Unix line endings (`\n`).

**Check**:
```python
def validate_unix_line_endings(filepath):
    """Validate Unix line endings."""
    with open(filepath, 'rb') as f:
        content = f.read()

    # Check for Windows CRLF
    if b'\r\n' in content:
        return (False, 'CRLF')

    # Check for Mac CR
    if b'\r' in content:
        return (False, 'CR')

    return (True, None)
```

**Failure Message**:
```
ERROR [VAL-E-011]: File uses {line_ending} line endings
  File: {filepath}
  Fix: Convert to Unix (LF) line endings
```

**Severity**: MANDATORY (Error)

**Failure Behavior**: Skip file (do not migrate it). **Migration NEVER normalizes line endings silently** — normalization changes body bytes and would violate INV-001. The single sanctioned fix is the explicit, user-invoked `vault_lint.py --fix` (which normalizes CRLF/CR → LF as a separate, logged, pre-migration operation, after backup).

**Rationale**: Mixed line endings cause Git diffs, platform issues. INV-014 requires Unix.

**Vault reality**: As of 2026-07-17 zero HotelOps files contain CR/CRLF, so this rule is expected to be a no-op safeguard.

---

## RECOMMENDED Rules (Warnings)

---

### VAL-W-001: Authority Field Present

**Purpose**: Encourage explicit authority declaration.

**Check**:
```python
def validate_authority_present(filepath):
    """Validate authority field exists."""
    fm = parse_frontmatter_dict(filepath)
    return 'authority' in fm
```

**Failure Message**:
```
WARN [VAL-W-001]: Authority field missing in {filepath}
  Defaulting to type-based authority
  Recommendation: Add 'authority: canonical|historical|working'
```

**Severity**: RECOMMENDED (Warning)

**Failure Behavior**: Log warning. Continue.

**Rationale**: Authority is recommended (W1), auto-assignable from type. Nice-to-have, not critical.

---

### VAL-W-002: Authority Valid Enum

**Purpose**: Ensure authority is valid if present.

**Check**:
```python
VALID_AUTHORITY = {'canonical', 'historical', 'working'}

def validate_authority_enum(filepath):
    """Validate authority is valid enum."""
    fm = parse_frontmatter_dict(filepath)

    if 'authority' not in fm:
        return True  # Caught by VAL-W-001

    authority = fm['authority']

    return authority in VALID_AUTHORITY
```

**Failure Message**:
```
WARN [VAL-W-002]: Invalid authority '{authority}' in {filepath}
  Valid values: canonical, historical, working
  Recommendation: Correct to valid value
```

**Severity**: RECOMMENDED (Warning)

**Failure Behavior**: Log warning. Continue.

**Rationale**: Invalid authority is non-critical (can infer from type). Warn, don't block.

---

### VAL-W-003: Decision Has Date + Status

**Purpose**: Ensure decisions have required fields.

**Check**:
```python
def validate_decision_fields(filepath):
    """Validate decision-specific required fields."""
    fm = parse_frontmatter_dict(filepath)

    if fm.get('type') != 'decision':
        return True  # Not a decision

    missing = []
    if 'date' not in fm:
        missing.append('date')
    if 'status' not in fm:
        missing.append('status')

    return (len(missing) == 0, missing)
```

**Failure Message**:
```
WARN [VAL-W-003]: Decision missing required fields in {filepath}
  Missing: {missing}
  Recommendation: Add missing fields
```

**Severity**: RECOMMENDED (Warning)

**Failure Behavior**: Log warning. Continue.

**Rationale**: Decisions should have date/status (W2), but already 100% compliant. Warn for outliers.

---

### VAL-W-004: Session Has Date + Status

**Purpose**: Ensure sessions have required fields.

**Check**:
```python
def validate_session_fields(filepath):
    """Validate session-specific required fields."""
    fm = parse_frontmatter_dict(filepath)

    if fm.get('type') != 'session':
        return True  # Not a session

    missing = []
    if 'date' not in fm:
        missing.append('date')
    if 'status' not in fm:
        missing.append('status')

    return (len(missing) == 0, missing)
```

**Failure Message**:
```
WARN [VAL-W-004]: Session missing required fields in {filepath}
  Missing: {missing}
  Recommendation: Add missing fields
```

**Severity**: RECOMMENDED (Warning)

**Failure Behavior**: Log warning. Continue.

---

### VAL-W-005: Loop Has Owner + Cadence + Status

**Purpose**: Ensure loops have operational fields.

**Check**:
```python
def validate_loop_fields(filepath):
    """Validate loop-specific required fields."""
    fm = parse_frontmatter_dict(filepath)

    if fm.get('type') != 'loop':
        return True  # Not a loop

    missing = []
    if 'owner' not in fm:
        missing.append('owner')
    if 'cadence' not in fm:
        missing.append('cadence')
    if 'status' not in fm:
        missing.append('status')

    return (len(missing) == 0, missing)
```

**Failure Message**:
```
WARN [VAL-W-005]: Loop missing operational fields in {filepath}
  Missing: {missing}
  Recommendation: Add missing fields (critical for handoff)
```

**Severity**: RECOMMENDED (Warning)

**Failure Behavior**: Log warning. Continue.

**Rationale**: Loops need owner/cadence for operational handoff (W2). Warn, don't block.

---

### VAL-W-006: Workstream Has Required Fields

**Purpose**: Ensure workstreams have state fields.

**Check**:
```python
def validate_workstream_fields(filepath):
    """Validate workstream-specific required fields."""
    fm = parse_frontmatter_dict(filepath)

    if fm.get('type') != 'workstream_hub':
        return True  # Not a workstream

    missing = []
    if 'workstream_id' not in fm:
        missing.append('workstream_id')
    if 'status' not in fm:
        missing.append('status')
    if 'last_refresh' not in fm:
        missing.append('last_refresh')

    return (len(missing) == 0, missing)
```

**Failure Message**:
```
WARN [VAL-W-006]: Workstream missing state fields in {filepath}
  Missing: {missing}
  Recommendation: Add missing fields (important for staleness check)
```

**Severity**: RECOMMENDED (Warning)

**Failure Behavior**: Log warning. Continue.

---

### VAL-W-007: Status Field Valid Enum (Type-Specific)

**Purpose**: Validate status values for type-specific enums.

**Check**:
```python
STATUS_ENUMS = {
    # Grounded in observed vault values (2026-07-17):
    #   decisions: accepted (13 + variants), implemented (12), proposed (3+),
    #              active (3), partial (1), parked (1)
    #   sessions:  closed (69/69); 'open-threads' is the session-reflect
    #              skill's documented carry-over state (rare by design)
    'decision': {'proposed', 'accepted', 'approved', 'implemented', 'active',
                 'partial', 'parked', 'superseded', 'rejected'},
    'session': {'closed', 'open-threads', 'draft', 'completed', 'archived'},
    'loop': {'active', 'paused', 'archived'},
    'workstream_hub': {'active', 'blocked', 'completed', 'archived'}
}

def normalize_status(status):
    """
    Deterministic normalization for freeform status values.

    Vault reality: many decisions carry annotated statuses like
    'Accepted (riunione strategica)' or 'PROPOSED — awaiting Stefano'.
    Rule: take the FIRST whitespace-delimited token, lowercase it,
    strip trailing punctuation (,;:). The annotation is prose and is
    not validated.
    """
    if not isinstance(status, str) or not status.strip():
        return None
    return status.strip().split()[0].lower().rstrip(',;:')

def validate_status_enum(filepath):
    """Validate (normalized) status is valid for document type."""
    fm = parse_frontmatter_dict(filepath)

    type = fm.get('type')
    status = fm.get('status')

    if type not in STATUS_ENUMS or status is None:
        return True  # No validation rule

    return normalize_status(status) in STATUS_ENUMS[type]
```

**Failure Message**:
```
WARN [VAL-W-007]: Invalid status '{status}' for {type} in {filepath}
  Valid statuses: {valid_statuses}
  Recommendation: Use valid status value
```

**Severity**: RECOMMENDED (Warning)

**Failure Behavior**: Log warning. Continue.

**Rationale**: Invalid status is non-critical (still usable). Warn, don't block.

---

## INFORMATIONAL Rules (Info)

---

### VAL-I-001: Git Metadata Present

**Purpose**: Inform if Git-derived metadata exists.

**Check**:
```python
def validate_git_metadata(filepath):
    """Check if Git metadata fields present."""
    fm = parse_frontmatter_dict(filepath)

    has_created = 'created' in fm
    has_last_updated = 'last_updated' in fm

    return (has_created, has_last_updated)
```

**Failure Message**:
```
INFO [VAL-I-001]: Git metadata missing in {filepath}
  Missing: created, last_updated
  Note: Can be auto-generated from Git history (optional)
```

**Severity**: INFORMATIONAL (Info)

**Failure Behavior**: Log info. Continue.

**Rationale**: Git metadata is optional (O2). Informational only.

---

### VAL-I-002: Wikilinks Extracted

**Purpose**: Inform if wikilinks have been extracted to references field.

**Check**:
```python
def validate_wikilinks_extracted(filepath):
    """Check if wikilinks extracted to references field."""
    content = read_file(filepath)
    body = extract_body(content)

    wikilinks = re.findall(r'\[\[([^\]]+)\]\]', body)

    fm = parse_frontmatter_dict(filepath)
    has_references = 'references' in fm

    if len(wikilinks) > 0 and not has_references:
        return (False, len(wikilinks))

    return (True, 0)
```

**Failure Message**:
```
INFO [VAL-I-002]: Wikilinks not extracted in {filepath}
  Found {count} wikilinks in body
  Note: Run vault_extract_wikilinks.py to populate references field (optional)
```

**Severity**: INFORMATIONAL (Info)

**Failure Behavior**: Log info. Continue.

**Rationale**: Wikilink extraction is optional (O1). Informational only.

---

### VAL-I-003: Manual Relations Present

**Purpose**: Inform if manual relations (supersedes, owned_by) present.

**Check**:
```python
def validate_manual_relations(filepath):
    """Check if manual relations present."""
    fm = parse_frontmatter_dict(filepath)

    has_supersedes = 'supersedes' in fm
    has_owned_by = 'owned_by' in fm

    return (has_supersedes, has_owned_by)
```

**Failure Message**:
```
INFO [VAL-I-003]: Manual relations missing in {filepath}
  Note: Consider adding 'supersedes' or 'owned_by' if applicable (optional)
```

**Severity**: INFORMATIONAL (Info)

**Failure Behavior**: Log info. Continue.

**Rationale**: Manual relations are optional (O3). Informational only.

---

### VAL-I-004: Slug Length Warning

**Purpose**: Warn if slug is very long (readability issue).

**Check**:
```python
def validate_slug_length(filepath):
    """Warn if slug is very long."""
    fm = parse_frontmatter_dict(filepath)

    if 'id' not in fm:
        return True

    id = fm['id']
    slug = id.split(':')[1]

    return len(slug) <= 80
```

**Failure Message**:
```
INFO [VAL-I-004]: Slug is very long in {filepath}
  ID: {id}
  Length: {len(slug)} chars
  Note: Consider shorter filename for readability (optional)
```

**Severity**: INFORMATIONAL (Info)

**Failure Behavior**: Log info. Continue.

**Rationale**: Long slugs are valid but less readable. Inform, don't block.

---

## Validation Matrix

| Rule | Level | Check | Failure Behavior |
|------|-------|-------|------------------|
| VAL-E-001 | MANDATORY | YAML valid | Rollback file |
| VAL-E-002 | MANDATORY | type present | Rollback file |
| VAL-E-003 | MANDATORY | type valid enum | Rollback file |
| VAL-E-004 | MANDATORY | id present | Rollback file |
| VAL-E-005 | MANDATORY | id format valid | Rollback file |
| VAL-E-006 | MANDATORY | id type matches type | Rollback file |
| VAL-E-007 | MANDATORY | id unique (vault-wide) | Fail migration |
| VAL-E-008 | MANDATORY | date format YYYY-MM-DD | Rollback file |
| VAL-E-009 | MANDATORY | body preserved | Rollback file, log incident |
| VAL-E-010 | MANDATORY | UTF-8 encoding | Skip file |
| VAL-E-011 | MANDATORY | Unix line endings | Skip file (fix only via explicit `--fix`) |
| VAL-W-001 | RECOMMENDED | authority present | Warn, continue |
| VAL-W-002 | RECOMMENDED | authority valid enum | Warn, continue |
| VAL-W-003 | RECOMMENDED | decision has date+status | Warn, continue |
| VAL-W-004 | RECOMMENDED | session has date+status | Warn, continue |
| VAL-W-005 | RECOMMENDED | loop has owner+cadence+status | Warn, continue |
| VAL-W-006 | RECOMMENDED | workstream has required fields | Warn, continue |
| VAL-W-007 | RECOMMENDED | status valid enum | Warn, continue |
| VAL-I-001 | INFORMATIONAL | Git metadata present | Info, continue |
| VAL-I-002 | INFORMATIONAL | Wikilinks extracted | Info, continue |
| VAL-I-003 | INFORMATIONAL | Manual relations present | Info, continue |
| VAL-I-004 | INFORMATIONAL | Slug length | Info, continue |

---

## Validation Profiles (Per Phase)

**CRITICAL — resolves a v1.0 contradiction**: rules VAL-E-002 through VAL-E-007 check for `type:` and `id:` fields, which are exactly what the migration *adds*. Running the full MANDATORY set as a pre-migration gate can therefore **never pass** on an un-migrated vault (0/239 files have `id:` before migration). Validation MUST run as phase-specific profiles:

### Profile PRE (pre-flight gate, before any modification)

Checks only conditions that must hold on the *input* vault:

1. VAL-E-010 (UTF-8)
2. VAL-E-011 (Line endings)
3. VAL-E-001 (YAML valid — files with a byte-0 frontmatter fence must parse)
4. VAL-E-008 (date format, on files that already have frontmatter)

**Gate**: all four pass on every in-scope file → GO. Any failure → fix manually (or `--fix` for line endings), re-run gate.

**CLI**: `vault_lint.py --all --profile pre`

### Profile POST (per-file, immediately after migrating each file)

Full mandatory set: VAL-E-001, 002, 003, 004, 005, 006, 008, 009 (body preserved vs `--baseline`), plus warnings VAL-W-001…007 and info VAL-I-001…004.

**On Error**: Abort the batch → restore the entire batch from backup (batch-atomic). Log error, exit 1.

**CLI**: `vault_lint.py --file <path> --baseline <manifest>` (POST is the default profile)

### Profile VAULT (vault-wide, after all files processed)

1. VAL-E-007 (ID uniqueness) — requires all files processed

**On Error**: Fail entire migration. Rollback all files.

**CLI**: `vault_lint.py --all` (includes VAULT checks when run with `--all`)

### Steady State (post-MVP, CI)

Full set (PRE + POST + VAULT) — after migration, the vault must pass everything, forever.

---

## Validation Output Format

### Summary Report

```
OKF Lite Validation Report
Generated: 2026-07-17T10:30:00Z
Vault: /Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault/HotelOps/

Files Validated: 239
├─ Tier 1: 74
└─ Tier 2: 165

Results:
├─ PASS: 235 (98.3%)
├─ ERRORS: 2 (0.8%)
├─ WARNINGS: 15 (6.3%)
└─ INFO: 42 (17.6%)

Errors (MANDATORY):
  [VAL-E-002] concepts/orphan.md: Missing required field 'type'
  [VAL-E-006] decisions/old_plan.md: ID type mismatch (decision:concept-foo vs type: concept)

Warnings (RECOMMENDED):
  [VAL-W-001] 15 files missing 'authority' field
  [VAL-W-005] loops/draft.md: Missing operational fields (owner, cadence)

Info (INFORMATIONAL):
  [VAL-I-002] 22 files have wikilinks not extracted
  [VAL-I-001] 42 files missing Git metadata

Status: FAILED (2 errors must be fixed)
```

---

### Per-File Report (JSON Lines)

```json
{"file": "concepts/FINANCIAL_RULES.md", "status": "pass", "errors": [], "warnings": [], "info": []}
{"file": "concepts/orphan.md", "status": "error", "errors": [{"code": "VAL-E-002", "message": "Missing required field 'type'"}], "warnings": [], "info": []}
{"file": "loops/draft.md", "status": "warn", "errors": [], "warnings": [{"code": "VAL-W-005", "message": "Missing operational fields (owner, cadence)"}], "info": []}
```

---

## CLI Interface

```bash
# Validate all files
python vault_lint.py --all

# Validate specific files
python vault_lint.py --file concepts/FINANCIAL_RULES.md

# Validate with a phase profile (see Validation Profiles)
python vault_lint.py --all --profile pre    # Pre-flight gate (E-001, E-008, E-010, E-011)
python vault_lint.py --all --profile post   # Full per-file set (default)
python vault_lint.py --all --profile vault  # Vault-wide (E-007 uniqueness)

# Validate with specific level
python vault_lint.py --all --level mandatory  # Errors only
python vault_lint.py --all --level recommended  # Errors + warnings
python vault_lint.py --all --level informational  # All

# Output format
python vault_lint.py --all --format text  # Human-readable
python vault_lint.py --all --format json  # Machine-readable

# Baseline manifest (required for VAL-E-009; skipped with INFO if absent)
python vault_lint.py --all --baseline okf_baseline_manifest.json

# Strict mode (warnings = errors)
python vault_lint.py --all --strict

# Exit codes
# 0 = Pass (no errors, warnings OK)
# 1 = Errors (mandatory violations)
# 2 = Warnings (if --strict)
```

---

## Integration with Migration

**Pre-Migration** (Profile PRE only — see Validation Profiles above; the full
mandatory set would always fail on an un-migrated vault):
```python
# Validate vault is migratable (encoding, line endings, parseable YAML, dates)
if not validate_vault(vault_dir, profile='pre'):
    print("ERROR: Vault has pre-flight errors. Fix before migration.")
    sys.exit(1)
```

**During Migration**:
```python
for filepath in files_to_migrate:
    # Validate pre-conditions
    if not validate_pre_migration(filepath):
        log_error(f"Skipping {filepath}: validation failed")
        continue

    # Migrate
    migrate_file(filepath, metadata)

    # Validate post-conditions
    if not validate_post_migration(filepath):
        log_error(f"Rollback {filepath}: post-migration validation failed")
        rollback_file(filepath)
```

**Post-Migration**:
```python
# Vault-wide validations
if not validate_id_uniqueness(vault_dir):
    print("ERROR: Duplicate IDs detected. Rollback entire migration.")
    rollback_all()
    sys.exit(1)
```

---

## Continuous Validation (CI)

**GitHub Actions Workflow**:
```yaml
name: OKF Lite Validation

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Validate vault
        run: python vault_lint.py --all --strict
      - name: Check results
        run: |
          if [ $? -ne 0 ]; then
            echo "Validation failed"
            exit 1
          fi
```

**Frequency**: Every commit to vault.

**Policy**: Block merge if validation fails.

---

**End of Validation Specification**

**Status**: Normative. All implementations MUST implement these validation rules exactly.
