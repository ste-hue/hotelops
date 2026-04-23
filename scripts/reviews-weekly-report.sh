#!/bin/bash
# Reviews weekly report — send once per ISO week.
# Launchd fires Monday 8:00 / 12:00 / 18:00; week-lock ensures a single send.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$HOME/.virtualenvs/hotelops_core/bin/python"
LOCK_DIR="/tmp/hotelops-reviews"
WEEK_TAG="$(date +%G-W%V)"
LOCKFILE="${LOCK_DIR}/weekly-${WEEK_TAG}.lock"
LOGFILE="${LOCK_DIR}/report-$(date +%Y%m%d).log"

mkdir -p "$LOCK_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

if [ -f "$LOCKFILE" ]; then
    echo "$(ts) Lock present ($LOCKFILE) — report già inviato per ${WEEK_TAG}, skipping." >> "$LOGFILE"
    exit 0
fi

if [ ! -x "$PYTHON" ]; then
    echo "$(ts) ABORT: python not found at $PYTHON. Check venv path." >> "$LOGFILE"
    exit 1
fi

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
else
    echo "$(ts) WARN: .env missing at $PROJECT_DIR/.env — credenziali potrebbero non essere caricate." >> "$LOGFILE"
fi

cd "$PROJECT_DIR"

echo "$(ts) Sending weekly report (${WEEK_TAG})..." >> "$LOGFILE"
if "$PYTHON" -m cli reviews --report >> "$LOGFILE" 2>&1; then
    touch "$LOCKFILE"
    echo "$(ts) Report sent." >> "$LOGFILE"
else
    rc=$?
    echo "$(ts) Report FAILED (exit $rc). Will retry at next scheduled time." >> "$LOGFILE"
    exit "$rc"
fi

find "$LOCK_DIR" -name "weekly-*.lock" -mtime +60 -delete 2>/dev/null || true
