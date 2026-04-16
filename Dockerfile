# Intended for Cloud Run Jobs: run to completion (no HTTP port).
# Set env GCS_BUCKET on the job; default CMD runs the daily pipeline with GCS sync.
# Override CMD only if you need e.g. --storage local for debugging.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py backfill_matchup_results.py analyze_historic_favorites.py gcs_sync.py verify_matchup_data.py ./

CMD ["python", "main.py", "--storage", "gcs"]
