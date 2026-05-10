# Vault Sync Bootstrap (Parallel Track)

## Scope

Independent docs-only track to align repo documentation with Obsidian usage without touching feature code.

## Repo -> Vault Mapping

- `docs/architecture/INVARIANTS.md` -> keep canonical in repo; vault should only keep archive/link pointer.
- `docs/architecture/AI_INSTRUCTIONS.md` -> keep canonical in repo; vault should reference it in bootstrap notes.
- `docs/architecture/DATA_ENGINEERING_RULES.md` -> repo technical governance; no full copy in vault.
- `STATUS.md` -> session memory in repo only; vault gets only long-lived decisions/ontology, not daily ops.
- `CLAUDE.md` -> repo mechanics and commands; vault should keep high-level platform framing, not command inventory.

## What To Capture In Vault (If Approved)

1. Decision note only if the promotion/parser interface mismatch becomes a lasting architectural rule.
   - Candidate file: `decisions/2026-05-06_Promotion_Parser_Interface_Contract.md`
   - Trigger: merged change that standardizes parser invocation contract.
2. Platform freshness update in `PLATFORM.md` metadata only (last updated + compact pointer to migrated repo canonicals).
   - Do not duplicate full table counts/command lists.
3. Optional bridge note in vault index linking "technical canonicals moved to repo":
   - `INVARIANTS`, `AI_INSTRUCTIONS`, `LE_3_DIMENSIONI`, procedures/protocols.

## What Not To Capture

- Temporary implementation details from the A2+B1 plan.
- Branch-local planning notes or WIP checklists.
- Per-run anomalies until they are either:
  - a strategic decision, or
  - a canonical ontology change.
- Any duplicate of repo-runbooks already stubbed in vault (`procedures/*`, `protocols/*`).

## Guardrails For Claude Parallel Work

- Work in docs-only branch/worktree.
- No feature code edits.
- Produce capture proposals first; wait for approval before writing vault files.
- Keep vault entries durable (6+ month relevance), skip operational noise.

## Suggested Prompt To Claude

```
Continue in your current task.
In parallel, create a docs-only mapping output:
- repo -> vault ownership map
- proposed captures (decision/invariant/ontology) with reason
- explicit "do not capture" list

Constraints:
- docs-only branch/worktree
- no feature code changes
- do not write vault files without approval
- prefer links/pointers over duplicated technical content
```
