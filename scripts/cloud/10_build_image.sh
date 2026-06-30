#!/usr/bin/env bash
# Task 1 — Build & push dell'immagine batch dei job su Artifact Registry.
# Uso: scripts/cloud/10_build_image.sh [TAG]   (default: v1)
set -euo pipefail

PROJECT=hotelops-suite
REGION=europe-west1
TAG="${1:-v1}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/hotelops/jobs:${TAG}"

cd "$(git rev-parse --show-toplevel)"

cat > /tmp/cloudbuild-jobs.yaml <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build','-f','Dockerfile.jobs','-t','${IMAGE}','.']
images: ['${IMAGE}']
EOF

gcloud builds submit --project="$PROJECT" --config=/tmp/cloudbuild-jobs.yaml .
echo "Immagine pubblicata: ${IMAGE}"
