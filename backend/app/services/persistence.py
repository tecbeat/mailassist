"""Plugin data persistence.

Saves AI plugin results (email summaries, detected newsletters, extracted
coupons) to the database.  Provides a single implementation used by both
``mail_processor`` (auto-mode, with Pydantic response models) and
``approval_executor`` (after user approval, with stored dict data).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import delete, select
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
    ExtractedOtpCode,
    SpamDetectionResult,
)
from app.models.mail import UrgencyLevel

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Field length limits (must match DB column constraints)
# ---------------------------------------------------------------------------

_LEN_EMAIL_ADDRESS = 320
_LEN_LABEL = 200
_LEN_REASON = 500
_LEN_FOLDER = 500
_LEN_STORE = 200
_LEN_CODE = 100
_LEN_LOCATION = 500
_LEN_TONE = 50
_LEN_CONTACT_NAME = 255
_LEN_REASONING = 500
_LEN_OTP_CODE = 2000
_LEN_OTP_DESCRIPTION = 500
_LEN_OTP_SERVICE = 100
_LEN_OTP_CODE_TYPE = 30
_LEN_OTP_URL = 2000


def _trunc(value: str | None, max_len: int) -> str | None:
    """Truncate *value* to *max_len* characters, or return ``None`` if falsy.

    Centralises the ``field[:n] if field else None`` pattern that was
    scattered across every persistence save function.
    """
    if not value:
        return None
    return value[:max_len]


def _trunc_required(value: str, max_len: int) -> str:
    """Truncate a non-optional string field to *max_len* characters."""
    return value[:max_len]


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
    summary: str,
    key_points: list[str],
    urgency: str | UrgencyLevel = UrgencyLevel.MEDIUM,
    action_required: bool = False,
    action_description: str | None = None,
    mail_id: UUID,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist an AI-generated email summary (upsert).

    Uses INSERT ... ON CONFLICT DO UPDATE so re-processing the same
    mail simply overwrites the previous summary instead of raising a
    ``UniqueViolationError`` on ``uq_summary_user_mail_id``.
    """
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "user_id": user_id,
        "mail_id": mail_id,
        "summary": summary,
        "key_points": key_points,
        "urgency": urgency,
        "action_required": action_required,
        "action_description": action_description,
        "created_at": now,
        "updated_at": now,
    }

    # Columns to overwrite on conflict (everything except PK + created_at)
    update_cols = {k: v for k, v in values.items() if k not in ("id", "user_id", "created_at")}
    update_cols["updated_at"] = now

    stmt = (
        pg_insert(EmailSummary)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_summary_user_mail_id",
            set_=update_cols,
        )
    )

    async with _persist(own_session, db) as session:
        await session.execute(stmt)

    logger.info("email_summary_saved", mail_id=str(mail_id), urgency=urgency)


