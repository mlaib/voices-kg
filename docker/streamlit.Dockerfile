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

COPY app/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

# The app code is mounted at runtime; baking it in would make iteration slow.
EXPOSE 8501

CMD ["streamlit", "run", "/app/Overview.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", "--browser.gatherUsageStats=false"]
