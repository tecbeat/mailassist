# Stage 1: Build frontend
FROM node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + static frontend
FROM python:3.14-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97 AS production

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.11.16@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d /uv /usr/local/bin/uv

# Install runtime system dependencies (curl for healthchecks)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -m appuser

WORKDIR /app

# Version injected by CI versioner via --opt build-arg:VERSION; falls back to "0.0.0-dev" for local builds
ARG VERSION=v0.0.0-dev
ENV VERSION=${VERSION}

# Ensure venv binaries (uvicorn, alembic, arq) are on PATH
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Install Python dependencies (cached layer -- only rebuilds on pyproject.toml/uv.lock change)
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-editable

# Copy Alembic config (separate layer for migration-only changes)
COPY backend/alembic.ini ./
COPY backend/alembic/ ./alembic/

# Copy backend source
COPY backend/app/ ./app/

# Copy changelog for the "What's New" dialog
COPY CHANGELOG.md ./

# Copy frontend build output (may not exist if frontend not yet built)
COPY --from=frontend-builder /build/dist ./static/

# Entrypoint selects role via CLI argument (app | worker | migrate)
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Switch to non-root user
USER 1000:1000

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD []
