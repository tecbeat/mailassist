# Installation

## Prerequisites

- Docker and Docker Compose v2
- An OIDC identity provider (Authentik, Keycloak, or any OIDC-compliant provider)
- At least one IMAP email account
- At least one AI provider (OpenAI, Ollama, or any OpenAI-compatible endpoint)

## Docker Compose

```bash
git clone https://git.teccave.de/tecbeat/mailassist.git
cd mailassist
cp .env.example .env
```

Edit `.env` and fill in the required values:

```bash
APP_SECRET_KEY=your-secret-key-min-32-chars    # master encryption key
POSTGRES_PASSWORD=your-db-password
VALKEY_PASSWORD=your-valkey-password
OIDC_ISSUER_URL=https://auth.example.com/application/o/mailassist/
OIDC_CLIENT_ID=your-client-id
OIDC_CLIENT_SECRET=your-client-secret
OIDC_REDIRECT_URI=http://localhost:8000/auth/callback
```

Start the stack:

```bash
docker compose up -d
```

This starts five services:

| Service | Purpose |
|---|---|
| `app` | FastAPI web server + React SPA |
| `worker` | ARQ background worker (mail polling, AI pipeline, sync) |
| `postgres` | PostgreSQL 17 database |
| `valkey` | Valkey 8 (sessions, task queue, cache) |
| `ollama` | Optional local LLM inference |

The web UI is available at `http://localhost:8000`.

## Helm Chart (Kubernetes)

For Kubernetes deployments, a Helm chart is available in `charts/mailassist/`:

```bash
helm install mailer charts/mailassist/ -f my-values.yaml -n mailer --create-namespace
```

See `charts/mailassist/values.yaml` for all configuration options.

## Verify

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```
