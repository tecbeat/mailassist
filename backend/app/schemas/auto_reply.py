"""Pydantic schemas for auto-reply record API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AutoReplyRecordResponse(BaseModel):
    """Response schema for an auto-reply record."""

    id: UUID
    mail_account_id: UUID
    mail_uid: str
    mail_subject: str | None = None
    mail_from: str | None = None
    draft_body: str
    tone: str | None = None
    reasoning: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AutoReplyRecordListResponse(BaseModel):
    """Paginated list of auto-reply records."""

    items: list[AutoReplyRecordResponse]
    total: int
    page: int
    per_page: int
    pages: int


class AutoReplyRecordUpdate(BaseModel):
    """Update schema for editing an auto-reply draft."""

    draft_body: str | None = Field(default=None, min_length=1, max_length=5000)
    tone: str | None = Field(default=None, max_length=50)
