# HotelOps Hub — admin surface (Streamlit su Cloud Run, legge/scrive BigQuery in tempo reale).
# Serve app.py (admin completo: cashflow + ingest), gated da IAP. Auth BQ/GCS via
# Application Default Credentials del service account di Cloud Run (nessuna chiave
# nell'immagine). Deploy: gcloud run deploy --source .
FROM python:3.11-slim

WORKDIR /app

# Deps di sistema minime (google-cloud, build wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir ".[dashboard]"

# Cloud Run inietta $PORT (default 8080)
ENV PORT=8080
EXPOSE 8080

CMD streamlit run verticals/hub/app.py \
    --server.port=$PORT --server.address=0.0.0.0 \
    --server.headless=true --server.enableCORS=false \
    --server.enableXsrfProtection=false
