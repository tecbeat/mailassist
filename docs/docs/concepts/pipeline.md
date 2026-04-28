# Pipeline

Every incoming mail passes through an ordered plugin pipeline. Each plugin can inspect the mail, call an LLM, and propose actions.

## Plugin Order

| Priority | Plugin | Purpose |
|:--------:|--------|---------|
| 5 | Rules | Structured AND/OR conditions with 11 operators |
| 10 | Spam Detection | Scoring with confidence levels and blocklist |
| 20 | Newsletter | Detects newsletters and mailing lists |
| 30 | Labeling | Generates semantic labels |
| 40 | Smart Folders | Auto-sorts into IMAP folders |
| 50 | Coupons | Extracts codes, expiry dates, terms |
| 60 | Calendar | Extracts events, syncs to CalDAV |
| 70 | Auto-Reply | Drafts context-aware replies |
| 75 | Summary | Produces concise summaries |
| 80 | Contacts | Extracts and syncs contacts via CardDAV |
| 90 | Notifications | Sends alerts via Apprise |

## Per-Plugin Providers

Each plugin can be assigned its own AI provider. This lets you use a fast cloud model for spam detection and a large local model for summaries.

## Approval Modes

Every plugin supports three modes:

- **Auto** — actions are applied immediately
- **Approval** — actions are queued for manual review
- **Off** — plugin is skipped entirely

!!! note
    The Notifications plugin only supports **Auto** and **Off** (no approval mode).

## Pipeline Context

Plugins communicate through a shared `PipelineContext`:

- **First-Write-Wins** for exclusive actions (e.g. move to folder)
- **Additive** for labels and flags (multiple plugins can add labels)

If a plugin marks a mail as spam, downstream plugins can check this and adjust their behavior.

## Prompt Templates

Each plugin uses a Jinja2 template to construct its LLM prompt. Templates are editable in the UI under **Prompts** and support variables like `{{ subject }}`, `{{ sender_name }}`, `{{ body }}`.
