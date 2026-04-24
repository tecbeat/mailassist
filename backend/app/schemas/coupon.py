"""Pydantic schemas for coupon API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ExtractedCouponResponse(BaseModel):
    """Response schema for an extracted coupon."""

    id: UUID
    mail_account_id: UUID
    mail_uid: str
    sender_email: str | None = None
    mail_subject: str | None = None
    code: str | None = None
    description: str | None = None
    store: str | None = None
    expires_at: datetime | None = None
    valid_from: datetime | None = None
    is_used: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExtractedCouponListResponse(BaseModel):
    """Paginated list of extracted coupons."""

    items: list[ExtractedCouponResponse]
    total: int
    page: int
    per_page: int
    pages: int


class CouponUpdate(BaseModel):
    """Update schema for marking a coupon as used/unused."""

    is_used: bool
