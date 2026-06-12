#!/usr/bin/env bash
# Giardiniere notturno hotelops — lanciato da launchd alle 02:00 (o a mano per test).
set -euo pipefail

# launchd parte con PATH minimale: claude vive in ~/.local/bin, gh in /opt/homebrew/bin.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

REPO="$HOME/dev/Projects/hotelops"
LOG_DIR="$REPO/meta/gardener/logs"
LOG="$LOG_DIR/$(date +%Y-%m-%d_%H%M).log"
mkdir -p "$LOG_DIR"

exec >>"$LOG" 2>&1
echo "=== gardener run $(date) ==="

cd "$REPO"

# Prerequisiti: esci pulito se manca qualcosa (niente notti a metà).
command -v claude >/dev/null || { echo "ABORT: claude CLI mancante"; exit 1; }
command -v gh >/dev/null     || { echo "ABORT: gh CLI mancante"; exit 1; }
gh auth status >/dev/null    || { echo "ABORT: gh non autenticato"; exit 1; }
git fetch origin             || { echo "ABORT: fetch fallito (rete?)"; exit 1; }

# caffeinate: il Mac non dorme finché il run è vivo.
# --max-budget-usd al posto di --max-turns (rimosso dal CLI ≥2.1): guard anti-runaway.
# --allowedTools: in headless i Bash fuori allowlist vengono negati senza prompt;
#   il mandato (GARDENER.md) resta il limite di policy (mai push main, BQ read-only).
caffeinate -i claude -p "$(cat "$REPO/meta/gardener/GARDENER.md")" \
  --permission-mode acceptEdits \
  --max-budget-usd 20 \
  --allowedTools "Bash(git:*)" "Bash(gh:*)" "Bash(pytest:*)" "Bash(ruff:*)" "Bash(ls:*)" "Bash(cat:*)" "Bash(bq show:*)" \
    "Bash(.venv/bin/pytest:*)" "Bash(.venv/bin/ruff:*)" "Bash(python -m pytest:*)"

echo "=== gardener done $(date) ==="
