#!/bin/bash
# Reviews daily scrape — staggered retry.
# Schedule 5 times/day in crontab; only the first successful run
# actually scrapes. The rest are no-ops thanks to a daily lock file.
#
# Crontab example:
#   0 7 * * *   /path/to/hotelops/scripts/reviews-daily.sh
#   0 11 * * *  /path/to/hotelops/scripts/reviews-daily.sh
#   0 15 * * *  /path/to/hotelops/scripts/reviews-daily.sh
#   0 19 * * *  /path/to/hotelops/scripts/reviews-daily.sh
#   0 22 * * *  /path/to/hotelops/scripts/reviews-daily.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$HOME/.virtualenvs/hotelops_core/bin/python"
LOCK_DIR="/tmp/hotelops-reviews"
LOCKFILE="${LOCK_DIR}/$(date +%Y%m%d).lock"
LOGFILE="${LOCK_DIR}/reviews-$(date +%Y%m%d).log"

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

echo "$(ts) Starting reviews scrape..." >> "$LOGFILE"

if "$PYTHON" -m cli reviews --scrape >> "$LOGFILE" 2>&1; then
    touch "$LOCKFILE"
    echo "$(ts) Scrape completed successfully." >> "$LOGFILE"
else
    rc=$?
    echo "$(ts) Scrape FAILED (exit $rc). Will retry at next scheduled time." >> "$LOGFILE"
    exit "$rc"
fi

find "$LOCK_DIR" -name "*.lock" -mtime +7 -delete 2>/dev/null || true
find "$LOCK_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
