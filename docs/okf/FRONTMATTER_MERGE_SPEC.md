# Frontmatter Merge Specification — HotelOps OKF Lite

**Version**: 1.1
**Date**: 2026-07-17
**Status**: Normative
**Scope**: All frontmatter modification operations

**v1.1 changes**: Replaced the parse/re-serialize algorithm (v1.0) with a **line-preserving insertion algorithm**. v1.0 re-serialized the entire frontmatter (alphabetical key order, block-style lists, comment loss), which contradicted the approved REVISED_PILOT_PLAN expected outputs (existing fields preserved in original order and formatting, new fields inserted after `type`). v1.1 produces exactly the pilot plan's expected files. Also: malformed-YAML policy is now unambiguously strict-fail, and silent line-ending normalization is removed (contradicted INV-001/INV-014).

---

## Purpose

This document defines the **exact algorithm** for merging OKF metadata into existing markdown files.

**Implementation MUST follow this specification exactly.**

Two implementations of this spec MUST produce byte-identical files.

---

## Design Principle: Touch Nothing You Don't Own

Migration manages exactly **three keys**: `type`, `id`, `authority` (the "managed keys").

Every other byte of the file — body, existing frontmatter lines, comments, quoting style, flow-style lists, key order, blank lines — is **preserved byte-for-byte**. The algorithm operates on **lines**, not on a parsed-and-reserialized YAML document. YAML parsing is used **read-only** (to inspect values and validate); it never drives serialization of existing content.

**Consequences** (all deliberate):
- YAML comments are preserved (v1.0 lost them)
- Existing flow-style lists (`applies_to: [INTUR, ORTI]`) stay flow-style
- Existing unquoted dates (`date: 2026-05-18`) stay unquoted
- Existing key order is untouched; no alphabetical reordering
- Idempotence and determinism are trivial: a compliant file is returned byte-identical

---

## Definitions

**Frontmatter block**: Present if and only if the file's content begins with the exact four bytes `---\n` at **byte 0**. The block ends at the first subsequent line that is exactly `---` (the closing fence). A `---` block appearing anywhere else in the file (e.g., after a heading — see `concepts/FINANCIAL_RULES.md`, whose `---` block sits *below* the H1) is **body**, not frontmatter, and is never touched.

**Frontmatter lines**: The lines strictly between the opening and closing fences.

**Managed keys**: `type`, `id`, `authority`.

**Managed line**: A frontmatter line matching the regex `^(type|id|authority):` (key at column 0 — nested/indented occurrences do not count).

---

## Algorithm

```
Input:  filepath
        new_metadata = {type: <from classification>, id: <from STABLE_ID_SPEC>,
                        authority: <type-default from profile>}
        (new_metadata contains ONLY managed keys — never anything else)
Output: modified file, or no-op, or typed error

1. Read file (strict UTF-8, no newline translation)
2. Reject non-conforming files (encoding, BOM, line endings)
3. Case A (no frontmatter): prepend a new frontmatter block
4. Case B (frontmatter exists): read-only validate, then line-level insert/replace
5. Write file (strict UTF-8, no newline translation)
6. Validate invariants (INV-001: body byte-identical)
```

---

### Step 1 — Read

```python
def read_file(filepath):
    with open(filepath, 'rb') as f:
        raw = f.read()
    return raw
```

Read as **bytes** first. All checks in Step 2 operate on bytes.

---

### Step 2 — Reject Non-Conforming Files

Checked in this order; first failure wins. These are **errors, never silent fixes**. (Pre-flight validation — VAL-E-010/VAL-E-011 — should have caught them already; this is defense in depth.)

| Code | Condition | Behavior |
|------|-----------|----------|
| FM-E-001 | `raw` does not decode as UTF-8 | Skip file, log ERROR, exit code 1 at end of run |
| FM-E-002 | `raw` starts with UTF-8 BOM (`EF BB BF`) | Skip file, log ERROR (BOM would break byte-0 fence detection) |
| FM-E-003 | `raw` contains `\r` (CR or CRLF line endings) | Skip file, log ERROR. **Never normalize silently** — normalization changes body bytes and violates INV-001. The only sanctioned normalization is the explicit, user-invoked `vault_lint.py --fix`, run *before* migration. |

After these checks: `content = raw.decode('utf-8')`. Then `lines = content.split('\n')`. (Note: `'\n'.join(lines)` reconstructs `content` exactly — the final-newline behavior of the original file round-trips with no special handling.)

