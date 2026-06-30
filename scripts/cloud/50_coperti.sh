#!/usr/bin/env bash
# Task 5 — coperti su Cloud Run Job + Cloud Scheduler.
# KEYLESS: gira COME drive-audit@ (accesso al Google Sheet). fetch_gsheet ora
# esporta via API Drive (niente rclone). Wipe+reload: --replace ricarica tutto
# il foglio (source-of-truth) in f_coperti_giornalieri.
# Uso: scripts/cloud/50_coperti.sh [IMAGE_TAG]   (default: v3)
set -euo pipefail

PROJECT=hotelops-suite
REGION=europe-west1
TAG="${1:-v3}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/hotelops/jobs:${TAG}"
DRIVE_SA="drive-audit@${PROJECT}.iam.gserviceaccount.com"
JOBS_SA="hotelops-jobs@${PROJECT}.iam.gserviceaccount.com"

gcloud run jobs create coperti --project="$PROJECT" --region="$REGION" \
  --image="$IMAGE" --service-account="$DRIVE_SA" \
  --command=python --args=-m,ingest.flussi.ingest_coperti,--gsheet,--replace \
  --max-retries=2 --task-timeout=600s

gcloud run jobs add-iam-policy-binding coperti --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:${JOBS_SA}" --role=roles/run.invoker

# Cadenza giornaliera (il locale girava 12/18/23 ma con lock = 1 load/giorno).
gcloud scheduler jobs create http coperti-daily --project="$PROJECT" --location="$REGION" \
  --schedule="0 12 * * *" --time-zone="Europe/Rome" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/coperti:run" \
  --http-method=POST --oauth-service-account-email="${JOBS_SA}"

echo "coperti: Job (keyless, drive-audit@) + Scheduler creati."
