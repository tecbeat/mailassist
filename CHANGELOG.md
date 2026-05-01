# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-05-01

### Added

- **"What's New" changelog dialog** — shows recent changes after app updates, dismissible per version ([!154](https://git.teccave.de/tecbeat/mailassist/-/merge_requests/154))
- **11-plugin AI processing pipeline** — spam detection, newsletters, labeling, smart folders, coupons, calendar extraction, auto-reply drafts, email summaries, contact sync, notifications, and rules engine
- **Approval queue** — review AI actions before they touch your mailbox (auto / approval / disabled per plugin)
- **Multi-account IMAP** with IMAP IDLE push and polling fallback
- **Multiple AI providers** — OpenAI, Ollama, or any OpenAI-compatible endpoint, assignable per plugin
- **Rules engine** — structured AND/OR conditions with 11 operators and natural language to rule translation
- **CardDAV contact sync** — incremental sync with matching and write-back
- **CalDAV calendar integration** — event extraction and sync
- **Customizable Jinja2 prompt templates** — editable in the UI with CodeMirror
- **OIDC/SSO authentication** — Authentik, Keycloak, and any OpenID Connect provider
- **Envelope encryption** — two-layer KEK/DEK for all stored credentials
- **Notifications via Apprise** — Matrix, Discord, email, and 80+ services
- **Dashboard** with processing stats, cron job management, and approval overview
- **Helm chart** for Kubernetes deployment