---

### Step 3 — Case A: No Frontmatter

**Condition**: `content` does not start with `---\n` (this includes empty files and the mid-file-fence case like FINANCIAL_RULES.md).

**Action**: Prepend a new frontmatter block, in this exact fixed order:

```
---\n
type: {type}\n
id: {id}\n
authority: {authority}\n
---\n
{original content, byte-identical}
```

i.e. `new_content = f"---\ntype: {t}\nid: {i}\nauthority: {a}\n---\n" + content`.

**Inserted-line format** (applies everywhere in this spec): `{key}: {value}` — single space after the colon, no quotes, no trailing whitespace. All managed values (`type` enum values, `type:slug` IDs, authority enum values) are safe YAML plain scalars — a colon followed immediately by a non-space character does not need quoting.

This reproduces the REVISED_PILOT_PLAN expected output for IDENTITY.md exactly.

---

### Step 4 — Case B: Frontmatter Exists

**Condition**: `content` starts with `---\n`.

#### 4.1 Locate the closing fence

```python
closing_idx = None
for i in range(1, len(lines)):
    if lines[i] == '---':
        closing_idx = i
        break
```

If `closing_idx is None` → **FM-E-004: unterminated frontmatter fence**. Skip file, log ERROR. (Do NOT fall back to treating the file as body — v1.0's fail-safe produced a second frontmatter block on top of the broken one.)

`fm_lines = lines[1:closing_idx]` — these are the frontmatter lines.

#### 4.2 Read-only YAML validation

```python
try:
    fm_dict = yaml.safe_load('\n'.join(fm_lines)) or {}
except yaml.YAMLError:
    # FM-E-005
```

FM-E-005: **malformed YAML → skip file, log ERROR, require manual fix**. This is the single normative policy. (v1.0 described both a fail-safe and a strict option; the fail-safe is withdrawn.)

If `fm_dict` is not a dict (e.g., the frontmatter is a bare list or scalar) → FM-E-005 as well.

`fm_dict` is used **only** to read the current values of managed keys. It is never re-serialized.

#### 4.3 Duplicate managed keys

Count managed lines per key: if `type`, `id`, or `authority` appears **more than once** at column 0 within `fm_lines` → **FM-E-006: duplicate managed key**. Skip file, log ERROR, manual fix. (YAML's "last wins" would make the line-level edit ambiguous.) Duplicates of *non-managed* keys are the user's business — untouched, no error.

#### 4.4 The `type` operation

Let `existing_type = fm_dict.get('type')` and `VALID_TYPES` = the 9-value enum.

- **Missing** → insert `type: {new}` as the **first frontmatter line** (immediately after the opening fence).
- **Present and valid** (`existing_type in VALID_TYPES`) → untouched, even if it differs from the classification's proposal. Log INFO if it differs.
- **Present and invalid** → look up `existing_type` in the **Type Normalization Table** (OKF_LITE_IMPLEMENTATION_SPEC.md § File Classification Rules). If found → **replace the entire `type:` line** with `type: {normalized}`. Any trailing comment on that one line is lost — log WARN. If not in the table → **FM-E-007: unknown legacy type**, skip file, human review.

#### 4.5 The `id` and `authority` operations

- **`id` exists**: preserved **only if it passes all three checks**:
  1. **Syntactically valid** — matches the enum-anchored ID pattern (STABLE_ID_SPEC.md)
  2. **Type-consistent** — its prefix equals the file's resolved `type`
  3. **Unique** — no other in-scope file carries the same `id` (checked against the run's ID registry)

  All three pass → untouched (ID stability; the slug may legitimately differ from the filename-derived slug, e.g. after a rename). Any check fails → **FM-E-008: unpreservable existing id** — skip the file for human review. **Never silently overwrite an existing `id`.**
- **`authority` exists** (any value) → never overwrite, untouched (user-customized authority respected; VAL-W-002 warns on invalid values, non-blocking).
- If **missing** → insert immediately **after the `type:` line**, preserving the relative order `type`, `id`, `authority`:
  - `id` inserts at position `T+1` (where `T` = index of the `type:` line within the file's lines)
  - `authority` inserts after `id` if `id` was just inserted or already sits at `T+1`; otherwise directly after `type:`. Equivalent deterministic formulation: build the list `to_insert` = the missing keys among `[id, authority]` in that order, with their values, and splice it at `T+1`.

Existing managed keys located elsewhere in the frontmatter are **not moved**.

#### 4.6 No other writes

`new_metadata` never contains non-managed keys, so **conflicting values for non-managed keys cannot occur** — migration has no opinion on them. Every non-managed line is byte-identical in the output.

---

### Step 5 — Write

```python
def write_file(filepath, new_content):
    with open(filepath, 'wb') as f:
        f.write(new_content.encode('utf-8'))
```

Write bytes. UTF-8, no BOM, no newline translation (INV-014).

**No-op check**: if `new_content == content`, do not write; report `skip (already compliant)`. Required for idempotence (INV-009) and clean Git diffs.

---

### Step 6 — Validate

Post-write, assert INV-001: the body (all lines after the closing fence; entire file if Case A input) is byte-identical to the input's body. On violation → rollback the file immediately (ROLLBACK_SPEC.md), log incident.

---

## Conflict Resolution Summary

| Key | Existing value | Action |
|-----|----------------|--------|
| `type` | absent | Insert (first frontmatter line) |
| `type` | valid enum | Preserve (log INFO if ≠ classification proposal) |
| `type` | invalid, in normalization table | Replace line in place |
| `type` | invalid, not in table | FM-E-007 → human review |
| `id` | absent | Insert after `type` |
| `id` | present, valid + type-consistent + unique | Preserve |
| `id` | present, failing any of those checks | **FM-E-008 → human review (never silently overwrite)** |
| `authority` | absent | Insert after `id`/`type` |
| `authority` | present (any value) | **Never overwrite** |
| any other key | anything | **Never written, never deleted, never reordered** |

---

## Worked Examples (= pilot expected outputs)

### Example 1 — No frontmatter (IDENTITY.md)

Input starts `# HotelOps — Identity`. Metadata: `type: constitutional`, `id: constitutional:identity`, `authority: canonical`.

Output:
```markdown
---
type: constitutional
id: constitutional:identity
authority: canonical
---
# HotelOps — Identity
...
```

### Example 2 — Existing valid frontmatter (decisions/2026-05-18_PF_Rotate_Design.md)

Input frontmatter:
```yaml
---
type: decision
date: 2026-05-18
status: accepted
related_commits: []
---
```

Output (id + authority inserted after `type`; `date` stays unquoted; `related_commits: []` stays flow-style):
```yaml
---
type: decision
id: decision:2026-05-18-pf-rotate-design
authority: historical
date: 2026-05-18
status: accepted
related_commits: []
---
```

### Example 3 — Existing frontmatter, long free-text values (workstreams/HUB.md)

Input frontmatter:
```yaml
---
type: workstream_hub
workstream_id: hub
status: active
phase: Phase 3 (superficie di consegna — parallelizzabile, non spiazza la spina cash_control)
last_refresh: 2026-06-14
---
```

Output: `id: workstream_hub:hub` and `authority: working` inserted after `type:`; the `phase:` line (em-dash, parentheses and all) byte-identical.

### Example 4 — Invalid type replacement

Input frontmatter:
```yaml
---
type: business_logic
category: financial
applies_to: [INTUR, ORTI]
last_updated: 2026-06-01
---
```

`business_logic` → `concept` per the Type Normalization Table. Output:
```yaml
---
type: concept
id: concept:financial-rules
authority: canonical
category: financial
applies_to: [INTUR, ORTI]
last_updated: 2026-06-01
---
```

**Reality note (normative deviation from REVISED_PILOT_PLAN):** in the actual vault, `concepts/FINANCIAL_RULES.md` has its `---` block **below the H1 heading**, so it is *not* frontmatter (fence is not at byte 0). The pilot plan's "Before" snippet assumed otherwise. Actual pilot behavior for this file is **Case A**: a new frontmatter block (`type: concept`, `id`, `authority`) is prepended, and the legacy mid-file block remains in the body, byte-identical (INV-001). Cleaning up the legacy block is a **manual, post-pilot, human decision** — never automated (INV-013). The pilot reviewer must expect this and not flag it as corruption. Example 4 above still applies to any file whose invalid `type` sits in a *real* (byte-0) frontmatter block.

### Example 5 — Empty frontmatter

Input `---\n---\n# Doc\n` → type missing → insert at top:
```markdown
---
type: concept
id: concept:doc
authority: canonical
---
# Doc
```

### Example 6 — Comments preserved

Input:
```yaml
---
type: concept
# reviewed by Rosa 2026-06
tags: [finance, core]
---
```
Output inserts `id`/`authority` after `type:`; the comment line and flow-style `tags` are byte-identical. (v1.0 destroyed both.)

---

## Policies (template checklist)

- **No frontmatter** → Case A (Step 3).
- **Frontmatter exists** → Case B (Step 4).
- **Unknown keys** → never deleted, never modified, never reordered. Obsidian-native keys (`tags`, `aliases`, `cssclass`, `publish`) and any custom field survive untouched.
- **Duplicated keys** → duplicated *managed* keys: FM-E-006, manual fix. Duplicated non-managed keys: out of scope, untouched.
- **Conflicting values** → per the Conflict Resolution Summary; migration only ever writes managed keys.
- **Ordering** → existing lines keep their order. Inserted managed keys appear in fixed order `type`, `id`, `authority` at the top of the block (after an existing `type:` line, wherever it is). No global reordering.
- **YAML formatting** → inserted lines use `key: value` plain-scalar form (single space, no quotes, 0-column keys). Existing lines: formatting untouched, whatever it is.
- **Newline policy** → LF only, enforced by rejection (FM-E-003), never by conversion. Original presence/absence of a trailing final newline round-trips exactly (split/join on `\n`).
- **Comments** → preserved, with one documented exception: a replaced invalid `type:` line loses its own trailing comment (WARN logged).
- **Encoding** → strict UTF-8 in and out, BOM rejected (FM-E-002), no escaping of non-ASCII (`Romità`, `✅` pass through as raw UTF-8 since their lines are never rewritten).

---

## Error Codes

| Code | Meaning | Behavior |
|------|---------|----------|
| FM-E-001 | Not UTF-8 | Skip file, ERROR |
| FM-E-002 | UTF-8 BOM present | Skip file, ERROR |
| FM-E-003 | CR/CRLF line endings | Skip file, ERROR (fix via explicit `vault_lint.py --fix` first) |
| FM-E-004 | Opening fence without closing fence | Skip file, ERROR |
| FM-E-005 | Frontmatter YAML malformed / not a mapping | Skip file, ERROR, manual fix |
| FM-E-006 | Duplicate managed key (`type`/`id`/`authority`) | Skip file, ERROR, manual fix |
| FM-E-007 | Invalid `type` not in normalization table | Skip file, ERROR, human review |
| FM-E-008 | Existing `id` not preservable (syntax / type mismatch / duplicate) | Skip file, ERROR, human review |

**Interaction with the transaction model** (OKF_LITE_IMPLEMENTATION_SPEC.md § Transaction Model): during the *dry-run inventory*, FM-E-00x conditions flag files for human review and exclude them from the batch. During a *live batch*, any FM-E-00x on a batch member is an error → **the whole batch is rolled back** (it means the frozen inventory was stale). A skipped/rolled-back file is left byte-identical.

---

## Reference Implementation

```python
import re
import yaml

VALID_TYPES = {
    'constitutional', 'concept', 'architecture', 'decision',
    'session', 'loop', 'workstream_hub', 'vertical', 'log'
}

MANAGED_LINE = re.compile(r'^(type|id|authority):')

def merge_frontmatter(filepath, new_metadata, type_normalization_table,
                      id_registry):
    """
    new_metadata: {'type': ..., 'id': ..., 'authority': ...} — managed keys only.
    id_registry: run-wide map id -> filepath (for the uniqueness check, FM-E-008).
    Returns: 'modified' | 'noop' | ('error', 'FM-E-00x')
    """
    raw = open(filepath, 'rb').read()

    # Step 2 — rejections
    try:
        content = raw.decode('utf-8')
    except UnicodeDecodeError:
        return ('error', 'FM-E-001')
    if raw.startswith(b'\xef\xbb\xbf'):
        return ('error', 'FM-E-002')
    if b'\r' in raw:
        return ('error', 'FM-E-003')

    if not content.startswith('---\n'):
        # Step 3 — Case A
        block = (f"---\ntype: {new_metadata['type']}\n"
                 f"id: {new_metadata['id']}\n"
                 f"authority: {new_metadata['authority']}\n---\n")
        new_content = block + content
    else:
        # Step 4 — Case B
        lines = content.split('\n')
        closing = next((i for i in range(1, len(lines)) if lines[i] == '---'), None)
        if closing is None:
            return ('error', 'FM-E-004')
        fm_lines = lines[1:closing]

        try:
            fm_dict = yaml.safe_load('\n'.join(fm_lines))
        except yaml.YAMLError:
            return ('error', 'FM-E-005')
        fm_dict = fm_dict or {}
        if not isinstance(fm_dict, dict):
            return ('error', 'FM-E-005')

        for key in ('type', 'id', 'authority'):
            if sum(1 for l in fm_lines if l.startswith(key + ':')) > 1:
                return ('error', 'FM-E-006')

        # type operation
        existing_type = fm_dict.get('type')
        type_line_idx = next(
            (i for i in range(1, closing) if lines[i].startswith('type:')), None)
        if existing_type is None or type_line_idx is None:
            lines.insert(1, f"type: {new_metadata['type']}")
            closing += 1
            type_line_idx = 1
        elif str(existing_type) not in VALID_TYPES:
            if str(existing_type) not in type_normalization_table:
                return ('error', 'FM-E-007')
            lines[type_line_idx] = f"type: {type_normalization_table[str(existing_type)]}"
        # else: valid → untouched

        # id preservation checks (FM-E-008) — see §4.5
        if 'id' in fm_dict:
            existing_id = str(fm_dict['id'])
            resolved_type = new_metadata['type']
            if (not valid_id_format(existing_id)                       # syntax
                    or existing_id.split(':')[0] != resolved_type      # type-consistent
                    or id_registry.get(existing_id, filepath) != filepath):  # unique
                return ('error', 'FM-E-008')

        # id / authority insertion (fixed relative order after the type line)
        to_insert = []
        if 'id' not in fm_dict:
            to_insert.append(f"id: {new_metadata['id']}")
        if 'authority' not in fm_dict:
            to_insert.append(f"authority: {new_metadata['authority']}")
        lines[type_line_idx + 1:type_line_idx + 1] = to_insert

        new_content = '\n'.join(lines)

    if new_content == content:
        return 'noop'

    # INV-001 assertion before writing
    assert _body(new_content) == _body(content), 'INV-001 violation'
    open(filepath, 'wb').write(new_content.encode('utf-8'))
    return 'modified'

def _body(content):
    if not content.startswith('---\n'):
        return content
    lines = content.split('\n')
    for i in range(1, len(lines)):
        if lines[i] == '---':
            return '\n'.join(lines[i + 1:])
    return content
```

(Note: `_body` on the Case A *input* returns the whole file, and on the Case A *output* returns everything after the new closing fence — which is the whole original file. The assertion therefore checks exactly INV-001 in both cases.)

---

## Testing Specification

**Unit tests required** (each asserts byte-exact output):

1. No frontmatter → block prepended, order `type,id,authority` (Example 1)
2. Empty frontmatter → keys inserted (Example 5)
3. Valid frontmatter → `id`/`authority` inserted after `type`, everything else byte-identical (Example 2)
4. Invalid type in normalization table → single line replaced (Example 4)
5. Invalid type NOT in table → FM-E-007, file untouched
6. Unknown keys, comments, flow-style lists, unquoted dates → byte-preserved (Example 6)
7. Mid-file `---` block (FINANCIAL_RULES layout) → treated as Case A, legacy block preserved in body
8. Existing `id`, valid + type-consistent + unique but ≠ filename-derived slug → preserved
8b. Existing `id` malformed, or type-mismatched, or duplicated → FM-E-008, file untouched, human review
9. Duplicate `type:` lines → FM-E-006, file untouched
10. Unterminated fence → FM-E-004, file untouched
11. Malformed YAML → FM-E-005, file untouched
12. CRLF file → FM-E-003, file untouched
13. BOM file → FM-E-002, file untouched
14. File without trailing final newline → round-trips without gaining one
15. Idempotence: `merge(merge(X)) == merge(X)` byte-identical, second call returns `noop`
16. Determinism: two runs on identical input → byte-identical outputs

**Integration tests**: the 4 pilot files (expected outputs above), plus 10 random Tier 1 and 20 random Tier 2 files (INV-001…INV-007 assertions).

---

**End of Frontmatter Merge Specification**

**Status**: Normative. Implementations MUST match this algorithm exactly (byte-for-byte outputs).
