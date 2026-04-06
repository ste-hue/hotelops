#!/bin/bash
# Reviews weekly report — send every Monday morning.
#
# Crontab:
#   0 8 * * 1  /path/to/hotelops/scripts/reviews-weekly-report.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOGFILE="/tmp/hotelops-reviews/report-$(date +%Y%m%d).log"

mkdir -p /tmp/hotelops-reviews

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR"

echo "$(date '+%Y-%m-%d %H:%M:%S') Sending weekly report..." >> "$LOGFILE"
hotelops reviews --report >> "$LOGFILE" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S') Report sent." >> "$LOGFILE"
