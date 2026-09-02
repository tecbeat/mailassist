# Stage 1: Build frontend
FROM node:24-alpine@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + static frontend
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS production

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff /uv /usr/local/bin/uv

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
