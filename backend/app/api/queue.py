"""Mail Processing Queue API endpoints.

Provides a paginated view of all tracked emails with their processing
status, error details, and the ability to retry failed mails.
"""

import contextlib
import json
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import or_, select

from app.api.deps import CurrentUserId, DbSession, build_paginated_response, paginate, sanitize_like
from app.models.mail import ErrorType, TrackedEmail, TrackedEmailStatus
from app.schemas.queue import PipelineProgress, TrackedEmailListResponse, TrackedEmailResponse

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
    response = build_paginated_response(result, TrackedEmailResponse, TrackedEmailListResponse)
    await _enrich_pipeline_progress(response.items)
    return response


@router.post("/{email_id}/retry")
async def retry_email(
    email_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> TrackedEmailResponse:
    """Reset a tracked email and immediately start reprocessing.

    Works for any email that is not currently being processed.  Clears
    previous plugin results and error state, transitions the mail to
    PROCESSING, and enqueues the ARQ job so the pipeline starts right
    away instead of waiting for the next scheduler cycle.
    """
    stmt = select(TrackedEmail).where(
        TrackedEmail.id == email_id,
        TrackedEmail.user_id == user_id,
    )
    result = await db.execute(stmt)
    email = result.scalar_one_or_none()

    if email is None:
        raise HTTPException(status_code=404, detail="Tracked email not found")

    if email.status == TrackedEmailStatus.PROCESSING:
        raise HTTPException(
            status_code=409,
            detail="Cannot retry an email that is currently being processed",
        )

    # Reset state
    email.retry_count += 1
    email.last_error = None
    email.error_type = None
    email.plugins_completed = None
    email.plugins_failed = None
    email.plugins_skipped = None
    email.plugin_results = None
    email.completion_reason = None

    # Try to enqueue ARQ job immediately (transition to PROCESSING)
    enqueued = False
    try:
        from app.core.redis import get_arq_client

        arq = get_arq_client()
        job_id = f"process_mail:{email.mail_account_id}:{email.mail_uid}:{email.current_folder}"

        # Clear stale result key so enqueue succeeds
        result_key = f"arq:result:{job_id}"
        with contextlib.suppress(Exception):
            await arq.delete(result_key)

        job = await arq.enqueue_job(
            "process_mail",
            str(user_id),
            str(email.mail_account_id),
            email.mail_uid,
            email.current_folder,
            _job_id=job_id,
        )
        if job is not None:
            email.status = TrackedEmailStatus.PROCESSING
            enqueued = True
    except Exception:
        logger.warning("retry_enqueue_failed", email_id=str(email_id))

    if not enqueued:
        # Fallback: set to QUEUED so the scheduler picks it up
        email.status = TrackedEmailStatus.QUEUED

    await db.flush()

    logger.info(
        "tracked_email_retry",
        email_id=str(email_id),
        user_id=str(user_id),
        retry_count=email.retry_count,
        enqueued=enqueued,
    )

    return TrackedEmailResponse.model_validate(email)


@router.post("/{email_id}/cancel")
async def cancel_email(
    email_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> TrackedEmailResponse:
    """Request cancellation of a processing email.

    Sets a Valkey cancel flag that the pipeline checks between plugins.
    The pipeline will stop after the current plugin finishes and mark
    the email as completed with reason ``cancelled``.
    """
    stmt = select(TrackedEmail).where(
        TrackedEmail.id == email_id,
        TrackedEmail.user_id == user_id,
    )
    result = await db.execute(stmt)
    email = result.scalar_one_or_none()

    if email is None:
        raise HTTPException(status_code=404, detail="Tracked email not found")

    if email.status != TrackedEmailStatus.PROCESSING:
        raise HTTPException(
            status_code=409,
            detail="Can only cancel emails that are currently being processed",
        )

    try:
        from app.core.redis import get_task_client
        from app.workers.pipeline_orchestrator import _cancel_key

        client = get_task_client()
        # Set cancel flag with TTL (pipeline will pick it up between plugins)
        await client.set(
            _cancel_key(str(email.mail_account_id), email.mail_uid, email.current_folder),
            "1",
            ex=300,  # 5 min TTL as safety net
        )
    except Exception:
        logger.exception("cancel_flag_set_failed", email_id=str(email_id))
        raise HTTPException(status_code=500, detail="Failed to set cancellation flag") from None

    logger.info(
        "tracked_email_cancel_requested",
        email_id=str(email_id),
        user_id=str(user_id),
    )

    return TrackedEmailResponse.model_validate(email)


# ---------------------------------------------------------------------------
# Pipeline progress enrichment (Valkey)
# ---------------------------------------------------------------------------


async def _enrich_pipeline_progress(items: list[TrackedEmailResponse]) -> None:
    """Attach live pipeline progress from Valkey to processing emails."""
    processing = [item for item in items if item.status == TrackedEmailStatus.PROCESSING]
    if not processing:
        return

    try:
        from app.core.redis import get_task_client
        from app.workers.pipeline_orchestrator import _progress_key

        client = get_task_client()
        for item in processing:
            key = _progress_key(str(item.mail_account_id), item.mail_uid, item.current_folder)
            raw = await client.get(key)
            if not raw:
                continue
            try:
                data = json.loads(raw)
                item.pipeline_progress = PipelineProgress(**data)
            except (ValueError, TypeError):
                continue
    except Exception:
        # Progress enrichment is best-effort
        pass
