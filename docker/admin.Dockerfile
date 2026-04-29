FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY admin/requirements.txt /app/admin/requirements.txt
RUN pip install -r /app/admin/requirements.txt

EXPOSE 8000

# admin package is mounted at /app/admin at runtime.
CMD ["sh", "-c", "python -m admin.seed && uvicorn admin.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-2}"]
