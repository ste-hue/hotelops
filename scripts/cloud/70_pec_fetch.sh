#!/usr/bin/env bash
# Task 7 — pec-fetch su Cloud Run Job + Cloud Scheduler.
#
# Scarica in SOLA LETTURA le caselle PEC societarie (INTUR, ORTI, VIGNA) via IMAP e le
# consegna a intake + promote. La casella personale (mpspec.it) è deliberatamente fuori:
# nel registry non ha blocco `imap`, quindi --all la salta.
#
# Gira COME drive-audit@ (stessa identità di spiaggia/coperti: ha già BQ + GCS).
# Le password PEC arrivano da Secret Manager come env — nessuna chiave nell'immagine.
# Prerequisito: i tre segreti devono essere leggibili da drive-audit@, cioè
#   gcloud secrets add-iam-policy-binding pec-password-<E> \
#     --member="serviceAccount:drive-audit@..." --role=roles/secretmanager.secretAccessor
#
# ⚠️ PRIMA DI ESEGUIRE QUESTO SCRIPT: il backfill iniziale di ogni casella va fatto DA
# LOCALE. Il primo giro di una cartella mai fetchata scarica l'intera INBOX (INTUR ~3h);
# il job notturno deve nascere già in regime incrementale, dove vede poche buste e chiude
# in un minuto. Senza, il job riscarica ogni notte e non completa mai.
#
# Uso: scripts/cloud/70_pec_fetch.sh [IMAGE_TAG]   (default: v4)
set -euo pipefail

PROJECT=hotelops-suite
REGION=europe-west1
TAG="${1:-v4}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/hotelops/jobs:${TAG}"
DRIVE_SA="drive-audit@${PROJECT}.iam.gserviceaccount.com"
JOBS_SA="hotelops-jobs@${PROJECT}.iam.gserviceaccount.com"

SECRETS="PEC_PASSWORD_INTUR=pec-password-INTUR:latest"
SECRETS="${SECRETS},PEC_PASSWORD_ORTI=pec-password-ORTI:latest"
SECRETS="${SECRETS},PEC_PASSWORD_VIGNA=pec-password-VIGNA:latest"

# task-timeout 60m, non 10m come gli altri job: ~21 s per busta (upload GCS + intake +
# parse + insert). In regime incrementale bastano pochi minuti, ma una giornata con molte
# PEC o un recupero via finestra SINCE può allungarsi.
gcloud run jobs create pec-fetch --project="$PROJECT" --region="$REGION" \
  --image="$IMAGE" --service-account="$DRIVE_SA" \
  --set-secrets="$SECRETS" \
  --command=python --args=-m,ingest.pec_fetch,--all \
  --max-retries=1 --task-timeout=3600s

# max-retries=1 e non 2: un ritentativo automatico su una casella già parzialmente
# ingerita non fa danni (il content-hash deduplica) ma raddoppia il tempo. Il progresso
# è comunque monotono grazie al watermark per blocco.

gcloud run jobs add-iam-policy-binding pec-fetch --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:${JOBS_SA}" --role=roles/run.invoker

gcloud scheduler jobs create http pec-fetch-daily --project="$PROJECT" --location="$REGION" \
  --schedule="0 4 * * *" --time-zone="Europe/Rome" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT}/jobs/pec-fetch:run" \
  --http-method=POST --oauth-service-account-email="${JOBS_SA}"

echo "pec-fetch: Job (drive-audit@, 3 segreti PEC) + Scheduler 04:00 creati."
echo "Verifica: gcloud run jobs execute pec-fetch --region=${REGION} --wait"
