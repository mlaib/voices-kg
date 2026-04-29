FROM python:3.11-slim

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ENV http_proxy=$HTTP_PROXY https_proxy=$HTTPS_PROXY \
    HTTP_PROXY=$HTTP_PROXY HTTPS_PROXY=$HTTPS_PROXY
RUN if [ -n "$HTTP_PROXY" ]; then \
        echo "Acquire::http::Proxy  \"$HTTP_PROXY\";"  >  /etc/apt/apt.conf.d/01proxy && \
        echo "Acquire::https::Proxy \"$HTTPS_PROXY\";" >> /etc/apt/apt.conf.d/01proxy ; \
    fi

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
