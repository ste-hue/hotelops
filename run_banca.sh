#!/bin/bash
set -e

DATAHUB="/Users/stefanodellapietra/Library/CloudStorage/GoogleDrive-stefano@panoramagroup.it/My Drive/hotelops_datahub"
STAGING="$HOME/.cache/hotelops/tesoreria_staging"
ACCODAMENTI_STAGING="$HOME/.cache/hotelops/accodamenti_staging"

cd /Users/stefanodellapietra/dev/Projects/hotelops

echo "=== STEP 1 — SYNC banca (rclone) ==="
python -m pipelines.banca.fetch_drive --staging "$STAGING"

echo ""
echo "=== STEP 2 — INGEST banca → f_banche_movimenti (BigQuery) ==="
python -m pipelines.banca.ingest --datahub "$DATAHUB" --source "$STAGING"

echo ""
echo "=== STEP 3 — INGEST accodamenti Esolver → f_ledger_movimenti (BigQuery + CSV) ==="
python -m pipelines.banca.ingest_accodamenti \
    --datahub "$DATAHUB" \
    --staging "$ACCODAMENTI_STAGING"

echo ""
echo "=== DONE ==="
