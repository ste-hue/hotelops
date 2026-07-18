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

# Icona home-screen (design 1B "Monogramma P", claude.ai/design): webmanifest nella
# static dir di Streamlit + <link> iniettati in index.html. I PNG stanno su
# gs://hotelops-public-assets (pubblico): iOS/Chrome scaricano l'icona SENZA cookie,
# quindi un URL dietro IAP verrebbe respinto e cadrebbe il fallback "H" monogramma.
RUN STATIC=$(python -c "import streamlit, os; print(os.path.join(os.path.dirname(streamlit.__file__), 'static'))") \
    && cp verticals/hub/assets/hotelops.webmanifest "$STATIC/" \
    && sed -i 's|<head>|<head><link rel="apple-touch-icon" sizes="180x180" href="https://storage.googleapis.com/hotelops-public-assets/apple-touch-icon.png"/><link rel="manifest" href="./hotelops.webmanifest" crossorigin="use-credentials"/><meta name="apple-mobile-web-app-title" content="HotelOps"/><meta name="theme-color" content="#003764"/>|' "$STATIC/index.html"

# Cloud Run inietta $PORT (default 8080)
ENV PORT=8080
EXPOSE 8080

CMD streamlit run verticals/hub/app.py \
    --server.port=$PORT --server.address=0.0.0.0 \
    --server.headless=true --server.enableCORS=false \
    --server.enableXsrfProtection=false
