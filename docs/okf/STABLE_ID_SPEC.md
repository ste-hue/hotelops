# Stable ID Specification — HotelOps OKF Lite

**Version**: 1.1 (audit & hardening pass)
**Date**: 2026-07-17
**Status**: Normative
**Scope**: All stable ID generation and validation

---

## Purpose

Define the exact algorithm for generating stable, unique, semantic IDs for vault documents.

**Implementations MUST produce identical IDs given identical inputs.**

---

## ID Format

**Pattern**: `<type>:<slug>`

**Examples**:
- `concept:cassa-vs-competenza-sources`
- `decision:2026-05-18-pf-rotate-design`
- `session:2026-06-04-esolver-p0`
- `loop:cash-control`
- `constitutional:identity`
- `workstream_hub:hub`

**Length**: 18-60 characters (typical: 25-40)

**Character Set**:
- Type prefix: the exact type enum value, verbatim (lowercase letters and underscores — `workstream_hub` keeps its underscore)
- Slug: `[a-z0-9-]` (lowercase letters, digits, hyphens)
- Separator: single colon

**Normative rule**: The type prefix is NEVER normalized. It is the literal enum value from the 9-type system. Only the slug undergoes normalization.

---

## Algorithm

### Input

- `filepath`: Absolute or relative path to markdown file
- `type`: Document type (from type system: constitutional, concept, etc.)

**Example**:
```
filepath: /vault/concepts/CASSA_VS_COMPETENZA_sources.md
type: concept
```

### Step 1: Extract Filename

```python
import os

def extract_filename(filepath):
    """
    Extract filename without extension.

    Example:
        /vault/concepts/CASSA_VS_COMPETENZA_sources.md
        → CASSA_VS_COMPETENZA_sources
    """
    basename = os.path.basename(filepath)  # CASSA_VS_COMPETENZA_sources.md
    filename = os.path.splitext(basename)[0]  # CASSA_VS_COMPETENZA_sources
    return filename
```

### Step 2: Normalize to Slug

```python
import re

def normalize_to_slug(filename):
    """
    Normalize filename to slug.

    Rules:
    1. Lowercase
    2. Replace underscores with hyphens
    3. Replace every remaining character not in [a-z0-9-] with a hyphen
       (spaces, punctuation, parentheses, em-dashes, accented letters, etc.)
    4. Date patterns (YYYY-MM-DD) survive unchanged (digits and hyphens are valid)
    5. Collapse multiple hyphens to single
    6. Strip leading/trailing hyphens

    NORMATIVE: invalid characters are REPLACED WITH HYPHENS, never deleted.
    Deleting them would fuse adjacent words ("Foo Bar" → "foobar") and
    produce different IDs than this spec's examples.

    Example:
        CASSA_VS_COMPETENZA_sources
        → cassa-vs-competenza-sources
    """
    # Step 1: Lowercase
    slug = filename.lower()

    # Step 2: Underscores → hyphens
    slug = slug.replace('_', '-')

    # Step 3: Replace invalid characters with hyphens (keep a-z, 0-9, -)
    slug = re.sub(r'[^a-z0-9-]', '-', slug)

    # Step 4: Collapse multiple hyphens
    slug = re.sub(r'-+', '-', slug)

    # Step 5: Strip leading/trailing hyphens
    slug = slug.strip('-')

    return slug
```

**Examples**:

| Filename | Slug |
|----------|------|
| `CASSA_VS_COMPETENZA_sources` | `cassa-vs-competenza-sources` |
| `2026-05-18_PF_Rotate_Design` | `2026-05-18-pf-rotate-design` |
| `FINANCIAL_RULES` | `financial-rules` |
| `cash_control` | `cash-control` |
| `IDENTITY` | `identity` |
| `HUB` | `hub` |
| `Session 2026-06-04: Esolver P0` | `session-2026-06-04-esolver-p0` |
| `Foo  Bar` | `foo-bar` |

**Note**: Dates (YYYY-MM-DD) are preserved. Spaces, colons, underscores become hyphens (then consecutive hyphens collapse to one).

### Step 3: Construct ID

```python
def generate_id(filepath, type):
    """
    Generate stable ID.

    Format: <type>:<slug>

    Example:
        filepath: /vault/concepts/CASSA_VS_COMPETENZA_sources.md
        type: concept
        → concept:cassa-vs-competenza-sources
    """
    filename = extract_filename(filepath)
    slug = normalize_to_slug(filename)
    id = f"{type}:{slug}"
    return id
```

