---
slug: /
---

# mailassist

**The self-hosted AI email assistant.**

mailassist connects to your IMAP accounts, processes incoming mail through a configurable AI plugin pipeline, and takes action — all on your own infrastructure.

## Key Features

- **Multi-account IMAP** with IDLE push and polling fallback
- **11-plugin AI pipeline** — spam, newsletters, labeling, smart folders, coupons, calendar, auto-reply, summaries, contacts, notifications, and a rules engine
- **Approval queue** — review AI actions before they touch your mailbox
- **Plugin-provider mapping** — assign different AI models per plugin
- **Customizable prompts** — Jinja2 templates editable in the UI
- **Envelope encryption** — two-layer KEK/DEK for stored credentials
- **OIDC SSO** — Authentik, Keycloak, or any OpenID Connect provider
- **CardDAV / CalDAV** — contact sync and calendar event creation

## Quick Start

```bash
git clone https://git.teccave.de/tecbeat/mailassist.git
cd mailassist
cp .env.example .env   # fill in secrets + OIDC
docker compose up -d
```

Then open `http://localhost:8000`, log in via your OIDC provider, add a mail account, and point it at an AI provider.

## Documentation

| Section | Description |
|---|---|
| [Installation](getting-started/installation.md) | Docker Compose setup and prerequisites |
| [Configuration](getting-started/configuration.md) | Environment variables reference |
| [First Run](getting-started/first-run.md) | Walkthrough: account, plugin, approvals |
| [Architecture](concepts/architecture.md) | How the components fit together |
| [Pipeline](concepts/pipeline.md) | Plugin ordering, providers, approval modes |
| [Plugins](plugins/index.md) | All 11 plugins at a glance |
| [Operations](operations/backup.md) | Backup, upgrades, monitoring |
