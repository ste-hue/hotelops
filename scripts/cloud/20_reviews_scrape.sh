#!/usr/bin/env bash
# Task 2 — reviews-scrape su Cloud Run Job + Cloud Scheduler.
# Uso: scripts/cloud/20_reviews_scrape.sh [IMAGE_TAG]   (default: v1)
set -euo pipefail

PROJECT=hotelops-suite
REGION=europe-west1
TAG="${1:-v1}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/hotelops/jobs:${TAG}"
JOBS_SA="hotelops-jobs@${PROJECT}.iam.gserviceaccount.com"

gcloud run jobs create reviews-scrape --project="$PROJECT" --region="$REGION" \
  --image="$IMAGE" --service-account="$JOBS_SA" \
  --command=python --args=-m,cli,reviews,--scrape \
  --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest,APIFY_API_TOKEN=apify-api-token:latest \
  --max-retries=2 --task-timeout=900s

gcloud run jobs add-iam-policy-binding reviews-scrape --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:${JOBS_SA}" --role=roles/run.invoker

gcloud scheduler jobs create http reviews-scrape-daily --project="$PROJECT" --location="$REGION" \
  --schedule="0 7 * * *" --time-zone="Europe/Rome" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/reviews-scrape:run" \
  --http-method=POST \
  --oauth-service-account-email="${JOBS_SA}"

echo "reviews-scrape: Job + Scheduler creati."