**Complete Algorithm**:
```python
import os
import re

def generate_stable_id(filepath, type):
    """Generate stable ID for document."""
    # Extract filename
    basename = os.path.basename(filepath)
    filename = os.path.splitext(basename)[0]

    # Normalize to slug
    slug = filename.lower()
    slug = slug.replace('_', '-')
    slug = re.sub(r'[^a-z0-9-]', '-', slug)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-')

    # Construct ID
    id = f"{type}:{slug}"

    return id
```

---

## Validation

### ID Format Validation

**Pattern**: `^(constitutional|concept|architecture|decision|session|loop|workstream_hub|vertical|log):[a-z0-9-]+$`

(The prefix is the exact enum — a generic `[a-z]+` would wrongly reject `workstream_hub`.)

```python
import re

VALID_TYPES = (
    'constitutional', 'concept', 'architecture', 'decision',
    'session', 'loop', 'workstream_hub', 'vertical', 'log'
)

def validate_id_format(id):
    """
    Validate ID format.

    The type prefix MUST be one of the 9 exact enum values (note:
    workstream_hub contains an underscore — a generic [a-z]+ pattern
    would wrongly reject it). The slug allows [a-z0-9-] only.

    Valid:
        concept:cassa-vs-competenza-sources
        decision:2026-05-18-pf-rotate-design
        workstream_hub:hub

    Invalid:
        Concept:doc      # Uppercase
        concept:         # Empty slug
        :doc             # Empty type
        concept          # No colon
        concept:foo_bar  # Underscore in slug
        report:foo       # Type not in enum
    """
    pattern = r'^(' + '|'.join(VALID_TYPES) + r'):[a-z0-9-]+$'
    return re.match(pattern, id) is not None
```

### Type Validation

**Rule**: Type prefix MUST match document's type field.

```python
def validate_type_match(id, type):
    """
    Validate ID type prefix matches document type.

    Example:
        id: concept:financial-rules
        type: concept
        → VALID

        id: concept:financial-rules
        type: decision
        → INVALID (type mismatch)
    """
    id_type = id.split(':')[0]
    return id_type == type
```

### Uniqueness Validation

**Rule**: No two documents can have the same ID.

```python
def validate_uniqueness(vault_dir):
    """
    Validate all IDs are unique across vault.

    Returns:
        (is_valid, duplicates)

    duplicates: dict of {id: [filepath1, filepath2]}
    """
    id_to_files = {}

    for root, dirs, files in os.walk(vault_dir):
        for file in files:
            if file.endswith('.md'):
                filepath = os.path.join(root, file)
                fm = parse_frontmatter(filepath)
                if 'id' in fm:
                    id = fm['id']
                    if id not in id_to_files:
                        id_to_files[id] = []
                    id_to_files[id].append(filepath)

    # Find duplicates
    duplicates = {id: files for id, files in id_to_files.items() if len(files) > 1}

    is_valid = len(duplicates) == 0

    return (is_valid, duplicates)
```

---

## Collision Handling

### Detection

**When**: During mass migration or incremental file addition.

**How**: Build ID registry, detect duplicates.

```python
def detect_collisions(files):
    """
    Detect ID collisions before generating.

    Args:
        files: List of (filepath, type) tuples

    Returns:
        collisions: dict of {slug: [(filepath, type), ...]}
    """
    slug_to_files = {}

    for filepath, type in files:
        id = generate_stable_id(filepath, type)
        slug = id.split(':')[1]

        if slug not in slug_to_files:
            slug_to_files[slug] = []
        slug_to_files[slug].append((filepath, type, id))

    # Find collisions (same slug, same type)
    collisions = {}
    for slug, entries in slug_to_files.items():
        # Group by type
        by_type = {}
        for filepath, type, id in entries:
            if type not in by_type:
                by_type[type] = []
            by_type[type].append(filepath)

        # Collision = same type, multiple files
        for type, filepaths in by_type.items():
            if len(filepaths) > 1:
                collision_id = f"{type}:{slug}"
                collisions[collision_id] = filepaths

    return collisions
```

### Resolution Strategy

**Option 1: Fail Migration**

```python
if collisions:
    print("ERROR: ID collisions detected:")
    for id, filepaths in collisions.items():
        print(f"  {id}:")
        for fp in filepaths:
            print(f"    - {fp}")
    sys.exit(1)
```

