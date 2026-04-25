<div align="center">

# mailassist

**The self-hosted AI email assistant.**

[![Pipeline](https://img.shields.io/badge/build-passing-brightgreen)](https://git.teccave.de/tecbeat/mailassist/-/pipelines)
[![License](https://img.shields.io/badge/license-GPLv3-blue)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/)
[![React](https://img.shields.io/badge/react-19-61dafb)](https://react.dev/)

</div>

---

### Installation

```bash
# Clone and start
git clone https://git.teccave.de/tecbeat/mailassist.git
cd mailassist
cp .env.example .env                 # fill in secrets + OIDC
docker compose up -d
```

The web UI is available at `http://localhost:8000`. Log in through your OIDC provider, add a mail account, and point it at an AI provider. That's it.

#### Prerequisites

- Docker and Docker Compose v2
- An OIDC identity provider (Authentik, Keycloak, ...)
- At least one IMAP account
- At least one AI provider (OpenAI, Ollama, or any OpenAI-compatible endpoint)

### Pipeline

mailassist runs every incoming mail through an ordered, pluggable pipeline. Each plugin can be assigned its own AI provider, enabled or disabled per user, or set to require approval before acting.

| Order | Plugin | Purpose |
|:-----:|--------|---------|
|  5  | **Rules**              | Structured AND/OR rules with 11 operators, NL-to-rule translation |
| 10  | **Spam Detection**     | Scoring with confidence levels and a configurable blocklist |
| 20  | **Newsletter**         | Detects newsletters and mailing lists |
| 30  | **Labeling**           | Generates semantic labels |
| 40  | **Smart Folders**      | Auto-sorts mails into IMAP folders |
| 50  | **Coupons**            | Extracts codes, expiry dates, and terms |
| 60  | **Calendar**           | Extracts events and syncs to CalDAV |
| 70  | **Auto-Reply**         | Drafts context-aware replies |
| 75  | **Summary**            | Produces concise summaries |
| 80  | **Contacts**           | Extracts and syncs contacts via CardDAV |
| 90  | **Notifications**      | Sends alerts via Apprise (Matrix, Discord, mail, ...) |

### Highlights

- **Multi-account IMAP** with IMAP IDLE for push, plus polling as a fallback
- **Plugin-provider mapping** — fast cloud model for spam, big local model for summaries
- **Approval queue** — review AI actions before they touch your mailbox
- **Customizable prompts** — Jinja2 templates, editable in the UI with CodeMirror
- **Envelope encryption** — two-layer KEK/DEK for every stored credential
- **OIDC + PKCE** — SSO via any OpenID Connect provider
- **CardDAV / CalDAV** — contact matching, write-back, event sync

### Configuration

Everything is driven by environment variables. Start from [`.env.example`](./.env.example); the required keys are:

| Variable | Description |
|----------|-------------|
| `APP_SECRET_KEY` | Master encryption key (min. 32 chars) |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `VALKEY_PASSWORD` | Valkey password |
| `OIDC_ISSUER_URL` | OIDC discovery endpoint |
| `OIDC_CLIENT_ID` | OIDC client identifier |
| `OIDC_CLIENT_SECRET` | OIDC client secret |
| `OIDC_REDIRECT_URI` | OIDC callback URL |

All other variables ship with sane defaults. For key rotation set `APP_SECRET_KEY_OLD` to the previous value and restart — mailassist re-encrypts on the fly.

### Development

```bash
# Backend
cd backend
pip install -e ".[dev]"
pytest tests/ --cov=app            # tests + coverage (min. 80%)
ruff check app/ tests/             # lint
mypy app/                          # type-check

# Frontend
cd frontend
npm install
npm run dev                        # Vite dev server (proxies to :8000)
npx orval                          # regenerate API client from openapi.json
npx vitest                         # tests
```

### Stack

**Backend** — Python 3.13, FastAPI, SQLAlchemy 2 (async) + Alembic, ARQ on Valkey, litellm for unified LLM access, imap-tools, Authlib, Pydantic 2, structlog, `cryptography` for envelope encryption.

**Frontend** — React 19, TypeScript 5.8, Vite 6, TailwindCSS 4, Radix UI, TanStack Query 5, react-hook-form + Zod v4, orval, dnd-kit, CodeMirror 6.

**Infrastructure** — PostgreSQL 17, Valkey 8 (Redis-compatible), optional Ollama for local LLMs.

### FAQ

#### How is this different from Gmail's smart features?

mailassist is **self-hosted** and **provider-agnostic**. Your mail never leaves your infrastructure except for the LLM call — and even that can be local via Ollama. You bring the IMAP account, the AI provider, and the policy.

#### Do I need an OpenAI subscription?

No. mailassist speaks any OpenAI-compatible API — that includes Ollama, LM Studio, llama.cpp's server, LiteLLM proxy, Azure OpenAI, Together, Groq, and many more. Assign a different provider per plugin if you want to mix cloud and local.

#### Will it mess with my inbox?

Not unless you let it. Every plugin has an approval mode: `auto`, `approval`, or `disabled`. Start everything in `approval` mode, watch the queue for a few days, then flip the ones you trust to `auto`.

#### What about my data?

All credentials (IMAP, CardDAV, CalDAV, API keys) are stored with envelope encryption: a per-record DEK wrapped by the master KEK you provide via `APP_SECRET_KEY`. The API never returns encrypted values.

### License

[GNU GPL v3](./LICENSE)
