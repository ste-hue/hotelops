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
LOCK_DIR="/tmp/hotelops-reviews"
LOCKFILE="${LOCK_DIR}/$(date +%Y%m%d).lock"
LOGFILE="${LOCK_DIR}/reviews-$(date +%Y%m%d).log"

mkdir -p "$LOCK_DIR"

# Already ran successfully today? Skip.
if [ -f "$LOCKFILE" ]; then
    exit 0
fi

# Load env vars
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') Starting reviews scrape..." >> "$LOGFILE"

# Run the full pipeline: scrape -> normalize -> classify -> BQ -> alert
if hotelops reviews --scrape >> "$LOGFILE" 2>&1; then
    touch "$LOCKFILE"
    echo "$(date '+%Y-%m-%d %H:%M:%S') Scrape completed successfully." >> "$LOGFILE"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') Scrape FAILED (exit $?). Will retry at next scheduled time." >> "$LOGFILE"
    exit 1
fi

# Clean up lock files older than 7 days
find "$LOCK_DIR" -name "*.lock" -mtime +7 -delete 2>/dev/null || true
find "$LOCK_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
