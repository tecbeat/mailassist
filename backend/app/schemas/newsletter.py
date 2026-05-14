"""Pydantic schemas for newsletter API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.plugin_base import PluginResponseBase


class DetectedNewsletterResponse(PluginResponseBase):
    """Response schema for a detected newsletter."""

    id: UUID
    newsletter_name: str
    sender_address: str
    unsubscribe_url: str | None = None
    has_unsubscribe: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class DetectedNewsletterListResponse(BaseModel):
    """Paginated list of detected newsletters."""

    items: list[DetectedNewsletterResponse]
    total: int
    page: int
    per_page: int
    pages: int
