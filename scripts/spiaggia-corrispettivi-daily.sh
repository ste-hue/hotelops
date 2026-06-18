#!/bin/bash
# Spiaggia — pull giornaliero del Registro Corrispettivi dal Drive vivo.
# amministrazione aggiorna il file ogni giorno; questo lo pesca via service
# account → intake → promote. Idempotente: il content-hash dedup dell'intake
# rende un file invariato un no-op, quindi è sicuro girare più volte al giorno.
#
# Crontab example (qualche volta/giorno per prendere gli aggiornamenti in corso):
#   0 9 * * *   /path/to/hotelops/scripts/spiaggia-corrispettivi-daily.sh
#   0 14 * * *  /path/to/hotelops/scripts/spiaggia-corrispettivi-daily.sh
#   0 20 * * *  /path/to/hotelops/scripts/spiaggia-corrispettivi-daily.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$HOME/.virtualenvs/hotelops_core/bin/python"
LOG_DIR="/tmp/hotelops-spiaggia"
LOGFILE="${LOG_DIR}/corrispettivi-$(date +%Y%m%d).log"
SOURCE="RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT"

mkdir -p "$LOG_DIR"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

if [ ! -x "$PYTHON" ]; then
    echo "$(ts) ABORT: python non trovato a $PYTHON. Controlla la venv." >> "$LOGFILE"
    exit 1
fi

if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$PROJECT_DIR"

echo "$(ts) Pull registro corrispettivi spiaggia dal Drive ($SOURCE)..." >> "$LOGFILE"

if "$PYTHON" -m ingest.drive_fetch --source-name "$SOURCE" >> "$LOGFILE" 2>&1; then
    echo "$(ts) OK." >> "$LOGFILE"
else
    rc=$?
    echo "$(ts) FAILED (exit $rc)." >> "$LOGFILE"
    exit "$rc"
fi

find "$LOG_DIR" -name "*.log" -mtime +30 -delete 2>/dev/null || true
