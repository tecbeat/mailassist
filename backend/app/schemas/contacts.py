"""Pydantic schemas for Contacts API requests and responses."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# --- CardDAV Config ---


class CardDAVConfigCreate(BaseModel):
    """Request schema for creating/updating CardDAV configuration."""

    carddav_url: str = Field(max_length=500, description="CardDAV server URL (HTTPS only)")
    username: str = Field(max_length=255)
    password: str = Field(max_length=500, description="CardDAV password (write-only)")
    address_book: str = Field(max_length=255, description="Address book name/path")
    sync_interval: int = Field(default=15, ge=5, le=1440, description="Sync interval in minutes")

    @field_validator("carddav_url")
    @classmethod
    def validate_https(cls, v: str) -> str:
        if not v.strip().startswith("https://"):
            raise ValueError("CardDAV URL must use HTTPS")
        return v.strip()


class CardDAVConfigUpdate(BaseModel):
    """Request schema for partially updating CardDAV configuration."""

    carddav_url: str | None = Field(default=None, max_length=500)
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=500)
    address_book: str | None = Field(default=None, max_length=255)
    sync_interval: int | None = Field(default=None, ge=5, le=1440)
    is_active: bool | None = None

    @field_validator("carddav_url")
    @classmethod
    def validate_https(cls, v: str | None) -> str | None:
        if v is not None and not v.strip().startswith("https://"):
            raise ValueError("CardDAV URL must use HTTPS")
        return v.strip() if v else v


class CardDAVConfigResponse(BaseModel):
    """Response schema for CardDAV configuration (credentials never returned)."""

    id: UUID
    carddav_url: str
    address_book: str
    sync_interval: int
    last_sync_at: datetime | None
    is_active: bool

    model_config = {"from_attributes": True}


class CardDAVTestRequest(BaseModel):
    """Request schema for testing a CardDAV connection."""

    carddav_url: str = Field(max_length=500)
    username: str = Field(max_length=255)
    password: str = Field(max_length=500)
    address_book: str = Field(default="", max_length=255, description="Address book name/path to validate (optional)")

    @field_validator("carddav_url")
    @classmethod
    def validate_https(cls, v: str) -> str:
        if not v.strip().startswith("https://"):
            raise ValueError("CardDAV URL must use HTTPS")
        return v.strip()


class CardDAVTestResult(BaseModel):
    """Result of testing a CardDAV connection."""

    success: bool
    message: str
    details: dict[str, Any] | None = Field(default=None, description="Additional info like discovered address books")


# --- Contact ---


class ContactResponse(BaseModel):
    """Response schema for a cached contact."""

    id: UUID
    display_name: str
    first_name: str | None
    last_name: str | None
    emails: list[str]
    phones: list[str] | None
    organization: str | None
    title: str | None
    photo_url: str | None
    synced_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class ContactListResponse(BaseModel):
    """Paginated contact list response."""

    items: list[ContactResponse]
    total: int
    page: int
    per_page: int
    pages: int


class UnmatchedSenderResponse(BaseModel):
    """A unique sender address not yet matched to a contact."""

    email_address: str
    mail_count: int = Field(description="Number of mails from this sender")


class SenderResponse(BaseModel):
    """A unique sender address from all emails in the database."""

    email_address: str
    mail_count: int = Field(description="Number of mails from this sender")
    matched_contact_id: UUID | None = Field(
        default=None, description="Contact ID if this sender is assigned to a contact"
    )


class AssignEmailRequest(BaseModel):
    """Request schema for assigning an email address to a contact."""

    email_address: str = Field(max_length=320, description="Email address to assign")


class AssignEmailResponse(BaseModel):
    """Response after assigning an email to a contact."""

    contact_id: UUID
    email_address: str
    writeback_triggered: bool = Field(description="Whether CardDAV write-back was triggered")


class RemoveEmailRequest(BaseModel):
    """Request schema for removing an email address from a contact."""

    email_address: str = Field(max_length=320, description="Email address to remove")


class RemoveEmailResponse(BaseModel):
    """Response after removing an email from a contact."""

    contact_id: UUID
    email_address: str
    writeback_triggered: bool = Field(description="Whether CardDAV write-back was triggered")


class SyncResult(BaseModel):
    """Result of a contact sync operation."""

    added: int
    updated: int
    deleted: int
    errors: int


class ContactAssignmentResponse(BaseModel):
    """Response schema for a contact assignment record."""

    id: UUID
    mail_account_id: UUID
    mail_uid: str
    mail_subject: str | None = None
    mail_from: str | None = None
    contact_id: UUID | None = None
    contact_name: str
    confidence: float
    reasoning: str | None = None
    is_new_contact_suggestion: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ContactMailsResponse(BaseModel):
    """Paginated response for listing mails associated with a contact."""

    items: list[ContactAssignmentResponse]
    total: int
    page: int
    per_page: int
    pages: int


# --- Contact Extraction (AI) ---


class ContactExtractRequest(BaseModel):
    """Request to extract contact info from emails by a sender."""

    sender_email: str = Field(max_length=320, description="Sender email address to extract contact info from")


class ContactExtractedData(BaseModel):
    """AI-extracted contact data from emails."""

    display_name: str = Field(max_length=255)
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    emails: list[str] = Field(default_factory=list)
    phones: list[str] | None = Field(default=None)
    organization: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)


class ContactCreateRequest(BaseModel):
    """Request to manually create a local contact."""

    display_name: str = Field(min_length=1, max_length=255)
    first_name: str | None = Field(default=None, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    emails: list[str] = Field(default_factory=list)
    phones: list[str] | None = Field(default=None)
    organization: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
