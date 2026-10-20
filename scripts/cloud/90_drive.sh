#!/usr/bin/env bash
# 90_drive.sh — Drive: un solo scrittore (drive-fetch --all) + inventario (drive-audit).
# Spec: docs/superpowers/specs/2026-10-17-drive-agent-friendly-design.md
#
# DRAFT — non eseguire prima di risolvere i blocchi della spec e ottenere
# autorizzazione separata per l'attivazione. Questo script non implementa ancora
# il provisioning del file privato HOTELOPS_DRIVE_MAP nel runtime.
# Verificare l'identità effettiva e l'accesso in sola lettura alle radici scelte.
# Nessun ID di documenti o cartelle privati viene distribuito con il codice.
#
# Uso futuro: scripts/cloud/90_drive.sh [TAG] (default v8, da verificare)
set -euo pipefail
PROJECT=hotelops-suite
REGION=europe-west1
TAG="${1:-v8}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/hotelops/jobs:${TAG}"
DRIVE_SA="drive-audit@${PROJECT}.iam.gserviceaccount.com"
JOBS_SA="hotelops-jobs@${PROJECT}.iam.gserviceaccount.com"
RUN_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs"

# 1) drive-fetch: tutte le sorgenti Drive del registry, ogni notte alle 04:30.
gcloud run jobs create drive-fetch --project="$PROJECT" --region="$REGION" \
  --image="$IMAGE" --service-account="$DRIVE_SA" \
  --command=python --args=-m,ingest.drive_fetch,--all \
  --set-env-vars=TZ=Europe/Rome \
  --max-retries=1 --task-timeout=1200s
gcloud run jobs add-iam-policy-binding drive-fetch --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:${JOBS_SA}" --role=roles/run.invoker
gcloud scheduler jobs create http drive-fetch-daily --project="$PROJECT" --location="$REGION" \
  --schedule="30 4 * * *" --time-zone="Europe/Rome" \
  --uri="${RUN_URI}/drive-fetch:run" --http-method=POST \
  --oauth-service-account-email="${JOBS_SA}"

# 2) drive-audit: fotografia dell'albero, ogni notte alle 05:00 (dopo il fetch,
#    così i file appena entrati hanno già il raw_object_id).
gcloud run jobs create drive-audit --project="$PROJECT" --region="$REGION" \
  --image="$IMAGE" --service-account="$DRIVE_SA" \
  --command=python --args=-m,ingest.drive_inventory \
  --set-env-vars=TZ=Europe/Rome \
  --max-retries=1 --task-timeout=1800s
gcloud run jobs add-iam-policy-binding drive-audit --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:${JOBS_SA}" --role=roles/run.invoker
gcloud scheduler jobs create http drive-audit-daily --project="$PROJECT" --location="$REGION" \
  --schedule="0 5 * * *" --time-zone="Europe/Rome" \
  --uri="${RUN_URI}/drive-audit:run" --http-method=POST \
  --oauth-service-account-email="${JOBS_SA}"

echo "drive-fetch + drive-audit: Job (keyless, drive-audit@) + Scheduler creati."
echo "Quando drive-fetch --all copre RT_CORRISPETTIVISPIAGGIA per un mese, spegnere spiaggia-corrispettivi (40)."
