#!/usr/bin/env bash
# Task 4 — spiaggia-corrispettivi su Cloud Run Job + Cloud Scheduler.
# KEYLESS: il job gira COME drive-audit@ (che ha già accesso al Drive) →
# nessun file-chiave SA. drive_fetch._drive_service usa ADC se manca il key-file.
# Uso: scripts/cloud/40_spiaggia.sh [IMAGE_TAG]   (default: v2)
set -euo pipefail

PROJECT=hotelops-suite
REGION=europe-west1
TAG="${1:-v2}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/hotelops/jobs:${TAG}"
DRIVE_SA="drive-audit@${PROJECT}.iam.gserviceaccount.com"
JOBS_SA="hotelops-jobs@${PROJECT}.iam.gserviceaccount.com"
SOURCE="RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT"

gcloud run jobs create spiaggia-corrispettivi --project="$PROJECT" --region="$REGION" \
  --image="$IMAGE" --service-account="$DRIVE_SA" \
  --command=python --args=-m,ingest.drive_fetch,--source-name,"$SOURCE" \
  --max-retries=2 --task-timeout=600s

gcloud run jobs add-iam-policy-binding spiaggia-corrispettivi --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:${JOBS_SA}" --role=roles/run.invoker

gcloud scheduler jobs create http spiaggia-corrispettivi-daily --project="$PROJECT" --location="$REGION" \
  --schedule="0 9 * * *" --time-zone="Europe/Rome" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/spiaggia-corrispettivi:run" \
  --http-method=POST --oauth-service-account-email="${JOBS_SA}"

echo "spiaggia-corrispettivi: Job (keyless, drive-audit@) + Scheduler creati."
