# 001 - Mail Aggregate Refactor

**Date:** 2026-05-12
**Status:** accepted
**Issue:** #158

## Context

Every plugin table (`email_summaries`, `extracted_otp_codes`, `extracted_coupons`, `calendar_events`, `auto_reply_records`, `contact_assignments`, `detected_newsletters`, `spam_detection_results`, `applied_labels`, `assigned_folders`, `ai_drafts`) identifies mails by the tuple `(mail_account_id, mail_uid)`. The IMAP UID is not stable: folder moves assign new UIDs via `COPYUID`, `UIDVALIDITY` resets invalidate the entire UID space, and cross-folder collisions are possible.

This causes a class of correctness bugs:

- Plugin data becomes orphaned after IMAP MOVE (#157).
- Reprocessing creates duplicate plugin rows (no upsert protection on most tables).
- Notifications render with empty plugin context when the UID drifts.
- Approval persistence and pipeline persistence both hand-roll `(account_id, mail_uid)` lookups, duplicated across 10+ save functions.

`TrackedEmail` already tracks every discovered mail with a UUID primary key, but no plugin table references it via FK.

## Decision

Promote `TrackedEmail` to the canonical **Mail aggregate**. Every plugin, draft, change-log, and approval table gains a `mail_id UUID FK -> tracked_emails.id ON DELETE CASCADE` as its sole reference to a mail. IMAP coordinates (`mail_uid`, `current_folder`, `uidvalidity`) become mutable attributes on the aggregate that can drift without breaking referential integrity.

Key design choices:

1. **Keep table name `tracked_emails`** to minimise migration scope. The model class will be aliased as `Mail` in application code once the transition is complete (Phase 3+).
2. **Add `message_id` (RFC 5322)** to `tracked_emails` with a partial unique constraint `(mail_account_id, message_id) WHERE message_id IS NOT NULL` for stable de-duplication across UID changes.
3. **Add content snapshot columns** (`recipient`, `body_excerpt`, `has_attachments`, `attachment_filenames`, `headers_subset`, `first_seen_uid`, `first_seen_folder`, `uidvalidity`) to `tracked_emails` so plugin tables can drop their redundant `mail_subject`/`mail_from`/`sender_email` copies.
4. **Phased rollout** over 5 phases, each independently shippable:
   - Phase 1: Schema scaffolding (add `mail_id` nullable, new columns, backfill).
   - Phase 2: Dual-write persistence (write both `mail_id` and legacy columns).
   - Phase 3: Switchover (queries use `mail_id`, drop redundant columns).
   - Phase 4: Drop legacy identity columns from plugin tables.
   - Phase 5: Hardening (UIDVALIDITY detection, Message-ID dedup, fingerprint fallback).
5. **`body_excerpt` size: 4 KB** — sufficient for notifications and queue previews without bloating the database.
6. **Orphan plugin rows** (no matching `tracked_email`) are dropped during migration with a count+sample report in migration output. No quarantine table — the data is unrecoverable without a mail anchor.
7. **`mail_id` exposed in public API** alongside `mail_uid` from Phase 2 onward. `mail_uid` is not removed but documented as deprecated for identity purposes.

## Alternatives

### Option A: Rewrite UIDs in place after IMAP MOVE

Patch `mail_uid` on every plugin row when a MOVE returns a new COPYUID. Rejected because:
- Requires updating N plugin tables per move — O(plugins) writes per IMAP operation.
- Does not solve UIDVALIDITY resets.
- Keeps the fragile composite key as the identity.

### Option B: Carry `original_mail_uid` in events

Add `original_mail_uid` to events so the notification handler can look up plugin data by the UID at creation time. Rejected because:
- Adds a second UID to track, increasing complexity.
- Does not fix the underlying data model — plugin rows still use an unstable key.
- Breaks down when a mail is moved multiple times.

### Option C: Separate `mails` table (not reusing `tracked_emails`)

Create a brand-new `mails` table and keep `tracked_emails` as a processing queue only. Rejected because:
- Doubles the migration effort (must populate `mails` from `tracked_emails` + backfill all FKs).
- `TrackedEmail` already has 90% of the required fields.
- Two tables tracking the same mail increases consistency risk.

## Consequences

- Every plugin table gains a `mail_id` FK. After Phase 4, the `(mail_account_id, mail_uid)` composite key is removed from plugin tables.
- IMAP MOVE only updates `tracked_emails.mail_uid` and `tracked_emails.current_folder` — zero plugin table writes.
- Notification handler loads the mail aggregate once by `mail_id` instead of per-plugin lookups.
- Frontend API responses include `mail_id` (UUID) alongside `mail_uid` (string). Clients should migrate to `mail_id` over time.
- Migration must backfill `mail_id` on all existing plugin rows by joining to `tracked_emails` on `(mail_account_id, mail_uid)`.
- Reprocessing uses `INSERT ... ON CONFLICT (mail_id) DO UPDATE` — no more duplicate rows.
