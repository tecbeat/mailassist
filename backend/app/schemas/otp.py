"""Pydantic schemas for OTP code API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.plugin_base import PluginResponseBase


class ExtractedOtpCodeResponse(PluginResponseBase):
    """Response schema for an extracted OTP code."""

    id: UUID
    code: str
    description: str | None = None
    service: str | None = None
    code_type: str
    url: str | None = None
    expires_at: datetime | None = None
    is_expired: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExtractedOtpCodeListResponse(BaseModel):
    """Paginated list of extracted OTP codes."""

    items: list[ExtractedOtpCodeResponse]
    total: int
    page: int
    per_page: int
    pages: int
