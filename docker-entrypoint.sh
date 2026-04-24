#!/bin/sh
set -e

ROLE="${1:-app}"

case "$ROLE" in
  app)
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
    ;;
  worker)
    exec arq app.workers.worker.WorkerSettings
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  *)
    echo "Unknown role: $ROLE (expected: app, worker, migrate)" >&2
    exit 1
    ;;
esac
