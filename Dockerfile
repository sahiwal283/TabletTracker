# TabletTracker — bind gunicorn inside the container; publish host port 7620 -> container 8000
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Self-hosted: require ZOHO_SERVICE_BASE_URL at runtime (pass via --env-file or compose).
ENV DATABASE_PATH=/data/tablet_counter.db \
    FLASK_ENV=production \
    TABLETTRACKER_SELF_HOSTED=1 \
    BEHIND_PROXY=1

RUN mkdir -p /data

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120", "wsgi:application"]
