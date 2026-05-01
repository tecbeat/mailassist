"""Spam blocklist service.

Provides business logic for reporting emails/contacts as spam,
managing the blocklist, and checking senders against it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models import Contact, MailAccount, SpamBlocklistEntry, TrackedEmail
from app.models.spam import BlocklistEntryType, BlocklistSource
from app.services.imap_actions import execute_imap_actions

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


def _extract_domain(email: str) -> str | None:
    """Extract the domain part from an email address.

    Returns None if the address has no '@' sign.
    """
    parts = email.rsplit("@", 1)
    return parts[1].lower().strip() if len(parts) == 2 else None


async def _upsert_blocklist_entry(
    db: AsyncSession,
    user_id: UUID,
    entry_type: BlocklistEntryType,
    value: str,
    source: BlocklistSource,
    source_mail_uid: str | None = None,
) -> bool:
    """Insert a blocklist entry if it doesn't already exist.

    Uses PostgreSQL ON CONFLICT DO NOTHING for idempotency.

    Returns:
        True if a new row was inserted, False if it already existed.
    """
    stmt = (
        pg_insert(SpamBlocklistEntry)
        .values(
            user_id=user_id,
            entry_type=entry_type,
            value=value.lower().strip(),
            source=source,
            source_mail_uid=source_mail_uid,
        )
        .on_conflict_do_nothing(
            constraint="uq_spam_blocklist_user_type_value",
        )
    )
    result = await db.execute(stmt)
    return bool(result.rowcount)  # type: ignore[attr-defined]


async def report_as_spam(
    db: AsyncSession,
    user_id: UUID,
    mail_account_id: UUID,
    mail_uid: str,
    sender_email: str,
    subject: str | None = None,
) -> dict[str, Any]:
    """Report a mail as spam.

    Creates blocklist entries for the sender email and domain,
    then moves the mail to the spam/junk folder via IMAP.

    Args:
        db: Database session.
        user_id: Current user ID.
        mail_account_id: Mail account the message belongs to.
        mail_uid: IMAP UID of the message.
        sender_email: Sender's email address.
        subject: Email subject (optional, for pattern extraction).

    Returns:
        Dict with ``blocked_entries_created``, ``mail_moved``, and ``message``.
    """
    created = 0

    # Block the sender email
    if await _upsert_blocklist_entry(
        db,
        user_id,
        BlocklistEntryType.EMAIL,
        sender_email,
        BlocklistSource.REPORTED,
        mail_uid,
    ):
        created += 1

    # Block the sender domain
    domain = _extract_domain(sender_email)
    if domain and await _upsert_blocklist_entry(
        db,
        user_id,
        BlocklistEntryType.DOMAIN,
        domain,
        BlocklistSource.REPORTED,
        mail_uid,
    ):
        created += 1

    await db.flush()

    # Move mail to spam via IMAP
    mail_moved = False
    stmt = select(MailAccount).where(
        MailAccount.id == mail_account_id,
        MailAccount.user_id == user_id,
    )
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()

    if account:
        # Load current folder from tracked email.
        # Use scalars().first() because the same UID number can
        # exist in different folders after initial scan.
        current_folder = "INBOX"
        tracked_stmt = select(TrackedEmail.current_folder).where(
            TrackedEmail.mail_account_id == mail_account_id,
            TrackedEmail.mail_uid == mail_uid,
        )
        tracked_result = await db.execute(tracked_stmt)
        tracked_folder = tracked_result.scalars().first()
        if tracked_folder:
            current_folder = tracked_folder

        try:
            move_outcome = await execute_imap_actions(
                account,
                mail_uid,
                ["move_to_spam", "mark_as_read"],
                source_folder=current_folder,
            )
            mail_moved = True

            # Update current_folder (and mail_uid) after successful move
            if move_outcome.folder:
                update_stmt = select(TrackedEmail).where(
                    TrackedEmail.mail_account_id == mail_account_id,
                    TrackedEmail.mail_uid == mail_uid,
                    TrackedEmail.current_folder == current_folder,
                )
                update_result = await db.execute(update_stmt)
                tracked = update_result.scalar_one_or_none()
                if tracked:
                    tracked.current_folder = move_outcome.folder
                    if move_outcome.new_uid:
                        tracked.mail_uid = move_outcome.new_uid
                    await db.flush()
        except Exception:
            logger.exception(
                "spam_report_imap_move_failed",
                user_id=str(user_id),
                mail_uid=mail_uid,
            )

    logger.info(
        "spam_reported",
        user_id=str(user_id),
        sender=sender_email,
        entries_created=created,
        mail_moved=mail_moved,
    )

    return {
        "blocked_entries_created": created,
        "mail_moved": mail_moved,
        "message": f"Sender {sender_email} blocked, mail moved to spam."
        if mail_moved
        else f"Sender {sender_email} blocked, but mail could not be moved.",
    }


async def report_contact_as_spam(
    db: AsyncSession,
    user_id: UUID,
    contact_id: UUID,
) -> dict[str, Any]:
    """Report a contact as spam — block all their emails and delete the contact.

    Args:
        db: Database session.
        user_id: Current user ID.
        contact_id: The contact to report.

    Returns:
        Dict with ``blocked_entries_created``, ``mail_moved``, and ``message``.
    """
    stmt = select(Contact).where(
        Contact.id == contact_id,
        Contact.user_id == user_id,
    )
    result = await db.execute(stmt)
    contact = result.scalar_one_or_none()

    if contact is None:
        return {
            "blocked_entries_created": 0,
            "mail_moved": False,
            "message": "Contact not found.",
        }

    created = 0
    emails: list[str] = contact.emails or []

    for email in emails:
        if await _upsert_blocklist_entry(
            db,
            user_id,
            BlocklistEntryType.EMAIL,
            email,
            BlocklistSource.REPORTED,
        ):
            created += 1

        domain = _extract_domain(email)
        if domain and await _upsert_blocklist_entry(
            db,
            user_id,
            BlocklistEntryType.DOMAIN,
            domain,
            BlocklistSource.REPORTED,
        ):
            created += 1

    # Delete the contact
    await db.delete(contact)
    await db.flush()

    logger.info(
        "contact_reported_as_spam",
        user_id=str(user_id),
        contact_id=str(contact_id),
        contact_name=contact.display_name,
        emails_blocked=len(emails),
        entries_created=created,
    )

    return {
        "blocked_entries_created": created,
        "mail_moved": False,
        "message": f"Contact '{contact.display_name}' deleted and {len(emails)} email(s) blocked.",
    }


async def is_blocked(
    db: AsyncSession,
    user_id: UUID,
    sender_email: str,
    subject: str | None = None,
) -> bool:
    """Check whether a sender or subject matches any blocklist entry.

    Checks email address, domain, and (if provided) subject patterns.

    Args:
        db: Database session.
        user_id: User whose blocklist to check.
        sender_email: Sender email address.
        subject: Email subject (optional).

    Returns:
        True if the sender/subject is on the blocklist.
    """
    sender_lower = sender_email.lower().strip()
    domain = _extract_domain(sender_email)

    conditions = [
        # Exact email match
        ((SpamBlocklistEntry.entry_type == BlocklistEntryType.EMAIL) & (SpamBlocklistEntry.value == sender_lower)),
    ]

    if domain:
        conditions.append(
            (SpamBlocklistEntry.entry_type == BlocklistEntryType.DOMAIN) & (SpamBlocklistEntry.value == domain)
        )

    stmt = (
        select(func.count())
        .select_from(SpamBlocklistEntry)
        .where(
            SpamBlocklistEntry.user_id == user_id,
            or_(*conditions),
        )
    )
    count = (await db.execute(stmt)).scalar_one()

    if count > 0:
        return True

    # Check subject patterns
    if subject:
        pattern_stmt = select(SpamBlocklistEntry.value).where(
            SpamBlocklistEntry.user_id == user_id,
            SpamBlocklistEntry.entry_type == BlocklistEntryType.PATTERN,
        )
        pattern_result = await db.execute(pattern_stmt)
        patterns = pattern_result.scalars().all()

        subject_lower = subject.lower()
        for pattern in patterns:
            if pattern.lower() in subject_lower:
                return True

    return False


async def get_blocklist_context(
    db: AsyncSession,
    user_id: UUID,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Get blocklist entries for AI prompt context.

    Returns a compact list of entries suitable for injection into
    the spam detection prompt template.

    Args:
        db: Database session.
        user_id: User whose blocklist to retrieve.
        limit: Maximum entries to return.

    Returns:
        List of dicts with ``type`` and ``value`` keys.
    """
    stmt = (
        select(SpamBlocklistEntry.entry_type, SpamBlocklistEntry.value)
        .where(SpamBlocklistEntry.user_id == user_id)
        .order_by(SpamBlocklistEntry.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [{"type": row.entry_type.value, "value": row.value} for row in result]
