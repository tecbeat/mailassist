"""Pydantic schemas for applied label API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AppliedLabelResponse(BaseModel):
    """Response schema for an applied label record."""

    id: UUID
    mail_account_id: UUID
    mail_uid: str
    mail_subject: str | None = None
    mail_from: str | None = None
    label: str
    is_new_label: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AppliedLabelListResponse(BaseModel):
    """Paginated list of applied labels."""

    items: list[AppliedLabelResponse]
    total: int
    page: int
    per_page: int
    pages: int


class LabelSummary(BaseModel):
    """Summary of a unique label with usage count."""

    label: str
    count: int


class LabelSummaryListResponse(BaseModel):
    """List of unique labels with counts."""

    items: list[LabelSummary]
    total: int


class AppliedLabelCreate(BaseModel):
    """Create schema for manually adding a label."""

    label: str = Field(min_length=1, max_length=200)
