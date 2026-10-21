# syntax=docker/dockerfile:1
#
# Grill House Ops Copilot: two images from one Dockerfile
#
#   docker build --target pipeline -t grillhouse-pipeline .   data, ML and evaluation jobs
#   docker build --target api      -t grillhouse-api .        the FastAPI app and phone UI, with demo data baked in
#
# Both run as a non-root user and never contain the shop's private data or secrets (see .dockerignore).

ARG PYTHON_IMAGE=python:3.12.15-slim-bookworm

# ---------- base: shared runtime settings and a non-root user ----------
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
 && mkdir -p /app && chown app:app /app
WORKDIR /app

# ---------- pipeline: seed data, cleaning, PII redaction, DB load, dbt, forecasting ----------
FROM base AS pipeline
# OpenMP runtime for LightGBM
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 \
 && rm -rf /var/lib/apt/lists/*
COPY requirements/ requirements/
RUN pip install -r requirements/pipeline.txt
ENV DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    GIT_PYTHON_REFRESH=quiet
COPY --chown=app:app app/ app/
COPY --chown=app:app pipelines/ pipelines/
COPY --chown=app:app evals/ evals/
COPY --chown=app:app dbt/ dbt/
COPY --chown=app:app db/ db/
COPY --chown=app:app seed_data/ seed_data/
USER app
CMD ["python", "-m", "pipelines.run_all"]

# ---------- demo-data: build the synthetic reports the API answers from (no database needed) ----------
FROM pipeline AS demo-data
RUN python -m pipelines.run_all --no-db

# ---------- api: FastAPI backend + phone app, demo data included ----------
FROM base AS api
COPY requirements/api.txt requirements/api.txt
RUN pip install -r requirements/api.txt
COPY --chown=app:app app/ app/
COPY --chown=app:app ui/static/ ui/static/
COPY --from=demo-data --chown=app:app /app/seed_data/ seed_data/
RUN mkdir -p logs && chown app:app logs
ENV GRILLHOUSE_DATA=seed_data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