async def save_newsletter(
    *,
    user_id: UUID,
    is_newsletter: bool,
    newsletter_name: str = "Unknown",
    sender_address: str = "unknown",
    unsubscribe_url: str | None = None,
    has_unsubscribe: bool = False,
    mail_id: UUID,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist a detected newsletter (upsert on mail_id).

    If ``is_newsletter`` is False, this is a no-op.
    """
    if not is_newsletter:
        return

    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "user_id": user_id,
        "mail_id": mail_id,
        "newsletter_name": newsletter_name or "Unknown",
        "sender_address": sender_address[:_LEN_EMAIL_ADDRESS] if sender_address else "unknown",
        "unsubscribe_url": unsubscribe_url,
        "has_unsubscribe": has_unsubscribe,
        "created_at": now,
        "updated_at": now,
    }
    update_cols = {k: v for k, v in values.items() if k not in ("id", "user_id", "created_at")}
    update_cols["updated_at"] = now

    stmt = (
        pg_insert(DetectedNewsletter)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_newsletter_mail_id",
            set_=update_cols,
        )
    )

    async with _persist(own_session, db) as session:
        await session.execute(stmt)

    logger.info(
        "newsletter_saved",
        mail_id=str(mail_id),
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
    has_coupons: bool,
    coupons: list[dict[str, Any]],
    mail_id: UUID,
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
                mail_id=mail_id,
                code=_trunc(code, _LEN_CODE),
                description=description[:300] if description else None,
                store=_trunc(store, _LEN_STORE),
                expires_at=_parse_coupon_expiry(raw_expires),
                valid_from=_parse_coupon_expiry(raw_valid_from),
            )
        )

    async with _persist(own_session, db) as session:
        # Delete existing coupons for this mail to prevent duplicates on reprocess
        await session.execute(delete(ExtractedCoupon).where(ExtractedCoupon.mail_id == mail_id))
        for record in records:
            session.add(record)

    logger.info("coupons_saved", mail_id=str(mail_id), count=len(records))


async def save_applied_labels(
    *,
    user_id: UUID,
    labels: list[str],
    existing_labels: set[str] | None = None,
    mail_id: UUID,
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
                mail_id=mail_id,
                label=_trunc_required(lbl, _LEN_LABEL),
                is_new_label=lbl.lower() not in existing_set,
            )
        )

    async with _persist(own_session, db) as session:
        # Delete existing labels for this mail to prevent duplicates on reprocess
        await session.execute(delete(AppliedLabel).where(AppliedLabel.mail_id == mail_id))
        for record in records:
            session.add(record)

    logger.info("applied_labels_saved", mail_id=str(mail_id), count=len(records))


async def save_assigned_folder(
    *,
    user_id: UUID,
    folder: str,
    confidence: float | None = None,
    reason: str | None = None,
    existing_folders: set[str] | None = None,
    mail_id: UUID,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist an assigned folder record (upsert on mail_id)."""
    existing_set = {f.lower() for f in (existing_folders or set())}
    values = {
        "id": uuid4(),
        "user_id": user_id,
        "mail_id": mail_id,
        "folder": _trunc_required(folder, _LEN_FOLDER),
        "confidence": confidence,
        "reason": _trunc(reason, _LEN_REASON),
        "is_new_folder": folder.lower() not in existing_set,
        "created_at": datetime.now(UTC),
    }
    update_cols = {k: v for k, v in values.items() if k not in ("id", "user_id", "created_at")}
    stmt = (
        pg_insert(AssignedFolder)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_assigned_folder_mail_id",
            set_=update_cols,
        )
    )

    async with _persist(own_session, db) as session:
        await session.execute(stmt)

    logger.info("assigned_folder_saved", mail_id=str(mail_id), folder=folder)


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
    has_event: bool,
    title: str | None = None,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    location: str | None = None,
    description: str | None = None,
    is_all_day: bool = False,
    mail_id: UUID,
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

    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "user_id": user_id,
        "mail_id": mail_id,
        "title": title[:300],
        "start": parsed_start,
        "end": parsed_end,
        "location": _trunc(location, _LEN_LOCATION),
        "description": description[:2000] if description else None,
        "is_all_day": is_all_day,
        "created_at": now,
        "updated_at": now,
    }
    update_cols = {k: v for k, v in values.items() if k not in ("id", "user_id", "created_at")}
    update_cols["updated_at"] = now

    stmt = (
        pg_insert(CalendarEvent)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_calendar_event_mail_id",
            set_=update_cols,
        )
        .returning(CalendarEvent.__table__)
    )

    async with _persist(own_session, db) as session:
        result = await session.execute(stmt)
        row = result.fetchone()
        # Build a detached record for CalDAV sync
        record = CalendarEvent(
            id=row.id if row else values["id"],
            user_id=user_id,
            mail_id=mail_id,
            title=values["title"],
            start=parsed_start,
            end=parsed_end,
            location=values["location"],
            description=values["description"],
            is_all_day=is_all_day,
        )

    logger.info("calendar_event_saved", mail_id=str(mail_id), title=title)

    # --- CalDAV push ---
    await _sync_event_to_caldav(record)


async def save_auto_reply(
    *,
    user_id: UUID,
    should_reply: bool,
    draft_body: str | None = None,
    tone: str | None = None,
    reasoning: str | None = None,
    mail_id: UUID,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist an auto-reply record (upsert on mail_id).

    If ``should_reply`` is False or ``draft_body`` is missing, this is a no-op.
    """
    if not should_reply or not draft_body:
        logger.debug(
            "auto_reply_skipped_persistence",
            mail_id=str(mail_id),
            should_reply=should_reply,
            has_draft_body=bool(draft_body),
        )
        return

    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "user_id": user_id,
        "mail_id": mail_id,
        "draft_body": draft_body[:5000],
        "tone": _trunc(tone, _LEN_TONE),
        "reasoning": reasoning[:300] if reasoning else None,
        "created_at": now,
        "updated_at": now,
    }
    update_cols = {k: v for k, v in values.items() if k not in ("id", "user_id", "created_at")}
    update_cols["updated_at"] = now

    stmt = (
        pg_insert(AutoReplyRecord)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_auto_reply_mail_id",
            set_=update_cols,
        )
    )

    async with _persist(own_session, db) as session:
        await session.execute(stmt)

    logger.info("auto_reply_saved", mail_id=str(mail_id))


async def save_contact_assignment(
    *,
    user_id: UUID,
    contact_id: str | None = None,
    contact_name: str,
    confidence: float,
    reasoning: str | None = None,
    is_new_contact_suggestion: bool = False,
    auto_writeback: bool = False,
    sender_email: str | None = None,
    mail_id: UUID,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist an AI contact assignment record (upsert on mail_id).

    Args:
        auto_writeback: If True, automatically add the sender email to the
            contact's address list (DB + CardDAV).  Should only be True when the
            user's plugin approval mode is ``auto`` **or** when the assignment
            was explicitly approved by the user.
    """
    now = datetime.now(UTC)
    values = {
        "id": uuid4(),
        "user_id": user_id,
        "mail_id": mail_id,
        "contact_id": UUID(contact_id) if contact_id else None,
        "contact_name": _trunc_required(contact_name, _LEN_CONTACT_NAME),
        "confidence": confidence,
        "reasoning": _trunc(reasoning, _LEN_REASONING),
        "is_new_contact_suggestion": is_new_contact_suggestion,
        "created_at": now,
    }
    update_cols = {k: v for k, v in values.items() if k not in ("id", "user_id", "created_at")}

    stmt = (
        pg_insert(ContactAssignment)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_contact_assignment_mail_id",
            set_=update_cols,
        )
    )

    async with _persist(own_session, db) as session:
        await session.execute(stmt)

    logger.info(
        "contact_assignment_saved",
        mail_id=str(mail_id),
        contact_name=contact_name,
        is_new=is_new_contact_suggestion,
    )

    # Auto-add sender email to the assigned contact (DB + CardDAV + cache).
    # Only when explicitly allowed (auto mode or user-approved assignment).
    if auto_writeback and contact_id and sender_email and not is_new_contact_suggestion:
        from app.services.contacts.writeback import auto_add_sender_email

        await auto_add_sender_email(user_id, UUID(contact_id), sender_email)


