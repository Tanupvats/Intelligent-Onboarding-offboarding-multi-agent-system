

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---- Builder: install deps into a venv --------------------------------
FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
 && /opt/venv/bin/pip install -r requirements.txt

# ---- Runtime: minimal image -------------------------------------------
FROM base AS runtime

# Non-root user
RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# App code
COPY backend/ ./backend/
COPY servers/ ./servers/
COPY data/ ./data/

# Runtime-writable dirs
RUN mkdir -p /app/uploads /app/data \
 && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request, sys; \
urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3); sys.exit(0)" \
  || exit 1

CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8000"]
