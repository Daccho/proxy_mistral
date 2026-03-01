# Proxy Mistral Production Docker Image
# A05: Multi-stage build — keep build tools out of runtime image

# ── Stage 1: Build ──────────────────────────────────────────────
FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libssl-dev \
    libffi-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

# ── Stage 2: Runtime ────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Only runtime system libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libssl3 \
    libffi8 \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary and venv from builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --from=builder /build/.venv /app/.venv

# Copy application code
COPY . .

# Create data directory and non-root user
RUN mkdir -p /app/data && \
    useradd -m -u 1000 appuser && \
    chown -R 1000:1000 /app/data && \
    chmod -R 755 /app

USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000 8765

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["proxy-mistral", "serve"]
