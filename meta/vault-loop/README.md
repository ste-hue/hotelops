# Vault Loop — incremental reconciliation

Deterministic subset of Vault Loop **Mode C (Lint)**. The specification of the
three modes is `.claude/commands/vault-loop.md` and nothing else; design notes in
`docs/superpowers/specs/2026-10-11-vault-loop-incremental-design.md`.

```bash
# from the hotelops checkout (siblings ../mgmt_os and ../obsidian/Obsidian Vault)
python -m scripts.vault_loop.reconcile                      # prints the report
python -m scripts.vault_loop.reconcile --out /tmp/report.md  # also writes it
VAULT_LOOP_PATH_VAULT=/elsewhere/Vault python -m scripts.vault_loop.reconcile
```

- Sources: `sources.yaml` (names and watched paths only, nothing private).
- State: `--state` dir, default `.hotelops_state/vault_loop/` (gitignored):
  `state.json` (atomic authoritative bundle), `checkpoint.json`, `findings.json` (durable, never deleted, `open`/`resolved`),
  `last_report.md`.
- Exit code: `0` CURRENT · `1` findings · `2` a source was unavailable · `3` incomplete checks or dirty snapshots.
- Read-only everywhere. It never edits vault, repos or GitHub.

Statuses: `CURRENT` · `DRIFT DETECTED` (mechanical contradiction) · `REVIEW REQUIRED`
(a human/agent must decide) · `SOURCE UNAVAILABLE` · `NOT VERIFIED` (a check could
not complete, or needs a system this tool does not touch, e.g. BigQuery).

A source's checkpoint advances only when it was available, its working tree was
clean and every check that reads it completed. A dirty tree is still checked but
its SHA is held, so unpushed edits are never silently skipped. `REVIEW REQUIRED`
items for repo commits stay open across checkpoints until a vault note cites the
PR or a touched file.

## Cloud run (not deployed — needs Stefano's approval)

`vault-loop.yml` is a GitHub Actions workflow meant for the **private**
`ste-hue/obsidian-vault` repository (hotelops is public and the report names vault
files). It checks out hotelops (public), mgmt-os (private, token needed) and the
vault itself, runs the tool, uploads the report as a workflow artifact and commits
state to the `vault-loop-state` branch of the private repo. The weekly cron is
present but commented out: enabling it is a decision, not a side-effect.

Prerequisites before the first cloud run:

1. Confirm the authoritative vault is committed and pushed; the runner only sees the remote
   snapshot. A historical count of local edits is not a current sync check.
2. A fine-grained PAT (read-only contents for `mgmt-os`, `mutui-tracker` and
   `panorama-businessplan`) stored as the secret
   `MGMT_OS_READ_TOKEN` in the vault repo. If the audit scope changes, update both
   the source registry and the checkouts explicitly; missing access is not an
   empty source or a completed audit.
3. Copy `vault-loop.yml` to `.github/workflows/` of the vault repo and run it once
   by hand (`workflow_dispatch`).

## Failure and evidence boundaries

A missing vault subdirectory, unreadable note, unavailable cross-repo target,
dirty dependency or unreachable revision holds dependent checkpoints. No
date-window fallback over missing history. Findings resolve only after their exact
check completes on clean snapshots; uncommitted notes cannot acknowledge a repo
revision. The first historical baseline also requires a clean vault. Historical
amendments remain visible against the unchanged hash baseline. Generic filenames
and unrelated PR numbers are not evidence that a commit was captured.

State writes are serialized with a local lock and committed as one atomic bundle.
The split JSON files and report are compatibility exports; a subsequent run restores
them from `state.json` after an interrupted export. Corrupt state stops the run,
never resets the baseline. Keep state/report private; regex redaction is not a
guarantee that arbitrary confidential prose is safe to publish. Runtime/BQ checks
remain explicitly NOT VERIFIED and outside the mechanical overall status.

The cloud template is restricted to the private vault repo, distinguishes an
authenticated missing state branch from failed access, and fails incomplete audits.
A report created by the current invocation is required before upload/persistence;
a crash with exit 1 cannot reuse a prior report as if it were a completed audit.
No schedule or deployment is enabled by this template. This tool detects drift;
it does not semantically reconcile or automatically edit business decisions.
