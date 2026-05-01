"""Pydantic schemas for email summary API requests and responses."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EmailSummaryResponse(BaseModel):
    """Response schema for an email summary."""

    id: UUID
    mail_account_id: UUID
    mail_uid: str
    mail_subject: str | None = None
    mail_from: str | None = None
    mail_date: datetime | None = None
    summary: str
    key_points: list[str]
    urgency: str
    action_required: bool
    action_description: str | None
    notified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class EmailSummaryListResponse(BaseModel):
    """Paginated list of email summaries."""

    items: list[EmailSummaryResponse]
    total: int
    page: int
    per_page: int
    pages: int


class MissingSummaryItem(BaseModel):
    """A completed email that is missing an AI-generated summary."""

    id: UUID
    mail_account_id: UUID
    mail_uid: str
    subject: str | None = None
    sender: str | None = None
    completion_reason: str | None = None
    plugins_failed: list[str] | None = None
    plugins_skipped: list[str] | None = None
    current_folder: str = "INBOX"
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MissingSummaryListResponse(BaseModel):
    """Paginated list of completed mails that lack an email summary."""

    items: list[MissingSummaryItem]
    total: int
    page: int
    per_page: int
    pages: int


class SummaryFilterRules(BaseModel):
    """Filter rules for summary notification forwarding."""

    labels: list[str] | None = None
    folders: list[str] | None = None
    from_contacts_only: bool = False
    min_urgency: str = Field(default="low", pattern="^(low|medium|high|critical)$")
    action_required_only: bool = False
    exclude_spam: bool = True


class SummaryFilterConfigResponse(BaseModel):
    """Response schema for summary filter configuration."""

    id: UUID
    is_enabled: bool
    filter_rules: dict[str, Any]
    updated_at: datetime

    model_config = {"from_attributes": True}


class SummaryFilterConfigUpdate(BaseModel):
    """Update schema for summary filter configuration."""

    is_enabled: bool = False
    filter_rules: SummaryFilterRules = Field(default_factory=SummaryFilterRules)
