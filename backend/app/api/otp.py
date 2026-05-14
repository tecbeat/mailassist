"""OTP code API endpoints.

Provides listing, detail, and delete views for AI-extracted OTP codes.
"""

from typing import Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.deps import (
    CurrentUserId,
    DbSession,
    build_paginated_response,
    get_or_404,
    paginate,
    resolve_sort_order,
    sanitize_like,
)
from app.models import ExtractedOtpCode
from app.schemas.otp import (
    ExtractedOtpCodeListResponse,
    ExtractedOtpCodeResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/otp-codes", tags=["otp"])


@router.get("")
async def list_otp_codes(
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    service: str | None = None,
    code_type: str | None = None,
    active_only: bool = False,
    sort: Literal["newest", "oldest", "service", "expiry"] = Query(default="newest", description="Sort order"),
) -> ExtractedOtpCodeListResponse:
    """List extracted OTP codes with pagination and optional filters."""
    uid = user_id

    base_stmt = select(ExtractedOtpCode).options(joinedload(ExtractedOtpCode.tracked_email)).where(ExtractedOtpCode.user_id == uid)

    if service:
        base_stmt = base_stmt.where(ExtractedOtpCode.service.ilike(f"%{sanitize_like(service)}%"))
    if code_type:
        base_stmt = base_stmt.where(ExtractedOtpCode.code_type == code_type)
    if active_only:
        base_stmt = base_stmt.where(ExtractedOtpCode.is_expired.is_(False))

    order_col = resolve_sort_order(
        sort,
        {
            "newest": ExtractedOtpCode.created_at.desc(),
            "oldest": ExtractedOtpCode.created_at.asc(),
            "service": ExtractedOtpCode.service.asc(),
            "expiry": ExtractedOtpCode.expires_at.asc().nullslast(),
        },
    )

    base_stmt = base_stmt.order_by(order_col)
    result = await paginate(db, base_stmt, page, per_page)

    return build_paginated_response(result, ExtractedOtpCodeResponse, ExtractedOtpCodeListResponse)


@router.get("/{otp_id}")
async def get_otp_code(
    otp_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ExtractedOtpCodeResponse:
    """Get a single extracted OTP code with full details."""
    otp = await get_or_404(
        db, ExtractedOtpCode, otp_id, user_id, "OTP code not found",
        options=[joinedload(ExtractedOtpCode.tracked_email)],
    )
    return ExtractedOtpCodeResponse.model_validate(otp)


@router.delete("/{otp_id}", status_code=204)
async def delete_otp_code(
    otp_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete an extracted OTP code record."""
    otp = await get_or_404(db, ExtractedOtpCode, otp_id, user_id, "OTP code not found")

    await db.delete(otp)
    await db.flush()
    logger.info("otp_code_deleted", otp_id=str(otp_id))
