"""Pydantic schemas for Spam Blocklist API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SpamReportRequest(BaseModel):
    """Request to report a mail as spam."""

    mail_id: str = Field(max_length=100, description="IMAP UID of the mail to report")
    mail_account_id: UUID = Field(description="Mail account the message belongs to")
    sender_email: str = Field(max_length=320, description="Sender email address")
    subject: str | None = Field(default=None, max_length=998, description="Email subject for pattern extraction")


class SpamReportContactRequest(BaseModel):
    """Request to report a contact as spam (block all their emails)."""

    contact_id: UUID = Field(description="Contact to block")


class BlocklistEntryCreate(BaseModel):
    """Request to manually add a blocklist entry."""

    entry_type: str = Field(description="Type: 'email', 'domain', or 'pattern'")
    value: str = Field(max_length=998, description="Email, domain, or subject pattern to block")

    @field_validator("entry_type")
    @classmethod
    def validate_entry_type(cls, v: str) -> str:
        if v not in ("email", "domain", "pattern"):
            raise ValueError("entry_type must be 'email', 'domain', or 'pattern'")
        return v

    @field_validator("value")
    @classmethod
    def validate_value_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("value must not be empty")
        return v


class BlocklistEntryResponse(BaseModel):
    """Response schema for a blocklist entry."""

    id: UUID
    entry_type: str
    value: str
    source: str
    source_mail_uid: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class BlocklistListResponse(BaseModel):
    """Paginated blocklist list response."""

    items: list[BlocklistEntryResponse]
    total: int
    page: int
    per_page: int
    pages: int


class SpamReportResult(BaseModel):
    """Result of reporting something as spam."""

    blocked_entries_created: int = Field(description="Number of new blocklist entries created")
    mail_moved: bool = Field(description="Whether the mail was moved to spam folder")
    message: str
