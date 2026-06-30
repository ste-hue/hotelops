#!/usr/bin/env bash
# Task 0 — Bootstrap GCP per gli scheduled job cloud.
# Idempotente: ri-eseguibile (i create falliscono "ALREADY_EXISTS", innocuo).
# Prerequisito: API abilitate (secretmanager, cloudscheduler, artifactregistry,
# cloudbuild, run) — vedi sotto.
set -euo pipefail

PROJECT=hotelops-suite
REGION=europe-west1
JOBS_SA="hotelops-jobs@${PROJECT}.iam.gserviceaccount.com"

# --- API necessarie ---
gcloud services enable \
  secretmanager.googleapis.com cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com run.googleapis.com \
  --project="$PROJECT"

# --- Service account dedicato ai job ---
gcloud iam service-accounts create hotelops-jobs --project="$PROJECT" \
  --display-name="HotelOps Scheduled Jobs" || true
for ROLE in roles/bigquery.dataEditor roles/bigquery.jobUser roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${JOBS_SA}" --role="$ROLE" --condition=None
done

# --- Secret (valori dal .env locale, SOLO in questa shell) ---
set -a; source "$(git rev-parse --show-toplevel)/.env"; set +a
mksecret() { printf '%s' "$2" | gcloud secrets create "$1" --project="$PROJECT" --data-file=- || true; }
mksecret anthropic-api-key   "$ANTHROPIC_API_KEY"
mksecret apify-api-token     "$APIFY_API_TOKEN"
mksecret gmail-user          "$GMAIL_USER"
mksecret gmail-app-password  "$GMAIL_APP_PASSWORD"
for S in anthropic-api-key apify-api-token gmail-user gmail-app-password; do
  gcloud secrets add-iam-policy-binding "$S" --project="$PROJECT" \
    --member="serviceAccount:${JOBS_SA}" --role=roles/secretmanager.secretAccessor
done

# --- Artifact Registry ---
gcloud artifacts repositories create hotelops --project="$PROJECT" --location="$REGION" \
  --repository-format=docker --description="HotelOps images" || true

echo "Bootstrap completato."
