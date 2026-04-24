"""Coupon API endpoints.

Provides listing, detail, update, and delete views for AI-extracted coupons.
"""

from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentUserId, DbSession, get_or_404, paginate, sanitize_like
from app.models import ExtractedCoupon
from app.schemas.coupon import (
    CouponUpdate,
    ExtractedCouponListResponse,
    ExtractedCouponResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/coupons", tags=["coupons"])


@router.get("")
async def list_coupons(
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    store: str | None = None,
    active_only: bool = False,
    sort: Literal["newest", "oldest", "store", "expiry"] = Query(default="newest", description="Sort order"),
) -> ExtractedCouponListResponse:
    """List extracted coupons with pagination and optional filters."""
    uid = UUID(user_id)

    base_stmt = select(ExtractedCoupon).where(ExtractedCoupon.user_id == uid)

    if store:
        base_stmt = base_stmt.where(ExtractedCoupon.store.ilike(f"%{sanitize_like(store)}%"))
    if active_only:
        base_stmt = base_stmt.where(ExtractedCoupon.is_used.is_(False))

    if sort == "oldest":
        order_col = ExtractedCoupon.created_at.asc()
    elif sort == "store":
        order_col = ExtractedCoupon.store.asc()
    elif sort == "expiry":
        order_col = ExtractedCoupon.expires_at.asc().nullslast()
    else:
        order_col = ExtractedCoupon.created_at.desc()

    base_stmt = base_stmt.order_by(order_col)
    result = await paginate(db, base_stmt, page, per_page)

    return ExtractedCouponListResponse(
        items=[ExtractedCouponResponse.model_validate(c) for c in result.items],
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
    )


@router.get("/{coupon_id}")
async def get_coupon(
    coupon_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ExtractedCouponResponse:
    """Get a single extracted coupon with full details."""
    coupon = await get_or_404(db, ExtractedCoupon, coupon_id, user_id, "Coupon not found")
    return ExtractedCouponResponse.model_validate(coupon)


@router.patch("/{coupon_id}")
async def update_coupon(
    coupon_id: UUID,
    data: CouponUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> ExtractedCouponResponse:
    """Update a coupon (e.g. mark as used)."""
    coupon = await get_or_404(db, ExtractedCoupon, coupon_id, user_id, "Coupon not found")

    coupon.is_used = data.is_used
    await db.flush()
    logger.info("coupon_updated", coupon_id=str(coupon_id), is_used=data.is_used)
    return ExtractedCouponResponse.model_validate(coupon)


@router.delete("/{coupon_id}", status_code=204)
async def delete_coupon(
    coupon_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete an extracted coupon record."""
    coupon = await get_or_404(db, ExtractedCoupon, coupon_id, user_id, "Coupon not found")

    await db.delete(coupon)
    await db.flush()
    logger.info("coupon_deleted", coupon_id=str(coupon_id))
