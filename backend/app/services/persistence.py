"""Plugin data persistence.

Saves AI plugin results (email summaries, detected newsletters, extracted
coupons) to the database.  Provides a single implementation used by both
``mail_processor`` (auto-mode, with Pydantic response models) and
``approval_executor`` (after user approval, with stored dict data).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import get_session_ctx
from app.models import (
    AppliedLabel,
    AssignedFolder,
    AutoReplyRecord,
    CalDAVConfig,
    CalendarEvent,
    ContactAssignment,
    DetectedNewsletter,
    EmailSummary,
    ExtractedCoupon,
    SpamDetectionResult,
)
from app.models.mail import UrgencyLevel

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


@asynccontextmanager
async def _persist(
    own_session: bool,
    db: AsyncSession | None,
) -> AsyncIterator[AsyncSession]:
    """Yield a session for persistence, committing if we own it.

    Replaces the 7x copy-pasted ``own_session`` / ``db`` branching
    pattern throughout this module.
    """
    if own_session:
        async with get_session_ctx() as session:
            yield session
        return
    if db is not None:
        yield db
        await db.flush()
        return
    raise ValueError("Either own_session=True or db must be provided")


def parse_date_field(value: str | datetime) -> datetime | None:
    """Convert a string or datetime to a timezone-aware datetime.

    Returns None if the value cannot be parsed.
    """
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(str(value))
    except (ValueError, TypeError):
        logger.warning("unparseable_date_field", raw=str(value)[:50])
        return None


async def save_email_summary(
    *,
    user_id: UUID,
    account_id: UUID,
    mail_uid: str,
    mail_subject: str | None = None,
    mail_from: str | None = None,
    mail_date: str | datetime | None = None,
    summary: str,
    key_points: list[str],
    urgency: str | UrgencyLevel = UrgencyLevel.MEDIUM,
    action_required: bool = False,
    action_description: str | None = None,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist an AI-generated email summary (upsert).

    Uses INSERT ... ON CONFLICT DO UPDATE so re-processing the same
    mail simply overwrites the previous summary instead of raising a
    ``UniqueViolationError`` on ``uq_summary_user_account_mail``.
    """
    now = datetime.now(UTC)
    parsed_mail_date = parse_date_field(mail_date) if mail_date is not None else None
    values = {
        "id": uuid4(),
        "user_id": user_id,
        "mail_account_id": account_id,
        "mail_uid": mail_uid,
        "mail_subject": mail_subject[:998] if mail_subject else None,
        "mail_from": mail_from[:320] if mail_from else None,
        "mail_date": parsed_mail_date,
        "summary": summary,
        "key_points": key_points,
        "urgency": urgency,
        "action_required": action_required,
        "action_description": action_description,
        "created_at": now,
        "updated_at": now,
    }

    # Columns to overwrite on conflict (everything except PK + created_at)
    update_cols = {
        k: v for k, v in values.items() if k not in ("id", "user_id", "mail_account_id", "mail_uid", "created_at")
    }
    update_cols["updated_at"] = now

    stmt = (
        pg_insert(EmailSummary)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_summary_user_account_mail",
            set_=update_cols,
        )
    )

    async with _persist(own_session, db) as session:
        await session.execute(stmt)

    logger.info("email_summary_saved", mail_uid=mail_uid, urgency=urgency)


