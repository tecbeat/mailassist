# Architecture

mailassist runs as a set of cooperating services orchestrated by Docker Compose.

## Components

```
┌─────────────┐     ┌─────────────┐
│   Browser    │────▶│     app     │──── FastAPI + React SPA
└─────────────┘     └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │   postgres  │──── PostgreSQL 17
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │   valkey    │──── Sessions, task queue, cache
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │   worker    │──── ARQ background tasks
                    └──────┬──────┘
                           │
                    ┌──────┴──────┐
                    │   ollama    │──── Local LLM (optional)
                    └─────────────┘
```

### app

The FastAPI web server serves both the REST API and the React SPA (static files). It handles authentication (OIDC), request validation, and delegates business logic to the service layer.

### worker

The ARQ background worker runs scheduled and on-demand tasks:

- **Mail polling** — periodic IMAP fetch for each account
- **IMAP IDLE** — push-based mail monitoring
- **AI pipeline** — processes new mail through the plugin chain
- **Contact sync** — periodic CardDAV synchronization
- **Draft cleanup** — expires old auto-reply drafts
- **Health checks** — monitors AI provider availability

### postgres

PostgreSQL 17 stores all application data: accounts, contacts, plugin results, approval queue, rules, and encrypted credentials.

### valkey

Valkey 8 (Redis-compatible) serves three roles:

- **Session store** — user sessions for the web UI
- **Task broker** — ARQ job queue for background tasks
- **Cache** — token usage counters, rate limiting, OIDC discovery cache

### ollama (optional)

Local LLM inference via Ollama. Any OpenAI-compatible endpoint works — Ollama, LM Studio, llama.cpp, or cloud providers.
