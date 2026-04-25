"""Draft cleanup service.

Monitors AI-generated drafts and cleans up stale ones.
Detects when users send their own reply (superseding the AI draft)
or when drafts expire past the configured threshold.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from imap_tools import AND, MailBox
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import AIDraft, DraftStatus, MailAccount
from app.services.mail import ImapConnection, imap_connection, resolve_folder

logger = structlog.get_logger()


async def cleanup_drafts_for_account(
    db: AsyncSession,
    account: MailAccount,
    expiry_days: int = 7,
) -> dict[str, int]:
    """Clean up stale AI drafts for a single mail account.

    For each active AI draft:
    1. Check Sent folder for user replies matching the original message
       -> Found: mark "superseded", delete draft from IMAP
    2. Check if draft still exists in IMAP Drafts
       -> Missing: mark "deleted" (user used or deleted it manually)
    3. Check draft age against expiry threshold
       -> Expired: mark "expired", delete from IMAP

    Returns stats about the cleanup operation.
    """
    stats = {"superseded": 0, "deleted": 0, "expired": 0, "errors": 0}

    # Fetch active drafts for this account
    stmt = select(AIDraft).where(
        AIDraft.mail_account_id == account.id,
        AIDraft.status == DraftStatus.ACTIVE,
    )
    result = await db.execute(stmt)
    active_drafts = result.scalars().all()

    if not active_drafts:
        return stats

    now = datetime.now(UTC)
    expiry_threshold = now - timedelta(days=expiry_days)
    settings = get_settings()

    try:
        async with imap_connection(account) as conn:
            # Resolve Sent/Drafts folders using the shared helper
            sent_candidates = [
                f.strip()
                for f in settings.draft_sent_folder_names.split(",")
                if f.strip()
            ]
            draft_candidates = [
                f.strip()
                for f in settings.draft_folder_names.split(",")
                if f.strip()
            ]
            sent_folder = await resolve_folder(conn, sent_candidates)
            drafts_folder = await resolve_folder(conn, draft_candidates)

            # Collect Message-IDs from Sent folder for matching
            sent_message_ids = await _get_sent_message_ids(
                conn, sent_folder, settings,
            )

            # Check each active draft
            for draft in active_drafts:
                try:
                    # Check if user sent their own reply (supersedes the AI draft)
                    if draft.original_message_id in sent_message_ids:
                        await _delete_draft_from_imap(conn, draft.draft_uid, drafts_folder)
                        draft.status = DraftStatus.SUPERSEDED
                        draft.cleaned_at = now
                        stats["superseded"] += 1
                        logger.info(
                            "draft_superseded",
                            draft_id=str(draft.id),
                            original_message_id=draft.original_message_id,
                        )
                        continue

                    # Check if draft still exists in IMAP
                    draft_exists = await _draft_exists_in_imap(
                        conn, draft.draft_uid, drafts_folder,
                    )
                    if not draft_exists:
                        draft.status = DraftStatus.DELETED
                        draft.cleaned_at = now
                        stats["deleted"] += 1
                        logger.info("draft_manually_removed", draft_id=str(draft.id))
                        continue

                    # Check age-based expiry
                    if draft.created_at < expiry_threshold:
                        await _delete_draft_from_imap(conn, draft.draft_uid, drafts_folder)
                        draft.status = DraftStatus.EXPIRED
                        draft.cleaned_at = now
                        stats["expired"] += 1
                        logger.info("draft_expired", draft_id=str(draft.id))

                except Exception:
                    logger.exception("draft_cleanup_failed", draft_id=str(draft.id))
                    stats["errors"] += 1

            await db.commit()

    except Exception:
        logger.exception(
            "draft_cleanup_imap_failed",
            account_id=str(account.id),
        )
        stats["errors"] += 1

    return stats


async def _get_sent_message_ids(
    conn: ImapConnection,
    sent_folder: str | None,
    settings: Settings,
) -> set[str]:
    """Fetch In-Reply-To headers from recent Sent messages for matching.

    Looks at messages from the configured lookback window to find user-sent
    replies that may supersede AI drafts.
    """
    message_ids: set[str] = set()
    if sent_folder is None:
        return message_ids

    try:
        since_date = datetime.now(UTC) - timedelta(days=settings.draft_lookback_days)

        def _scan_sent() -> set[str]:
            ids: set[str] = set()
            conn.mailbox.folder.set(sent_folder)

            # Fetch recent messages with In-Reply-To header
            criteria = AND(date_gte=since_date.date())
            messages = list(conn.mailbox.fetch(
                criteria,
                headers_only=True,
                mark_seen=False,
                limit=settings.draft_max_sent_scan,
            ))
            for msg in messages:
                in_reply_to = msg.headers.get("in-reply-to", [""])
                # headers returns list of values
                for val in in_reply_to:
                    msg_id = val.strip().strip("<>")
                    if msg_id:
                        ids.add(msg_id)
            return ids

        message_ids = await asyncio.to_thread(_scan_sent)

    except Exception:
        logger.warning("sent_folder_scan_failed")

    return message_ids


async def _draft_exists_in_imap(
    conn: ImapConnection,
    draft_uid: str,
    drafts_folder: str | None,
) -> bool:
    """Check if a specific draft UID still exists in the Drafts folder."""
    if drafts_folder is None:
        return False

    try:
        def _check() -> bool:
            conn.mailbox.folder.set(drafts_folder)
            return draft_uid in conn.mailbox.uids()

        return await asyncio.to_thread(_check)
    except Exception:
        logger.warning("draft_exists_check_failed", draft_uid=draft_uid)
        return False


async def _delete_draft_from_imap(
    conn: ImapConnection,
    draft_uid: str,
    drafts_folder: str | None,
) -> None:
    """Delete a draft from the IMAP Drafts folder."""
    if drafts_folder is None:
        return

    try:
        def _delete() -> None:
            conn.mailbox.folder.set(drafts_folder)
            conn.mailbox.delete(draft_uid)

        await asyncio.to_thread(_delete)
    except Exception:
        logger.warning("draft_delete_failed", draft_uid=draft_uid)
