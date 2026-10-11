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
  `checkpoint.json`, `findings.json` (durable, never deleted, `open`/`resolved`),
  `last_report.md`.
- Exit code: `0` CURRENT · `1` findings or NOT VERIFIED · `2` a source was unavailable.
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

1. The vault working tree must be committed and pushed (today 14 files are
   modified locally; the cloud sees only `origin/master`).
2. A fine-grained PAT (read-only, `mgmt-os` contents) stored as the secret
   `MGMT_OS_READ_TOKEN` in the vault repo — or drop mgmt-os from the cloud run.
3. Copy `vault-loop.yml` to `.github/workflows/` of the vault repo and run it once
   by hand (`workflow_dispatch`).
