# Monitoring

## Health Check

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

The `/health` endpoint is unauthenticated and checks database and Valkey connectivity.

## Dashboard

The web UI dashboard shows:

- **Processed Mails** — count over 24h / 7d / 30d
- **Pending Approvals** — items awaiting review
- **Tokens Used** — LLM token consumption
- **Unhealthy Accounts** — IMAP accounts with connection issues
- **AI Provider Issues** — providers that are paused or failing
- **Failed Mails** — mails that failed processing
- **Cron Jobs** — status and last run time for all scheduled tasks
- **Job Queue** — queued, processing, and failed background jobs

## Docker Health Check

The Docker Compose configuration includes a health check. Monitor with:

```bash
docker compose ps
```

## Logs

```bash
docker compose logs -f app      # web server
docker compose logs -f worker   # background tasks
```

Logs are structured JSON via `structlog`.
