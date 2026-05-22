ARG PYTHON_IMAGE=python:3.10-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN if command -v apt-get >/dev/null 2>&1; then \
        apt-get update \
        && apt-get install -y --no-install-recommends ca-certificates \
        && rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
        apk add --no-cache ca-certificates; \
    fi

COPY requirements-nas.txt /tmp/requirements-nas.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r /tmp/requirements-nas.txt

EXPOSE 8765

CMD ["bash", "scripts/start_dashboard.sh"]
