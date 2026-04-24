# Stage 1: Build frontend
FROM node:22-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# Stage 2: Python backend + static frontend
FROM python:3.13-slim AS production

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install runtime system dependencies (curl for healthchecks)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 1000 appuser && useradd -u 1000 -g appuser -m appuser

WORKDIR /app

# Install Python dependencies (cached layer -- only rebuilds on pyproject.toml change)
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-dev --no-editable 2>/dev/null || \
    uv pip compile pyproject.toml -o /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt

# Copy Alembic config (separate layer for migration-only changes)
COPY backend/alembic.ini ./
COPY backend/alembic/ ./alembic/

# Copy backend source
COPY backend/app/ ./app/

# Copy frontend build output (may not exist if frontend not yet built)
COPY --from=frontend-builder /build/dist ./static/

# Entrypoint selects role via CLI argument (app | worker | migrate)
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Switch to non-root user
USER 1000:1000

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD []
