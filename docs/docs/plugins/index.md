---
sidebar_label: Overview
slug: /plugins
---

# Plugins Overview

mailassist processes every incoming mail through an ordered pipeline of 11 plugins. Each plugin can be enabled, disabled, or set to require approval.

| Priority | Plugin | AI | Description |
|:--------:|--------|:--:|-------------|
| 5 | [Rules](rules.md) | No | Structured AND/OR rules with NL-to-rule translation |
| 10 | [Spam Detection](spam.md) | Yes | Scoring with confidence levels and blocklist |
| 20 | [Newsletters](newsletters.md) | Yes | Detects newsletters and mailing lists |
| 30 | [Auto-Labeling](labeling.md) | Yes | Generates semantic labels |
| 40 | [Smart Folders](smart-folders.md) | Yes | Auto-sorts mails into IMAP folders |
| 50 | [Coupons](coupons.md) | Yes | Extracts codes, expiry dates, terms |
| 60 | [Calendar](calendar.md) | Yes | Extracts events, syncs to CalDAV |
| 70 | [Auto-Reply](auto-reply.md) | Yes | Drafts context-aware replies |
| 75 | [Summary](summary.md) | Yes | Produces concise summaries |
| 80 | [Contacts](contacts.md) | Yes | Extracts and syncs contacts via CardDAV |
| 90 | [Notifications](notifications.md) | No | Sends alerts via Apprise |

## Common Features

- **Per-plugin AI provider**: Assign a different model to each plugin
- **Approval modes**: Auto, Approval, or Off per plugin
- **Custom prompts**: Edit Jinja2 templates in the UI
- **Pipeline context**: Plugins share state (e.g. spam flag) for downstream decisions
