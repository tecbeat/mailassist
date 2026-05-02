"""Mail Processing Queue API endpoints.

Provides a paginated view of all tracked emails with their processing
status, error details, and the ability to retry failed mails.
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from app.api.deps import CurrentUserId, DbSession, build_paginated_response, paginate, sanitize_like
from app.models.mail import ErrorType, TrackedEmail, TrackedEmailStatus
from app.schemas.queue import TrackedEmailListResponse, TrackedEmailResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.get("")
async def list_queue(
    db: DbSession,
    user_id: CurrentUserId,
    status: TrackedEmailStatus | None = Query(default=None, description="Filter by processing status"),
    account_id: UUID | None = Query(default=None, description="Filter by mail account"),
    error_type: ErrorType | None = Query(default=None, description="Filter by error type"),
    q: str | None = Query(default=None, max_length=200, description="Search by subject or sender"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> TrackedEmailListResponse:
    """List tracked emails in the processing queue for the current user.

    Returns a paginated, filterable view of all emails the worker has
    discovered, sorted by last updated descending (most recent first).
    """
    stmt = select(TrackedEmail).where(TrackedEmail.user_id == user_id)

    if status:
        stmt = stmt.where(TrackedEmail.status == status)

    if account_id:
        stmt = stmt.where(TrackedEmail.mail_account_id == account_id)

    if error_type:
        stmt = stmt.where(TrackedEmail.error_type == error_type)

    if q:
        pattern = f"%{sanitize_like(q)}%"
        stmt = stmt.where(
            or_(
                TrackedEmail.subject.ilike(pattern),
                TrackedEmail.sender.ilike(pattern),
            )
        )

    stmt = stmt.order_by(TrackedEmail.updated_at.desc())

    result = await paginate(db, stmt, page, per_page)
    return build_paginated_response(result, TrackedEmailResponse, TrackedEmailListResponse)


@router.post("/{email_id}/retry")
async def retry_email(
    email_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> TrackedEmailResponse:
    """Reset a failed tracked email to queued status for reprocessing.

    Only emails in FAILED status can be retried. The retry_count is
    incremented so the worker can track repeated failures.
    """
    stmt = select(TrackedEmail).where(
        TrackedEmail.id == email_id,
        TrackedEmail.user_id == user_id,
    )
    result = await db.execute(stmt)
    email = result.scalar_one_or_none()

    if email is None:
        raise HTTPException(status_code=404, detail="Tracked email not found")

    if email.status != TrackedEmailStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail=f"Only failed emails can be retried (current status: {email.status.value})",
        )

    email.status = TrackedEmailStatus.QUEUED
    email.retry_count += 1
    email.last_error = None
    email.error_type = None
    await db.flush()

    logger.info(
        "tracked_email_retry_queued",
        email_id=str(email_id),
        user_id=str(user_id),
        retry_count=email.retry_count,
    )

    return TrackedEmailResponse.model_validate(email)
