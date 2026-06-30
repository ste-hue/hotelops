#!/usr/bin/env bash
# Task 6 — Alerting email sui fallimenti dei Cloud Run Jobs.
# Usa l'API Monitoring via REST (il componente gcloud `alpha` non è installato
# in questo ambiente). Idempotente-ish: ri-eseguire crea un duplicato del canale
# — controlla prima con `gcloud beta monitoring channels list`.
set -euo pipefail

PROJECT=hotelops-suite
EMAIL=ste.dellapietra@gmail.com

# 1. Canale di notifica email
gcloud beta monitoring channels create --project="$PROJECT" \
  --display-name="HotelOps Jobs Alerts" --type=email \
  --channel-labels=email_address="$EMAIL"

# Recupera l'ID del canale appena creato (o esistente)
CH=$(gcloud beta monitoring channels list --project="$PROJECT" \
  --filter="displayName='HotelOps Jobs Alerts'" --format="value(name)" | head -1)

# 2. Policy: scatta su qualsiasi esecuzione Job con result=failed
cat > /tmp/job-fail-policy.json <<EOF
{
  "displayName": "Cloud Run Job failed — hotelops",
  "combiner": "OR",
  "conditions": [{
    "displayName": "Job execution failed",
    "conditionThreshold": {
      "filter": "resource.type=\"cloud_run_job\" AND metric.type=\"run.googleapis.com/job/completed_execution_count\" AND metric.label.\"result\"=\"failed\"",
      "comparison": "COMPARISON_GT",
      "thresholdValue": 0,
      "duration": "0s",
      "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_SUM"}],
      "trigger": {"count": 1}
    }
  }],
  "notificationChannels": ["$CH"],
  "alertStrategy": {"autoClose": "604800s"}
}
EOF

TOKEN=$(gcloud auth print-access-token)
curl -s -X POST \
  "https://monitoring.googleapis.com/v3/projects/${PROJECT}/alertPolicies" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d @/tmp/job-fail-policy.json

echo "Alert policy creata (canale: $CH)."
