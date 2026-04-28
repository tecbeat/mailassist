# Spam Detection

**Priority:** 10 · **AI:** Yes

Analyzes incoming mail for spam indicators using the assigned AI provider. Produces a confidence score and optional explanation.

## Blocklist

Manually block senders by email address, domain, or subject pattern. Blocked entries are checked before the AI call — matching mail is flagged immediately without using tokens.

## Behavior

When spam is detected, the mail is flagged in the pipeline context. Downstream plugins can check this flag and skip processing (e.g. no point summarizing spam).
