"""Approval system API endpoints.

Provides the approval queue for AI actions that require user confirmation.
Supports listing pending approvals, approving/rejecting individual items,
and bulk operations.

On approval: enqueues an ARQ task to execute the stored IMAP actions.
On spam rejection: enqueues an ARQ task to re-process the email through
the remaining AI plugins (skipping spam detection).
"""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserId, DbSession, get_or_404, paginate, sanitize_like
from app.core.redis import get_arq_client
from app.models import Approval, ApprovalStatus
from app.schemas.approval import (
    ApprovalEditRequest,
    ApprovalListResponse,
    ApprovalResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("")
async def list_approvals(
    db: DbSession,
    user_id: CurrentUserId,
    status: ApprovalStatus | None = Query(default=None, description="Filter by status"),
    function_type: str | None = Query(default=None, description="Filter by plugin type"),
    search: str | None = Query(default=None, max_length=200, description="Search by subject or sender"),
    sort: Literal["newest", "oldest"] = Query(default="newest", description="Sort order"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> ApprovalListResponse:
    """List approval queue entries for the current user."""
    uid = UUID(user_id)
    base_stmt = select(Approval).where(Approval.user_id == uid)

    if status:
        base_stmt = base_stmt.where(Approval.status == status)

    if function_type:
        base_stmt = base_stmt.where(Approval.function_type == function_type)

    if search:
        pattern = f"%{sanitize_like(search)}%"
        base_stmt = base_stmt.where(
            or_(
                Approval.mail_subject.ilike(pattern),
                Approval.mail_from.ilike(pattern),
            )
        )

    order_col = Approval.created_at.asc() if sort == "oldest" else Approval.created_at.desc()
    base_stmt = base_stmt.order_by(order_col)

    result = await paginate(db, base_stmt, page, per_page)

    return ApprovalListResponse(
        items=[ApprovalResponse.model_validate(a) for a in result.items],
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
    )


@router.post("/{approval_id}/approve")
async def approve_action(
    approval_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ApprovalResponse:
    """Approve a pending AI action for execution."""
    approval = await _get_pending_or_404(db, approval_id, user_id)

    approval.status = ApprovalStatus.APPROVED
    approval.resolved_at = datetime.now(UTC)
    await db.flush()

    logger.info(
        "approval_approved",
        approval_id=str(approval_id),
        function_type=approval.function_type,
        user_id=user_id,
    )

    # Enqueue action execution via ARQ worker
    await _enqueue_execution(str(approval.id))

    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/reject")
async def reject_action(
    approval_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ApprovalResponse:
    """Reject a pending AI action.

    For spam rejections the email is re-queued through the AI pipeline
    so that remaining plugins (labeling, smart_folder, etc.) still run.
    """
    approval = await _get_pending_or_404(db, approval_id, user_id)

    approval.status = ApprovalStatus.REJECTED
    approval.resolved_at = datetime.now(UTC)
    await db.flush()

    logger.info(
        "approval_rejected",
        approval_id=str(approval_id),
        function_type=approval.function_type,
        user_id=user_id,
    )

    # Spam rejection: re-process through the rest of the pipeline
    if approval.function_type == "spam_detection":
        await _enqueue_spam_reprocess(
            user_id,
            str(approval.mail_account_id),
            approval.mail_uid,
        )

    return ApprovalResponse.model_validate(approval)


@router.patch("/{approval_id}")
async def edit_approval(
    approval_id: UUID,
    data: ApprovalEditRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ApprovalResponse:
    """Edit the proposed actions on a pending or manual_input approval.

    Allows the user to override the AI-proposed actions before approving.
    The edited_actions will be used instead of proposed_action when the
    approval is executed.
    """
    approval = await _get_pending_or_404(db, approval_id, user_id)

    approval.edited_actions = data.edited_actions
    await db.flush()

    logger.info(
        "approval_edited",
        approval_id=str(approval_id),
        function_type=approval.function_type,
        user_id=user_id,
    )

    return ApprovalResponse.model_validate(approval)


@router.delete("/{approval_id}", status_code=204)
async def delete_approval(
    approval_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a resolved or expired approval entry.

    Only non-pending approvals can be deleted to prevent accidental
    removal of items that still need user action.
    """
    approval = await get_or_404(db, Approval, approval_id, user_id, detail="Approval not found")

    actionable = {ApprovalStatus.PENDING, ApprovalStatus.MANUAL_INPUT}
    if approval.status in actionable:
        raise HTTPException(status_code=409, detail="Cannot delete an actionable approval. Approve or reject it first.")

    await db.delete(approval)
    await db.flush()
    logger.info("approval_deleted", approval_id=str(approval_id), user_id=user_id)


async def _get_pending_or_404(db: AsyncSession, approval_id: UUID, user_id: str) -> Approval:
    """Fetch a pending/manual_input approval owned by the current user or raise 404.

    Accepts approvals in PENDING or MANUAL_INPUT status — both represent
    items that still require user action.
    """
    approval = await get_or_404(db, Approval, approval_id, user_id, detail="Approval not found")

    actionable = {ApprovalStatus.PENDING, ApprovalStatus.MANUAL_INPUT}
    if approval.status not in actionable:
        raise HTTPException(status_code=409, detail=f"Approval already {approval.status.value}")

    # Check expiry
    now = datetime.now(UTC)
    if approval.expires_at is not None and approval.expires_at < now:
        approval.status = ApprovalStatus.EXPIRED
        approval.resolved_at = now
        await db.flush()
        raise HTTPException(status_code=410, detail="Approval has expired")

    return approval


async def _enqueue_execution(approval_id: str) -> None:
    """Enqueue an ARQ task to execute approved IMAP actions."""
    arq = get_arq_client()
    await arq.enqueue_job(
        "execute_approved_actions",
        approval_id,
        _job_id=f"execute_approval:{approval_id}",
    )
    logger.info("approval_execution_enqueued", approval_id=approval_id)


async def _enqueue_spam_reprocess(user_id: str, account_id: str, mail_uid: str) -> None:
    """Enqueue an ARQ task to re-process an email after spam rejection."""
    arq = get_arq_client()
    await arq.enqueue_job(
        "handle_spam_rejection",
        user_id,
        account_id,
        mail_uid,
        _job_id=f"spam_reprocess:{account_id}:{mail_uid}",
    )
    logger.info(
        "spam_reprocess_enqueued",
        user_id=user_id,
        account_id=account_id,
        mail_uid=mail_uid,
    )
