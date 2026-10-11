# Vault Loop — incremental reconciliation (design)

Date: 2026-10-11. Status: accepted for implementation in this branch.

## Problem

Vault Loop Mode C (Lint) is a manual, whole-vault pass executed by an agent on
Stefano's Mac. It has no memory between runs, so every pass re-reads everything,
cannot say "what changed since last time", and its success is indistinguishable
from "the agent ran". Nothing persists unresolved discrepancies.

## One canonical specification

`.claude/commands/vault-loop.md` stays the only specification of the three modes
(Bootstrap, Capture, Lint). This tool is the **deterministic subset of Mode C**,
runnable without an LLM. Semantic checks (Mode C check 9 and judgment calls)
stay with the agent; the tool only surfaces `REVIEW REQUIRED` items for them.
`.agents/skills/source-command-vault-loop/SKILL.md` is an adapter (PR #143).

## Scope

Tracked sources (config `meta/vault-loop/sources.yaml`):

| Source | Kind | Authority (per concept) |
| --- | --- | --- |
| `hotelops` | git repo (public) | technical rules, invariants, data contracts |
| `mgmt-os` | git repo (private) | management state engine, Regia direction |
| `vault` | git repo (private), subdir `HotelOps/` | reasoning memory, business ontology names (I3) |

BigQuery is a source in the spec but **not queried** by this tool: checks that
would need it report `NOT VERIFIED` with the reason. No runtime or GCP access.

## Checks (deterministic)

| ID | What | Result |
| --- | --- | --- |
| `source-availability` | each source resolves to a git HEAD; dirty working tree recorded | `SOURCE UNAVAILABLE` if missing; dirty → checkpoint not advanced |
| `vault-repo-pointers` | repo paths cited in vault notes exist in the hotelops checkout | dead pointer → `DRIFT DETECTED` |
| `invariant-range-claims` | vault text "I1–In" vs the number of `### In.` headings in `docs/architecture/INVARIANTS.md` | mismatch → `DRIFT DETECTED` |
| `archived-as-active` | `[[wikilink]]` whose only target lives under `_archive/` | → `DRIFT DETECTED` |
| `broken-wikilinks` | `[[wikilink]]` with no target in the vault | → `DRIFT DETECTED` (low) |
| `arch-changes-unreflected:<repo>` | commits since checkpoint touching watched paths (grouped by the PR that merged them) with no vault note citing the PR number or a touched file; open items are re-examined every run | → `REVIEW REQUIRED` |
| `archived-content-modified` | archived files or decisions older than 30 days whose hash changed since checkpoint | → `REVIEW REQUIRED` |
| `repo-docs-freshness` | reuse `scripts/check_docs_freshness.py` (`docs/procedures`, `docs/protocols`) | DEAD → `DRIFT DETECTED`, STALE → `REVIEW REQUIRED` |
| `bigquery-ontology-i3` | D_* values vs vault ontology | always `NOT VERIFIED` (no BigQuery in this tool); listed under Coverage, outside the roll-up |

Sessions (`sessions/`) and the archive are historical narrative: they are
scanned only by the hash check, never for pointer/claim checks.

## State and idempotence

State directory (`--state`, default `.hotelops_state/vault_loop/`, gitignored):

- `checkpoint.json` — per source: last verified SHA, dirty flag, verified_at;
  per check: last status. A source's SHA advances **only** when the source was
  available, its working tree was clean, and every check that reads it finished
  (status ≠ `NOT VERIFIED` for lack of data is fine; a crash is not).
- `findings.json` — stable IDs (`sha1(check|source|path|claim)`), `first_seen`,
  `last_seen`, `status` (`open` / `resolved`). A finding not reproduced in a run
  flips to `resolved` with `resolved_at`; it is never deleted.
- `last_report.md` — the report of the last run.

Two consecutive runs on unchanged sources produce the same finding IDs and states
(only `last_seen`/`verified_at` timestamps move) and the same checkpoint SHAs.

The tool never writes to any source. It never edits vault, repo or GitHub.

## Report

Markdown, written to `--out` and printed. Per source: status, SHA, dirty, whether
the checkpoint advanced and why not. Per check: status and count. Findings grouped
by status, each with id, source, authority, path, claim, proposed correction,
`approval: yes/no`. Text is scrubbed: anything that looks like a token, key,
`op://` reference or email is replaced by `[REDACTED]` and flagged. The report
cites paths and short claims only, never file bodies.

Overall status = worst of the sources/checks in the order
`SOURCE UNAVAILABLE` > `NOT VERIFIED` > `DRIFT DETECTED` > `REVIEW REQUIRED` > `CURRENT`
(a completed audit with open findings is not a reconciled system).

## Where it runs

Locally: `python -m scripts.vault_loop.reconcile` from the hotelops checkout,
sources resolved from `sources.yaml` defaults (`../mgmt_os`, `../obsidian/…`).

Cloud (Part 9 of the consolidation brief): GitHub Actions in the **private**
`ste-hue/obsidian-vault` repo (workflow template in `meta/vault-loop/`), because
hotelops is public and reports name vault files. Code is checked out from
hotelops; state is committed to a dedicated branch of the private repo. Weekly
cron present but disabled until Stefano approves. Not deployed by this branch.
