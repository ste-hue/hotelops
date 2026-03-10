#!/bin/bash
set -e

DATAHUB="/Users/stefanodellapietra/Library/CloudStorage/GoogleDrive-stefano@panoramagroup.it/My Drive/hotelops_datahub"
STAGING="$HOME/.cache/hotelops/tesoreria_staging"

cd /Users/stefanodellapietra/dev/Projects/hotelops

echo "=== SYNC (rclone) ==="
python -m pipelines.banca.fetch_drive --staging "$STAGING"

echo ""
echo "=== INGEST ==="
python -m pipelines.banca.ingest --datahub "$DATAHUB" --source "$STAGING"

echo ""
echo "=== DONE ==="
