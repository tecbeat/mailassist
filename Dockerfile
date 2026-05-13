# Stage 1: Build frontend
FROM node:24-alpine@sha256:d1b3b4da11eefd5941e7f0b9cf17783fc99d9c6fc34884a665f40a06dbdfc94f AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + static frontend
FROM python:3.14-slim@sha256:1697e8e8d39bf168e177ac6b5fdab6df86d81cfc24dae17dfb96cfc3ef76b4dd AS production

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.11.14@sha256:1025398289b62de8269e70c45b91ffa37c373f38118d7da036fb8bb8efc85d97 /uv /usr/local/bin/uv

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
