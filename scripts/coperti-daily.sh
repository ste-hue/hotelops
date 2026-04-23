#!/bin/bash
# Coperti daily ingest — wipe + full reload from Google Sheet.
# Google Sheet è source-of-truth authoritative: ogni run rimpiazza
# completamente f_coperti_giornalieri.
#
# Schedulato via launchd (~/Library/LaunchAgents/it.panoramagroup.hotelops-coperti.plist)
# Lock file impedisce re-run nella stessa giornata.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$HOME/.virtualenvs/hotelops_core/bin/python"
LOCK_DIR="/tmp/hotelops-coperti"
LOCKFILE="${LOCK_DIR}/$(date +%Y%m%d).lock"
LOGFILE="${LOCK_DIR}/coperti-$(date +%Y%m%d).log"

mkdir -p "$LOCK_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

if [ -f "$LOCKFILE" ]; then
    echo "$(ts) Lock present ($LOCKFILE) — already ran today, skipping." >> "$LOGFILE"
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

echo "$(ts) Starting coperti ingest..." >> "$LOGFILE"

if "$PYTHON" -m ingest.flussi.ingest_coperti --gsheet --replace >> "$LOGFILE" 2>&1; then
    touch "$LOCKFILE"
    echo "$(ts) Ingest completed successfully." >> "$LOGFILE"
else
    rc=$?
    echo "$(ts) Ingest FAILED (exit $rc). Will retry at next scheduled time." >> "$LOGFILE"
    exit "$rc"
fi

find "$LOCK_DIR" -name "*.lock" -mtime +7 -delete 2>/dev/null || true
find "$LOCK_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
