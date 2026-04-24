"""Pydantic schemas for Mail Account API requests and responses."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class MailAccountCreate(BaseModel):
    """Request schema for creating a mail account."""

    name: str = Field(max_length=100, description="Display name (e.g. 'Work', 'Private')")
    email_address: str = Field(max_length=320, description="Email address for this account")
    imap_host: str = Field(max_length=255)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_use_ssl: bool = True
    username: str = Field(max_length=255, description="IMAP username")
    password: str = Field(max_length=500, description="IMAP password (write-only)")
    polling_enabled: bool = True
    polling_interval_minutes: int = Field(default=5, ge=1, le=60)
    idle_enabled: bool = True
    scan_existing_emails: bool = Field(
        default=False,
        description="If true, index existing emails from all folders on first sync. Otherwise only new incoming mail is processed.",
    )
    excluded_folders: list[str] | None = Field(default=None, description="IMAP folders to skip during analysis")

    @field_validator("imap_host")
    @classmethod
    def validate_host(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Host must not be empty")
        return v.strip()


class MailAccountUpdate(BaseModel):
    """Request schema for updating a mail account."""

    name: str | None = Field(default=None, max_length=100)
    email_address: str | None = Field(default=None, max_length=320)
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_use_ssl: bool | None = None
    username: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=500)
    polling_enabled: bool | None = None
    polling_interval_minutes: int | None = Field(default=None, ge=1, le=60)
    idle_enabled: bool | None = None
    scan_existing_emails: bool | None = None
    excluded_folders: list[str] | None = None


class MailAccountResponse(BaseModel):
    """Response schema for a mail account (credentials never returned)."""

    id: UUID
    name: str
    email_address: str
    imap_host: str
    imap_port: int
    imap_use_ssl: bool
    polling_enabled: bool
    polling_interval_minutes: int
    idle_enabled: bool
    initial_scan_done: bool
    scan_existing_emails: bool
    excluded_folders: list[str] | None
    last_sync_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    consecutive_errors: int
    is_paused: bool
    manually_paused: bool
    paused_reason: str | None
    paused_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MailAccountStatus(BaseModel):
    """Status response for a mail account."""

    id: UUID
    name: str
    is_paused: bool
    manually_paused: bool
    paused_reason: str | None
    paused_at: datetime | None
    last_sync_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    consecutive_errors: int

    model_config = {"from_attributes": True}


class ConnectionTestResult(BaseModel):
    """Result of testing IMAP connection."""

    imap_success: bool
    imap_message: str
    imap_capabilities: list[str] = Field(default_factory=list)
    idle_supported: bool = False
    email_count: int | None = Field(default=None, description="Total emails found in INBOX")


class FolderInfo(BaseModel):
    """A single IMAP folder with optional message counts."""

    name: str
    messages: int | None = None
    unseen: int | None = None


class ImapFolderListResponse(BaseModel):
    """IMAP folder listing with hierarchy separator and excluded folders."""

    folders: list[FolderInfo] | list[str]
    separator: str
    excluded_folders: list[str] = Field(default_factory=list)


class JobEnqueuedResponse(BaseModel):
    """Confirmation that a job was enqueued."""

    status: str
    job_id: str | None = None


class FolderDeletedResponse(BaseModel):
    """Confirmation of IMAP folder deletion."""

    status: str
    folder: str


class FolderRenameRequest(BaseModel):
    """Request body for renaming an IMAP folder."""

    old_name: str = Field(min_length=1, max_length=500)
    new_name: str = Field(min_length=1, max_length=500)


class FolderRenamedResponse(BaseModel):
    """Confirmation of IMAP folder rename."""

    status: str
    old_name: str
    new_name: str


class ExcludedFoldersRequest(BaseModel):
    """Request body for updating excluded folders."""

    excluded_folders: list[str] = Field(default_factory=list)


class ExcludedFoldersResponse(BaseModel):
    """Updated excluded folders list."""

    excluded_folders: list[str]


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    items: list
    total: int
    page: int
    per_page: int
    pages: int


class PauseUpdate(BaseModel):
    """Request schema for updating the pause state."""

    paused: bool = Field(description="Whether the account should be paused")
    pause_reason: str = Field(default="manual", max_length=200, description="Reason for pausing")
