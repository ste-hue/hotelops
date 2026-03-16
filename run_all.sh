#!/bin/bash
# run_all.sh — ingest completo: banche + movimenti Esolver + accodamenti PMS
#
# Workflow:
#   1. Sync banche da Drive → ingest → f_banche_movimenti
#   2. Sync movimenti contabili Esolver da Drive → ingest → f_movimenti_contabili
#   3. Sync accodamenti PMS da Drive → ingest → f_accodamenti
#   4. Stampa ultime date per sapere cosa esportare la prossima volta
#
# Usage:
#   ./run_all.sh              # full run
#   ./run_all.sh --no-sync    # solo ingest (file già locali)
#   ./run_all.sh --dry-run    # parse senza scrivere su BQ

set -e

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
RECONCILIATION_DINO="/Users/stefanodellapietra/dev/Projects/reconciliation_dino"
if [ -d "$RECONCILIATION_DINO" ]; then
  export PYTHONPATH="$RECONCILIATION_DINO:${PYTHONPATH:-}"
fi

DATAHUB="/Users/stefanodellapietra/Library/CloudStorage/GoogleDrive-stefano@panoramagroup.it/My Drive/hotelops_datahub"
BANCA_STAGING="$HOME/.cache/hotelops/tesoreria_staging"
MOVIMENTI_STAGING="$HOME/.cache/hotelops/movimenti_staging"
ACCODAMENTI_STAGING="$HOME/.cache/hotelops/accodamenti_staging"

NO_SYNC=""
DRY_RUN=""
for arg in "$@"; do
  case $arg in
    --no-sync)  NO_SYNC="--no-sync" ;;
    --dry-run)  DRY_RUN="--dry-run" ;;
  esac
done

cd /Users/stefanodellapietra/dev/Projects/hotelops

echo "=========================================="
echo " HOTELOPS — INGEST COMPLETO"
echo " $(date '+%Y-%m-%d %H:%M')"
echo "=========================================="

# ── 1. BANCHE ──────────────────────────────────
echo ""
echo "=== [1/3] BANCHE → f_banche_movimenti ==="
if [ -z "$NO_SYNC" ]; then
  python -m pipelines.banca.fetch_drive --staging "$BANCA_STAGING"
fi
python -m pipelines.banca.ingest \
  --datahub "$DATAHUB" \
  --source "$BANCA_STAGING" \
  ${DRY_RUN}

# ── 2. MOVIMENTI CONTABILI ESOLVER ─────────────
echo ""
echo "=== [2/3] MOVIMENTI ESOLVER → f_movimenti_contabili ==="
python -m pipelines.amministrativa.ingest_movimenti_contabili \
  --datahub "$DATAHUB" \
  --staging "$MOVIMENTI_STAGING" \
  ${NO_SYNC} \
  ${DRY_RUN}

# ── 3. ACCODAMENTI PMS ─────────────────────────
echo ""
echo "=== [3/3] ACCODAMENTI PMS → f_accodamenti ==="
python -m pipelines.banca.ingest_accodamenti \
  --datahub "$DATAHUB" \
  --staging "$ACCODAMENTI_STAGING" \
  ${DRY_RUN}

# ── STATUS FINALE ──────────────────────────────
echo ""
echo "=========================================="
echo " ULTIME DATE — cosa scaricare dopo"
echo "=========================================="
bq query --use_legacy_sql=false --project_id=hotelops-suite \
  --format=pretty \
'SELECT * FROM hotelops.v_ultima_data ORDER BY fonte, societa_id, conto'

echo ""
echo "DONE $(date '+%Y-%m-%d %H:%M')"
