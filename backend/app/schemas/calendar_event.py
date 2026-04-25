"""Pydantic schemas for calendar event API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CalendarEventResponse(BaseModel):
    """Response schema for a calendar event record."""

    id: UUID
    mail_account_id: UUID
    mail_uid: str
    mail_subject: str | None = None
    mail_from: str | None = None
    title: str
    start: datetime | None = None
    end: datetime | None = None
    location: str | None = None
    description: str | None = None
    is_all_day: bool
    caldav_synced: bool
    caldav_error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CalendarEventListResponse(BaseModel):
    """Paginated list of calendar events."""

    items: list[CalendarEventResponse]
    total: int
    page: int
    per_page: int
    pages: int


class CalendarEventUpdate(BaseModel):
    """Update schema for editing a calendar event."""

    title: str | None = Field(default=None, min_length=1, max_length=300)
    start: datetime | None = None
    end: datetime | None = None
    location: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    is_all_day: bool | None = None