async def save_newsletter(
    *,
    user_id: UUID,
    account_id: UUID,
    mail_uid: str,
    is_newsletter: bool,
    newsletter_name: str = "Unknown",
    sender_address: str = "unknown",
    mail_subject: str | None = None,
    unsubscribe_url: str | None = None,
    has_unsubscribe: bool = False,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist a detected newsletter.

    If ``is_newsletter`` is False, this is a no-op.
    """
    if not is_newsletter:
        return

    record = DetectedNewsletter(
        user_id=user_id,
        mail_account_id=account_id,
        mail_uid=mail_uid,
        newsletter_name=newsletter_name or "Unknown",
        sender_address=sender_address[:320] if sender_address else "unknown",
        mail_subject=mail_subject[:998] if mail_subject else None,
        unsubscribe_url=unsubscribe_url,
        has_unsubscribe=has_unsubscribe,
    )

    async with _persist(own_session, db) as session:
        session.add(record)

    logger.info(
        "newsletter_saved",
        mail_uid=mail_uid,
        newsletter_name=newsletter_name,
        has_unsubscribe=has_unsubscribe,
    )


def _parse_coupon_expiry(raw: str | None) -> datetime | None:
    """Parse a coupon expiry date string into a UTC datetime."""
    if not raw:
        return None
    try:
        from datetime import date as date_type

        parsed = date_type.fromisoformat(raw)
        return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)
    except (ValueError, TypeError):
        return None


async def save_coupons(
    *,
    user_id: UUID,
    account_id: UUID,
    mail_uid: str,
    has_coupons: bool,
    coupons: list[dict[str, Any]],
    sender_email: str | None = None,
    mail_subject: str | None = None,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist extracted coupons.

    If ``has_coupons`` is False or ``coupons`` is empty, this is a no-op.

    Each coupon dict should have keys: ``code``, and optionally
    ``description``, ``store``, ``expires_at``.
    """
    if not has_coupons or not coupons:
        return

    records = []
    for coupon in coupons:
        code = coupon.get("code", "") if isinstance(coupon, dict) else getattr(coupon, "code", "")
        description = coupon.get("description") if isinstance(coupon, dict) else getattr(coupon, "description", None)
        store = coupon.get("store") if isinstance(coupon, dict) else getattr(coupon, "store", None)
        raw_expires = coupon.get("expires_at") if isinstance(coupon, dict) else getattr(coupon, "expires_at", None)
        raw_valid_from = coupon.get("valid_from") if isinstance(coupon, dict) else getattr(coupon, "valid_from", None)

        records.append(
            ExtractedCoupon(
                user_id=user_id,
                mail_account_id=account_id,
                mail_uid=mail_uid,
                sender_email=sender_email[:320] if sender_email else None,
                mail_subject=mail_subject[:998] if mail_subject else None,
                code=code[:100] if code else None,
                description=description[:300] if description else None,
                store=store[:200] if store else None,
                expires_at=_parse_coupon_expiry(raw_expires),
                valid_from=_parse_coupon_expiry(raw_valid_from),
            )
        )

    async with _persist(own_session, db) as session:
        for record in records:
            session.add(record)

    logger.info("coupons_saved", mail_uid=mail_uid, count=len(records))


async def save_applied_labels(
    *,
    user_id: UUID,
    account_id: UUID,
    mail_uid: str,
    mail_subject: str | None = None,
    mail_from: str | None = None,
    labels: list[str],
    existing_labels: set[str] | None = None,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist applied label records.

    If ``labels`` is empty, this is a no-op.
    """
    if not labels:
        return

    existing_set = {lbl.lower() for lbl in (existing_labels or set())}
    records = []
    for lbl in labels:
        records.append(
            AppliedLabel(
                user_id=user_id,
                mail_account_id=account_id,
                mail_uid=mail_uid,
                mail_subject=mail_subject[:998] if mail_subject else None,
                mail_from=mail_from[:320] if mail_from else None,
                label=lbl[:200],
                is_new_label=lbl.lower() not in existing_set,
            )
        )

    async with _persist(own_session, db) as session:
        for record in records:
            session.add(record)

    logger.info("applied_labels_saved", mail_uid=mail_uid, count=len(records))


async def save_assigned_folder(
    *,
    user_id: UUID,
    account_id: UUID,
    mail_uid: str,
    mail_subject: str | None = None,
    mail_from: str | None = None,
    folder: str,
    confidence: float | None = None,
    reason: str | None = None,
    existing_folders: set[str] | None = None,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist an assigned folder record (upsert on account+uid)."""
    existing_set = {f.lower() for f in (existing_folders or set())}
    values = {
        "id": uuid4(),
        "user_id": user_id,
        "mail_account_id": account_id,
        "mail_uid": mail_uid,
        "mail_subject": mail_subject[:998] if mail_subject else None,
        "mail_from": mail_from[:320] if mail_from else None,
        "folder": folder[:500],
        "confidence": confidence,
        "reason": reason[:200] if reason else None,
        "is_new_folder": folder.lower() not in existing_set,
        "created_at": datetime.now(UTC),
    }
    update_cols = {
        k: v for k, v in values.items() if k not in ("id", "user_id", "mail_account_id", "mail_uid", "created_at")
    }
    stmt = (
        pg_insert(AssignedFolder)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_assigned_folder_account_uid",
            set_=update_cols,
        )
    )

    async with _persist(own_session, db) as session:
        await session.execute(stmt)

    logger.info("assigned_folder_saved", mail_uid=mail_uid, folder=folder)


async def _sync_event_to_caldav(record: CalendarEvent) -> None:
    """Attempt to push a calendar event to CalDAV.

    Updates ``caldav_synced`` / ``caldav_error`` on the record.
    Never raises — failures are logged and stored.
    """
    from app.services.calendar import create_calendar_event, get_caldav_credentials

    # --- Load CalDAV config and extract all needed values while session is open ---
    caldav_url: str | None = None
    default_calendar: str | None = None
    encrypted_creds: bytes | None = None

    async with get_session_ctx() as session:
        stmt = select(CalDAVConfig).where(
            CalDAVConfig.user_id == record.user_id,
            CalDAVConfig.is_active.is_(True),
        )
        config = (await session.execute(stmt)).scalar_one_or_none()
        if config is not None:
            caldav_url = config.caldav_url
            default_calendar = config.default_calendar
            encrypted_creds = bytes(config.encrypted_credentials)

    if caldav_url is None or encrypted_creds is None:
        logger.debug("caldav_sync_skipped_no_config", user_id=str(record.user_id))
        return

    # start/end are now proper datetime columns
    start = record.start
    if start is None:
        logger.warning("caldav_sync_skipped_no_start", event_id=str(record.id))
        return

    end = record.end

    username, password = get_caldav_credentials(encrypted_creds)

    caldav_uid: str | None = None
    try:
        result = await create_calendar_event(
            caldav_url=caldav_url,
            username=username,
            password=password,
            calendar_name=default_calendar or "",
            title=record.title,
            start=start,
            end=end,
            location=record.location,
            description=record.description,
            is_all_day=record.is_all_day,
        )
        caldav_synced = True
        caldav_error = None
        caldav_uid = result.uid
        logger.info("caldav_sync_success", event_id=str(record.id), title=record.title)
    except Exception as exc:
        caldav_synced = False
        caldav_error = str(exc)[:2000]
        logger.warning("caldav_sync_failed", event_id=str(record.id), error=caldav_error)

    # Persist sync status
    async with get_session_ctx() as session:
        event_stmt = select(CalendarEvent).where(CalendarEvent.id == record.id)
        event = (await session.execute(event_stmt)).scalar_one_or_none()
        if event:
            event.caldav_synced = caldav_synced
            event.caldav_error = caldav_error
            if caldav_uid:
                event.caldav_uid = caldav_uid


async def save_calendar_event(
    *,
    user_id: UUID,
    account_id: UUID,
    mail_uid: str,
    mail_subject: str | None = None,
    mail_from: str | None = None,
    has_event: bool,
    title: str | None = None,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    location: str | None = None,
    description: str | None = None,
    is_all_day: bool = False,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist a calendar event record and push to CalDAV if configured.

    If ``has_event`` is False or ``title`` is missing, this is a no-op.
    The DB insert always happens first.  CalDAV sync is attempted afterwards;
    failures are recorded on the row but never prevent the DB save.
    """
    if not has_event or not title:
        return

    # Parse start/end strings to datetime if needed
    parsed_start = parse_date_field(start) if start is not None else None
    parsed_end = parse_date_field(end) if end is not None else None

    record = CalendarEvent(
        user_id=user_id,
        mail_account_id=account_id,
        mail_uid=mail_uid,
        mail_subject=mail_subject[:998] if mail_subject else None,
        mail_from=mail_from[:320] if mail_from else None,
        title=title[:300],
        start=parsed_start,
        end=parsed_end,
        location=location[:500] if location else None,
        description=description[:2000] if description else None,
        is_all_day=is_all_day,
    )

    async with _persist(own_session, db) as session:
        session.add(record)
        await session.flush()  # write to DB before detaching
        # Expunge before the session commits so the commit cannot expire record's
        # attributes — preventing DetachedInstanceError in _sync_event_to_caldav.
        session.expunge(record)

    logger.info("calendar_event_saved", mail_uid=mail_uid, title=title)

    # --- CalDAV push ---
    await _sync_event_to_caldav(record)


async def save_auto_reply(
    *,
    user_id: UUID,
    account_id: UUID,
    mail_uid: str,
    mail_subject: str | None = None,
    mail_from: str | None = None,
    should_reply: bool,
    draft_body: str | None = None,
    tone: str | None = None,
    reasoning: str | None = None,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist an auto-reply record.

    If ``should_reply`` is False or ``draft_body`` is missing, this is a no-op.
    """
    if not should_reply or not draft_body:
        logger.debug(
            "auto_reply_skipped_persistence",
            mail_uid=mail_uid,
            should_reply=should_reply,
            has_draft_body=bool(draft_body),
        )
        return

    record = AutoReplyRecord(
        user_id=user_id,
        mail_account_id=account_id,
        mail_uid=mail_uid,
        mail_subject=mail_subject[:998] if mail_subject else None,
        mail_from=mail_from[:320] if mail_from else None,
        draft_body=draft_body[:5000],
        tone=tone[:50] if tone else None,
        reasoning=reasoning[:300] if reasoning else None,
    )

    async with _persist(own_session, db) as session:
        session.add(record)

    logger.info("auto_reply_saved", mail_uid=mail_uid)


async def save_contact_assignment(
    *,
    user_id: UUID,
    account_id: UUID,
    mail_uid: str,
    mail_subject: str | None = None,
    mail_from: str | None = None,
    contact_id: str | None = None,
    contact_name: str,
    confidence: float,
    reasoning: str | None = None,
    is_new_contact_suggestion: bool = False,
    auto_writeback: bool = False,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist an AI contact assignment record.

    Args:
        auto_writeback: If True, automatically add the sender email to the
            contact's address list (DB + CardDAV).  Should only be True when the
            user's plugin approval mode is ``auto`` **or** when the assignment
            was explicitly approved by the user.
    """
    record = ContactAssignment(
        user_id=user_id,
        mail_account_id=account_id,
        mail_uid=mail_uid,
        mail_subject=mail_subject[:998] if mail_subject else None,
        mail_from=mail_from[:320] if mail_from else None,
        contact_id=UUID(contact_id) if contact_id else None,
        contact_name=contact_name[:255],
        confidence=confidence,
        reasoning=reasoning[:500] if reasoning else None,
        is_new_contact_suggestion=is_new_contact_suggestion,
    )

    async with _persist(own_session, db) as session:
        session.add(record)

    logger.info(
        "contact_assignment_saved",
        mail_uid=mail_uid,
        contact_name=contact_name,
        is_new=is_new_contact_suggestion,
    )

    # Auto-add sender email to the assigned contact (DB + CardDAV + cache).
    # Only when explicitly allowed (auto mode or user-approved assignment).
    if auto_writeback and contact_id and mail_from and not is_new_contact_suggestion:
        from app.services.contacts.writeback import auto_add_sender_email

        await auto_add_sender_email(user_id, UUID(contact_id), mail_from)


async def save_spam_detection(
    *,
    user_id: UUID,
    account_id: UUID,
    mail_uid: str,
    mail_subject: str | None = None,
    mail_from: str | None = None,
    is_spam: bool,
    confidence: float,
    reason: str | None = None,
    source: str = "ai",
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist a spam detection result (upsert).

    ``source`` indicates the detection method: ``"ai"`` for LLM-based
    detection, ``"blocklist"`` for blocklist matches.
    """
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "user_id": user_id,
        "mail_account_id": account_id,
        "mail_uid": mail_uid,
        "mail_subject": mail_subject[:998] if mail_subject else None,
        "mail_from": mail_from[:320] if mail_from else None,
        "is_spam": is_spam,
        "confidence": confidence,
        "reason": reason[:500] if reason else None,
        "source": source,
        "created_at": now,
        "updated_at": now,
    }

    update_cols = {
        k: v for k, v in values.items() if k not in ("id", "user_id", "mail_account_id", "mail_uid", "created_at")
    }
    update_cols["updated_at"] = now

    stmt = (
        pg_insert(SpamDetectionResult)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_spam_result_user_account_mail",
            set_=update_cols,
        )
    )

    async with _persist(own_session, db) as session:
        await session.execute(stmt)

    logger.info("spam_detection_saved", mail_uid=mail_uid, is_spam=is_spam, source=source)
