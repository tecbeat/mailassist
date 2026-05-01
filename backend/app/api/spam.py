"""Spam blocklist API endpoints.

Provides endpoints for reporting mails/contacts as spam and managing
the blocklist (CRUD).
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import CurrentUserId, DbSession, build_paginated_response, get_or_404, paginate, sanitize_like
from app.models import SpamBlocklistEntry
from app.models.spam import BlocklistEntryType, BlocklistSource
from app.schemas.spam import (
    BlocklistEntryCreate,
    BlocklistEntryResponse,
    BlocklistListResponse,
    SpamReportContactRequest,
    SpamReportRequest,
    SpamReportResult,
)
from app.services.spam import report_as_spam, report_contact_as_spam

logger = structlog.get_logger()

router = APIRouter(prefix="/api/spam", tags=["spam"])


# --- Spam Reporting ---


@router.post("/report")
async def report_spam(
    data: SpamReportRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> SpamReportResult:
    """Report a mail as spam.

    Moves the mail to the spam/junk folder and adds the sender
    email + domain to the blocklist.
    """
    result = await report_as_spam(
        db,
        user_id=user_id,
        mail_account_id=data.mail_account_id,
        mail_uid=data.mail_id,
        sender_email=data.sender_email,
        subject=data.subject,
    )
    return SpamReportResult(**result)


@router.post("/report-contact")
async def report_contact_spam(
    data: SpamReportContactRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> SpamReportResult:
    """Report a contact as spam.

    Blocks all email addresses associated with the contact and
    deletes the contact record.
    """
    result = await report_contact_as_spam(
        db,
        user_id=user_id,
        contact_id=data.contact_id,
    )
    return SpamReportResult(**result)


# --- Blocklist CRUD ---


@router.get("/blocklist")
async def list_blocklist(
    db: DbSession,
    user_id: CurrentUserId,
    search: str | None = Query(default=None, max_length=200, description="Search by value"),
    entry_type: BlocklistEntryType | None = Query(default=None, description="Filter by type: email, domain, pattern"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> BlocklistListResponse:
    """List blocklist entries with optional filtering and pagination."""
    uid = user_id
    base_stmt = select(SpamBlocklistEntry).where(SpamBlocklistEntry.user_id == uid)

    if search:
        pattern = f"%{sanitize_like(search)}%"
        base_stmt = base_stmt.where(SpamBlocklistEntry.value.ilike(pattern))

    if entry_type:
        base_stmt = base_stmt.where(SpamBlocklistEntry.entry_type == entry_type)

    base_stmt = base_stmt.order_by(SpamBlocklistEntry.created_at.desc())
    result = await paginate(db, base_stmt, page, per_page)

    return build_paginated_response(result, BlocklistEntryResponse, BlocklistListResponse)


@router.post("/blocklist", status_code=201)
async def create_blocklist_entry(
    data: BlocklistEntryCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> BlocklistEntryResponse:
    """Manually add a blocklist entry."""
    uid = user_id
    et = BlocklistEntryType(data.entry_type)

    # Check for duplicates
    stmt = select(SpamBlocklistEntry).where(
        SpamBlocklistEntry.user_id == uid,
        SpamBlocklistEntry.entry_type == et,
        SpamBlocklistEntry.value == data.value.lower().strip(),
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Entry already exists in blocklist.")

    entry = SpamBlocklistEntry(
        user_id=uid,
        entry_type=et,
        value=data.value.lower().strip(),
        source=BlocklistSource.MANUAL,
    )
    db.add(entry)
    await db.flush()

    logger.info(
        "blocklist_entry_created",
        user_id=user_id,
        entry_type=data.entry_type,
        value=data.value,
    )
    return BlocklistEntryResponse.model_validate(entry)


@router.delete("/blocklist/{entry_id}", status_code=204)
async def delete_blocklist_entry(
    entry_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Remove a blocklist entry."""
    entry = await get_or_404(db, SpamBlocklistEntry, entry_id, user_id, "Blocklist entry not found")
    await db.delete(entry)
    await db.flush()
    logger.info("blocklist_entry_deleted", entry_id=str(entry_id), user_id=user_id)
