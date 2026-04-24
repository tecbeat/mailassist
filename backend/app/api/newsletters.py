"""Newsletter API endpoints.

Provides listing and detail views for AI-detected newsletters,
including unsubscribe URL access.
"""

from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentUserId, DbSession, get_or_404, paginate, sanitize_like
from app.models import DetectedNewsletter
from app.schemas.newsletter import (
    DetectedNewsletterListResponse,
    DetectedNewsletterResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/newsletters", tags=["newsletters"])


@router.get("")
async def list_newsletters(
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    sender: str | None = None,
    sort: Literal["newest", "oldest", "name"] = Query(default="newest", description="Sort order"),
) -> DetectedNewsletterListResponse:
    """List detected newsletters with pagination and optional sender filter."""
    uid = UUID(user_id)

    base_stmt = select(DetectedNewsletter).where(DetectedNewsletter.user_id == uid)

    if sender:
        base_stmt = base_stmt.where(DetectedNewsletter.sender_address.ilike(f"%{sanitize_like(sender)}%"))

    if sort == "oldest":
        order_col = DetectedNewsletter.created_at.asc()
    elif sort == "name":
        order_col = DetectedNewsletter.newsletter_name.asc()
    else:
        order_col = DetectedNewsletter.created_at.desc()

    base_stmt = base_stmt.order_by(order_col)
    result = await paginate(db, base_stmt, page, per_page)

    return DetectedNewsletterListResponse(
        items=[DetectedNewsletterResponse.model_validate(n) for n in result.items],
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
    )


@router.get("/{newsletter_id}")
async def get_newsletter(
    newsletter_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> DetectedNewsletterResponse:
    """Get a single detected newsletter with full details."""
    newsletter = await get_or_404(db, DetectedNewsletter, newsletter_id, user_id, "Newsletter not found")
    return DetectedNewsletterResponse.model_validate(newsletter)


@router.delete("/{newsletter_id}", status_code=204)
async def delete_newsletter(
    newsletter_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a detected newsletter record."""
    newsletter = await get_or_404(db, DetectedNewsletter, newsletter_id, user_id, "Newsletter not found")

    await db.delete(newsletter)
    await db.flush()
    logger.info("newsletter_deleted", newsletter_id=str(newsletter_id))