**Rationale**: Force user to resolve manually (rename file, merge files, clarify intent).

**Recommended**: **Option 1** (strict). Collisions indicate ambiguity that automation cannot resolve.

---

**Option 2: Append Disambiguator**

```python
def resolve_collision(slug, type, filepath, existing_ids):
    """
    Append disambiguator to slug.

    Example:
        slug: financial-rules
        type: concept
        existing: [concept:financial-rules]
        → concept:financial-rules-2
    """
    base_id = f"{type}:{slug}"

    if base_id not in existing_ids:
        return base_id

    # Append counter
    counter = 2
    while True:
        candidate = f"{type}:{slug}-{counter}"
        if candidate not in existing_ids:
            return candidate
        counter += 1
```

**Rationale**: Automatic resolution, no user intervention.

**Downsides**: IDs become opaque (`financial-rules-2` — which one is correct?). User confusion.

**Recommendation**: **Do NOT use** for MVP. Require manual resolution.

---

### Preventing Future Collisions

**Rule**: Before creating new file, check ID uniqueness.

**Workflow**:
1. User creates `new_file.md`
2. Migration script generates ID
3. Check uniqueness
4. If collision → warn user, require rename
5. If unique → proceed

---

## Persistence

### First Generation

**When**: File has no `id:` field in frontmatter.

**Action**: Generate ID, add to frontmatter.

```python
if 'id' not in frontmatter:
    id = generate_stable_id(filepath, type)
    frontmatter['id'] = id
```

### Subsequent Runs (Idempotence)

**When**: File already has `id:` field.

**Action**: **Preserve the existing ID only if it passes all three checks** (FRONTMATTER_MERGE_SPEC.md §4.5, FM-E-008):

