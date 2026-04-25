"""Pydantic schemas for CalDAV calendar API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CalDAVConfigResponse(BaseModel):
    """Response schema for CalDAV configuration (credentials hidden)."""

    id: UUID
    caldav_url: str
    default_calendar: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CalDAVConfigUpdate(BaseModel):
    """Create or update CalDAV configuration."""

    caldav_url: str = Field(max_length=500)
    username: str = Field(max_length=200)
    password: str = Field(max_length=500)
    default_calendar: str = Field(max_length=255)

    @field_validator("caldav_url")
    @classmethod
    def validate_https(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("CalDAV URL must use HTTPS")
        return v


class CalDAVTestRequest(BaseModel):
    """Request to test CalDAV connectivity.

    Accepts credentials directly so the connection can be tested
    before saving configuration. All fields are optional — when
    omitted the stored config is used instead.
    """

    caldav_url: str | None = Field(default=None, max_length=500)
    username: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=500)
    default_calendar: str = Field(default="", max_length=255, description="Calendar to validate (optional)")

    @field_validator("caldav_url")
    @classmethod
    def validate_https(cls, v: str | None) -> str | None:
        if v is not None and not v.strip().startswith("https://"):
            raise ValueError("CalDAV URL must use HTTPS")
        return v.strip() if v else v


class CalDAVTestResponse(BaseModel):
    """Result of a CalDAV connectivity test."""

    success: bool
    message: str
    calendars: list[str] = Field(default_factory=list)
    details: dict | None = Field(default=None, description="Additional info like discovered URLs")
