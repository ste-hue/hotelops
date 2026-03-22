FROM python:3.11-slim

WORKDIR /app

# Install only what condges needs
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dashboard]"

# Core (the world model) + condges (the vertical)
COPY core/ core/
COPY condges/ condges/

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "condges/app.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0", \
    "--server.headless=true"]
