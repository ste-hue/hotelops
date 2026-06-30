#!/usr/bin/env bash
# Task 3 — reviews-report (settimanale) su Cloud Run Job + Cloud Scheduler.
# Uso: scripts/cloud/30_reviews_report.sh [IMAGE_TAG]   (default: v1)
set -euo pipefail

PROJECT=hotelops-suite
REGION=europe-west1
TAG="${1:-v1}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/hotelops/jobs:${TAG}"
JOBS_SA="hotelops-jobs@${PROJECT}.iam.gserviceaccount.com"

gcloud run jobs create reviews-report --project="$PROJECT" --region="$REGION" \
  --image="$IMAGE" --service-account="$JOBS_SA" \
  --command=python --args=-m,cli,reviews,--report \
  --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest,GMAIL_USER=gmail-user:latest,GMAIL_APP_PASSWORD=gmail-app-password:latest \
  --max-retries=2 --task-timeout=600s

gcloud run jobs add-iam-policy-binding reviews-report --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:${JOBS_SA}" --role=roles/run.invoker

gcloud scheduler jobs create http reviews-report-weekly --project="$PROJECT" --location="$REGION" \
  --schedule="0 8 * * 1" --time-zone="Europe/Rome" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/reviews-report:run" \
  --http-method=POST --oauth-service-account-email="${JOBS_SA}"

echo "reviews-report: Job + Scheduler creati."
