"""Applied label API endpoints.

Provides listing, label summary, and delete views for labels
applied by the AI labeling plugin.
"""

from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import func, select

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import UnaryExpression

from app.api.deps import CurrentUserId, DbSession, get_or_404, paginate, sanitize_like
from app.models import AppliedLabel
from app.schemas.applied_label import (
    AppliedLabelListResponse,
    AppliedLabelResponse,
    LabelSummary,
    LabelSummaryListResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/labels", tags=["labels"])


@router.get("")
async def list_applied_labels(
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    label: str | None = None,
    sort: Literal["newest", "oldest", "label"] = Query(default="newest", description="Sort order"),
) -> AppliedLabelListResponse:
    """List applied labels with pagination and optional label filter."""
    uid = UUID(user_id)

    base_stmt = select(AppliedLabel).where(AppliedLabel.user_id == uid)

    if label:
        base_stmt = base_stmt.where(AppliedLabel.label.ilike(f"%{sanitize_like(label)}%"))

    order_col: UnaryExpression[Any]
    if sort == "oldest":
        order_col = AppliedLabel.created_at.asc()
    elif sort == "label":
        order_col = AppliedLabel.label.asc()
    else:
        order_col = AppliedLabel.created_at.desc()

    base_stmt = base_stmt.order_by(order_col)
    result = await paginate(db, base_stmt, page, per_page)

    return AppliedLabelListResponse(
        items=[AppliedLabelResponse.model_validate(r) for r in result.items],
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
    )


@router.get("/summary")
async def get_label_summary(
    db: DbSession,
    user_id: CurrentUserId,
) -> LabelSummaryListResponse:
    """Get a summary of unique labels with usage counts."""
    uid = UUID(user_id)

    stmt = (
        select(AppliedLabel.label, func.count().label("count"))
        .where(AppliedLabel.user_id == uid)
        .group_by(AppliedLabel.label)
        .order_by(func.count().desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    items = [LabelSummary(label=row.label, count=row.count) for row in rows]
    return LabelSummaryListResponse(items=items, total=len(items))


@router.delete("/{label_id}", status_code=204)
async def delete_applied_label(
    label_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete an applied label record."""
    record = await get_or_404(db, AppliedLabel, label_id, user_id, "Label record not found")
    await db.delete(record)
    await db.flush()
    logger.info("applied_label_deleted", label_id=str(label_id))
