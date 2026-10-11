---
name: source-command-vault-loop
description: Adapter for the canonical HotelOps Vault Loop. Use when asked to bootstrap, capture, lint, audit or reconcile Obsidian-vault and repository changes.
---

# Vault Loop adapter (single source of truth)

The **only maintained Vault Loop specification** is:

`.claude/commands/vault-loop.md` (repository root).

Before executing any Vault Loop mode, read that file **from the current checked-out revision** and follow its mode selection, source-authority rules, safeguards, and output contract. Do not use this adapter as a fallback copy of those instructions. If that canonical file cannot be loaded, stop and report that Vault Loop is unavailable; do not improvise a reconciliation.

The Obsidian vault is a separate local resource. No vault comparison may be claimed complete unless the actual authorized vault snapshot was available. Code-only analysis must be labelled as partial.
