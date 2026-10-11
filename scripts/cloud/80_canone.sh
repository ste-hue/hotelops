#!/usr/bin/env bash
# Cruscotto canone ORTI → INTUR su Cloud Run Job + Cloud Scheduler.
# Ogni giorno rilegge gli osservati da BigQuery (sola lettura), rigenera la pagina
# e la pubblica nel KV del Worker `canone` (https://canone.panorama-host.com).
# I dati del BP NON stanno nell'immagine: secret `canone-model-inputs` montato come file.
# Uso: scripts/cloud/80_canone.sh [IMAGE_TAG]   (default: v7)
# Nuova versione del BP: gcloud secrets versions add canone-model-inputs --data-file=<model-inputs.json>
set -euo pipefail

PROJECT=hotelops-suite
REGION=europe-west1
TAG="${1:-v7}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/hotelops/jobs:${TAG}"
JOBS_SA="hotelops-jobs@${PROJECT}.iam.gserviceaccount.com"
ROOT="$(git rev-parse --show-toplevel)"

# --- Secret (valori dal .env locale e dal file BP, SOLO in questa shell, mai a video) ---
set -a; source "${ROOT}/.env"; set +a
printf '%s' "$CLOUDFLARE_API_TOKEN" | gcloud secrets create cloudflare-kv-token --project="$PROJECT" --data-file=- || true
printf '%s' "$CLOUDFLARE_ACCOUNT_ID" | gcloud secrets create cloudflare-account-id --project="$PROJECT" --data-file=- || true
gcloud secrets create canone-model-inputs --project="$PROJECT" \
  --data-file="${ROOT}/.hotelops_state/canone_sim/model-inputs.json" || true
for S in cloudflare-kv-token cloudflare-account-id canone-model-inputs; do
  gcloud secrets add-iam-policy-binding "$S" --project="$PROJECT" \
    --member="serviceAccount:${JOBS_SA}" --role=roles/secretmanager.secretAccessor >/dev/null
done

gcloud run jobs create canone-push --project="$PROJECT" --region="$REGION" \
  --image="$IMAGE" --service-account="$JOBS_SA" \
  --command=python --args=-m,cli,canone,--push \
  --set-env-vars=CANONE_SIM_INPUTS=/secrets/canone/model-inputs.json \
  --set-secrets=CLOUDFLARE_API_TOKEN=cloudflare-kv-token:latest,CLOUDFLARE_ACCOUNT_ID=cloudflare-account-id:latest,/secrets/canone/model-inputs.json=canone-model-inputs:latest \
  --max-retries=1 --task-timeout=300s

gcloud run jobs add-iam-policy-binding canone-push --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:${JOBS_SA}" --role=roles/run.invoker

# Dopo spiaggia-corrispettivi (09:00): gli osservati del giorno sono già in BigQuery.
gcloud scheduler jobs create http canone-push-daily --project="$PROJECT" --location="$REGION" \
  --schedule="30 9 * * *" --time-zone="Europe/Rome" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/canone-push:run" \
  --http-method=POST --oauth-service-account-email="${JOBS_SA}"

echo "canone-push: Job + Scheduler creati."