async def save_spam_detection(
    *,
    user_id: UUID,
    is_spam: bool,
    confidence: float,
    reason: str | None = None,
    source: str = "ai",
    mail_id: UUID,
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
        "mail_id": mail_id,
        "is_spam": is_spam,
        "confidence": confidence,
        "reason": _trunc(reason, _LEN_REASON),
        "source": source,
        "created_at": now,
        "updated_at": now,
    }

    update_cols = {k: v for k, v in values.items() if k not in ("id", "user_id", "created_at")}
    update_cols["updated_at"] = now

    stmt = (
        pg_insert(SpamDetectionResult)
        .values(**values)
        .on_conflict_do_update(
            constraint="uq_spam_result_user_mail_id",
            set_=update_cols,
        )
    )

    async with _persist(own_session, db) as session:
        await session.execute(stmt)

    logger.info("spam_detection_saved", mail_id=str(mail_id), is_spam=is_spam, source=source)


async def save_otp(
    *,
    user_id: UUID,
    has_codes: bool,
    codes: list[dict[str, Any]],
    mail_id: UUID,
    own_session: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Persist extracted OTP codes.

    If ``has_codes`` is False or ``codes`` is empty, this is a no-op.

    Each code dict should have keys: ``code``, and optionally
    ``service``, ``code_type``, ``expires_in_minutes``.
    """
    if not has_codes or not codes:
        return

    now = datetime.now(UTC)
    records = []
    for code_item in codes:
        code = code_item.get("code", "") if isinstance(code_item, dict) else getattr(code_item, "code", "")
        service = code_item.get("service") if isinstance(code_item, dict) else getattr(code_item, "service", None)
        description = (
            code_item.get("description") if isinstance(code_item, dict) else getattr(code_item, "description", None)
        )
        code_type = (
            code_item.get("code_type", "other")
            if isinstance(code_item, dict)
            else getattr(code_item, "code_type", "other")
        )
        expires_in = (
            code_item.get("expires_in_minutes")
            if isinstance(code_item, dict)
            else getattr(code_item, "expires_in_minutes", None)
        )
        url = code_item.get("url") if isinstance(code_item, dict) else getattr(code_item, "url", None)

        expires_at = None
        if isinstance(expires_in, int) and expires_in > 0:
            expires_at = now + timedelta(minutes=min(expires_in, 1440))

        records.append(
            ExtractedOtpCode(
                user_id=user_id,
                mail_id=mail_id,
                code=_trunc_required(code, _LEN_OTP_CODE),
                description=_trunc(description, _LEN_OTP_DESCRIPTION),
                service=_trunc(service, _LEN_OTP_SERVICE),
                code_type=code_type[:_LEN_OTP_CODE_TYPE] if code_type else "other",
                url=_trunc(url, _LEN_OTP_URL),
                expires_at=expires_at,
            )
        )

    async with _persist(own_session, db) as session:
        # Delete existing OTP codes for this mail to prevent duplicates on reprocess
        await session.execute(delete(ExtractedOtpCode).where(ExtractedOtpCode.mail_id == mail_id))
        for record in records:
            session.add(record)

    logger.info("otp_codes_saved", mail_id=str(mail_id), count=len(records))
