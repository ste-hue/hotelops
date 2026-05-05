#!/usr/bin/env bash
# Idempotent provisioning of gs://hotelops-raw.
# Safe to re-run: each step is a no-op if state already matches.
set -euo pipefail

PROJECT="hotelops-suite"
BUCKET="hotelops-raw"
LOCATION="EU"

echo "→ Ensuring bucket gs://${BUCKET} (project=${PROJECT}, location=${LOCATION})…"
if gsutil ls -b "gs://${BUCKET}" >/dev/null 2>&1; then
  echo "  bucket already exists, skipping create"
else
  gcloud storage buckets create "gs://${BUCKET}" \
    --project="${PROJECT}" \
    --location="${LOCATION}" \
    --default-storage-class=STANDARD \
    --uniform-bucket-level-access \
    --public-access-prevention
fi

echo "→ Enabling Object Versioning…"
gcloud storage buckets update "gs://${BUCKET}" --versioning

echo "→ Enabling Autoclass with terminal class ARCHIVE…"
gcloud storage buckets update "gs://${BUCKET}" \
  --enable-autoclass \
  --autoclass-terminal-storage-class=ARCHIVE

echo "→ Verifying state…"
gcloud storage buckets describe "gs://${BUCKET}" \
  --format='value(name,versioning.enabled,autoclass.enabled,autoclass.terminalStorageClass,iamConfiguration.publicAccessPrevention,iamConfiguration.uniformBucketLevelAccess.enabled)'

echo "✓ Done. gs://${BUCKET} is ready."
