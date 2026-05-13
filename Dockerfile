# Stage 1: Build frontend
FROM node:24-alpine@sha256:d1b3b4da11eefd5941e7f0b9cf17783fc99d9c6fc34884a665f40a06dbdfc94f AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + static frontend
FROM python:3.14-slim@sha256:33ef7446e8c14b21cb247e23afbcdc90e98853b70812ca46b2265e769a7dfb8b AS production

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.11.12@sha256:3a59a3cdd5f7c217faa36e32dbc7fddbb0412889c2a0a5229f6d790e5a019dd7 /uv /usr/local/bin/uv

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
