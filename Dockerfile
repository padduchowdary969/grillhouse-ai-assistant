# Pipeline image: builds the demo dataset and loads it into the database (see docker-compose.yml).
FROM python:3.12-slim

WORKDIR /app
# OpenMP runtime for LightGBM
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DBT_SEND_ANONYMOUS_USAGE_STATS=false GIT_PYTHON_REFRESH=quiet
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "pipelines.run_all"]
