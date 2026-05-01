"""Email summary API endpoints.

Provides listing, detail, and filter configuration for AI-generated email summaries.
Also exposes a diagnostic endpoint for completed mails that are missing summaries.
"""

from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import case, select

from app.api.deps import CurrentUserId, DbSession, build_paginated_response, get_or_404, paginate, sanitize_like
from app.models import EmailSummary
from app.schemas.summary import (
    EmailSummaryListResponse,
    EmailSummaryResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/summaries", tags=["summaries"])


@router.get("")
async def list_summaries(
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    urgency: str | None = None,
    action_required: bool | None = None,
    search: str | None = Query(default=None, description="Text search across subject, sender, and summary"),
    sort: Literal["newest", "oldest"] = Query(default="newest", description="Sort order"),
) -> EmailSummaryListResponse:
    """List email summaries with pagination and optional filters."""
    uid = UUID(user_id)

    # Base query
    base_stmt = select(EmailSummary).where(EmailSummary.user_id == uid)

    if urgency:
        base_stmt = base_stmt.where(EmailSummary.urgency == urgency)
    if action_required is not None:
        base_stmt = base_stmt.where(EmailSummary.action_required == action_required)
    if search:
        pattern = f"%{sanitize_like(search)}%"
        base_stmt = base_stmt.where(
            EmailSummary.mail_subject.ilike(pattern)
            | EmailSummary.mail_from.ilike(pattern)
            | EmailSummary.summary.ilike(pattern)
        )

    # Sort by mail_date (actual email date), falling back to created_at for records without a mail_date
    sort_col = case(
        (EmailSummary.mail_date.is_not(None), EmailSummary.mail_date),
        else_=EmailSummary.created_at,
    )
    order_col = sort_col.asc() if sort == "oldest" else sort_col.desc()
    base_stmt = base_stmt.order_by(order_col)

    result = await paginate(db, base_stmt, page, per_page)

    return build_paginated_response(result, EmailSummaryResponse, EmailSummaryListResponse)


@router.get("/{summary_id}")
async def get_summary(
    summary_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> EmailSummaryResponse:
    """Get a single email summary with full details."""
    summary = await get_or_404(db, EmailSummary, summary_id, user_id, "Summary not found")
    return EmailSummaryResponse.model_validate(summary)


@router.delete("/{summary_id}", status_code=204)
async def delete_summary(
    summary_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a single email summary."""
    summary = await get_or_404(db, EmailSummary, summary_id, user_id, "Summary not found")
    await db.delete(summary)
    await db.flush()
    logger.info("summary_deleted", summary_id=str(summary_id), user_id=user_id)