1. Syntactically valid (enum-anchored pattern above)
2. Type-consistent (prefix == the file's resolved `type`)
3. Unique (no other in-scope file has it)

```python
if 'id' in frontmatter:
    existing = str(frontmatter['id'])
    if (validate_id_format(existing)
            and existing.split(':')[0] == resolved_type
            and registry.get(existing, filepath) == filepath):
        return existing        # preserve — even if slug != filename slug (renames)
    raise UnpreservableId(existing)   # FM-E-008: skip file, human review.
                                      # NEVER silently overwrite an existing id.
```

**Rationale**: IDs are **stable**. Once assigned, they never change (even if the filename changes — that's the point of stability). But a malformed, type-mismatched, or duplicated ID is a defect, and silently keeping it would poison cross-references just as much as silently replacing it: a human decides.

---

## Regeneration Policy

**Rule**: **NEVER regenerate IDs automatically.**

**Rationale**: ID stability is critical. Regeneration breaks cross-references.

**Exception**: Manual regeneration (user explicitly requests, understands consequences).

**Procedure for manual regeneration**:
1. Remove `id:` field from frontmatter
2. Run migration script
3. Script generates new ID
4. User reviews, confirms
5. Commit

**Risk**: Breaks existing references. Use only if ID was incorrectly assigned.

---

## Migration from Filename-Based References

**Problem**: Obsidian uses `[[filename]]` wikilinks. OKF uses stable IDs.

**Strategy**: Extract wikilinks → resolve to IDs → populate `references:` field.

**Example**:

Before:
```markdown
See [[CASSA_VS_COMPETENZA_sources]] for details.
```

After (frontmatter):
```yaml
references:
  - concept:cassa-vs-competenza-sources
```

**Note**: Wikilink in body preserved (INV-005). References field added.

---

## Cross-Vault References (Deferred)

**Future**: If vault federates, add namespace.

**Format**: `<namespace>/<type>:<slug>`

**Example**: `hotelops/concept:financial-rules`

**Current**: Single vault, no namespace needed. `type:slug` sufficient.

**Migration Path**: When federation needed, prepend namespace to all IDs.

```python
def add_namespace(id, namespace):
    """
    Add namespace to ID.

    Example:
        concept:financial-rules
        → hotelops/concept:financial-rules
    """
    return f"{namespace}/{id}"
```

**Compatibility**: `type:slug` is valid subset of `namespace/type:slug`.

---

## Edge Cases

### Empty Filename

**Input**: `filepath: /vault/.md`

**Behavior**: Fail. Empty filename is invalid.

```python
if not slug:
    raise ValueError(f"Cannot generate ID for empty filename: {filepath}")
```

---

### Numeric-Only Filename

**Input**: `filepath: /vault/2026.md`

**Slug**: `2026`

**ID**: `decision:2026` (if type=decision)

**Valid**: Yes. Numbers are allowed in slug.

---

### Very Long Filename

**Input**: `filepath: /vault/this-is-a-very-long-filename-with-many-words-and-it-keeps-going-and-going.md`

**Slug**: `this-is-a-very-long-filename-with-many-words-and-it-keeps-going-and-going`

**ID**: `concept:this-is-a-very-long-filename-with-many-words-and-it-keeps-going-and-going`

**Valid**: Yes. No length limit (YAML supports long strings).

**Recommendation**: Warn if slug > 80 chars (readability).

---

### Special Characters in Filename

**Input**: `filepath: /vault/Plan (2026) — Q1.md`

**Normalization**:
1. `plan (2026) — q1`
2. `plan--2026-----q1` (spaces, parens, em-dash each replaced by a hyphen)
3. `plan-2026-q1` (collapse consecutive hyphens, strip edges)

**ID**: `decision:plan-2026-q1`

**Valid**: Yes. Special chars removed.

---

### Filename with Leading/Trailing Hyphens

**Input**: `filepath: /vault/-test-.md`

**Normalization**:
1. `-test-`
2. Strip → `test`

**ID**: `concept:test`

**Valid**: Yes. Hyphens stripped.

---

### Filename with Consecutive Hyphens

**Input**: `filepath: /vault/foo---bar.md`

**Normalization**:
1. `foo---bar`
2. Collapse → `foo-bar`

**ID**: `concept:foo-bar`

**Valid**: Yes. Multiple hyphens collapsed.

---

## Test Cases

| Filename | Type | Expected ID |
|----------|------|-------------|
| `IDENTITY.md` | constitutional | `constitutional:identity` |
| `FINANCIAL_RULES.md` | concept | `concept:financial-rules` |
| `CASSA_VS_COMPETENZA_sources.md` | concept | `concept:cassa-vs-competenza-sources` |
| `2026-05-18_PF_Rotate_Design.md` | decision | `decision:2026-05-18-pf-rotate-design` |
| `2026-06-04_esolver_p0.md` | session | `session:2026-06-04-esolver-p0` |
| `cash_control.md` | loop | `loop:cash-control` |
| `HUB.md` | workstream_hub | `workstream_hub:hub` |
| `Plan (2026).md` | decision | `decision:plan-2026` |
| `Foo  Bar.md` | concept | `concept:foo-bar` |
| `Test-123.md` | concept | `concept:test-123` |
| `2026.md` | decision | `decision:2026` |

---

## Validation Test Suite

**Required Tests**:

1. **Format validation** (valid pattern)
2. **Type prefix match** (ID type == document type)
3. **Uniqueness** (no duplicate IDs)
4. **Idempotence** (regenerate → same ID)
5. **Determinism** (same input → same ID)
6. **Normalization** (special chars, case, underscores)
7. **Edge cases** (empty, numeric, long, special chars)

---

## CLI Interface (for manual ID generation)

```bash
# Generate ID for single file
python vault_generate_ids.py --file concepts/FINANCIAL_RULES.md

# Generate IDs for all files (dry-run)
python vault_generate_ids.py --all --dry-run

# Generate IDs for all files (apply)
python vault_generate_ids.py --all

# Check for collisions
python vault_generate_ids.py --check-collisions

# Validate all IDs
python vault_generate_ids.py --validate
```

**Exit Codes**:
- `0`: Success
- `1`: Error (collision, invalid format, etc.)
- `2`: Validation warning (non-blocking)

---

## Audit Log

**Log Entry** (per ID generated):
```json
{
  "timestamp": "2026-07-17T10:30:00Z",
  "filepath": "concepts/FINANCIAL_RULES.md",
  "type": "concept",
  "generated_id": "concept:financial-rules",
  "action": "add",
  "previous_id": null
}
```

**Log Entry** (collision detected):
```json
{
  "timestamp": "2026-07-17T10:30:05Z",
  "error": "collision",
  "id": "concept:financial-rules",
  "files": [
    "concepts/FINANCIAL_RULES.md",
    "archive/FINANCIAL_RULES_old.md"
  ]
}
```

---

**End of Stable ID Specification**

**Status**: Normative. All implementations MUST follow this algorithm exactly.
