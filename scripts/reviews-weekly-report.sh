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

if [ -f "$LOCKFILE" ]; then
    exit 0
fi

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') Sending weekly report (${WEEK_TAG})..." >> "$LOGFILE"
if "$PYTHON" -m cli reviews --report >> "$LOGFILE" 2>&1; then
    touch "$LOCKFILE"
    echo "$(date '+%Y-%m-%d %H:%M:%S') Report sent." >> "$LOGFILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') Report FAILED (exit $?). Will retry at next scheduled time." >> "$LOGFILE"
    exit 1
fi

find "$LOCK_DIR" -name "weekly-*.lock" -mtime +60 -delete 2>/dev/null || true
