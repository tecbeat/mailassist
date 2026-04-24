"""Pydantic schemas for assigned folder API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AssignedFolderResponse(BaseModel):
    """Response schema for an assigned folder record."""

    id: UUID
    mail_account_id: UUID
    mail_uid: str
    mail_subject: str | None = None
    mail_from: str | None = None
    folder: str
    confidence: float | None = None
    reason: str | None = None
    is_new_folder: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AssignedFolderListResponse(BaseModel):
    """Paginated list of assigned folders."""

    items: list[AssignedFolderResponse]
    total: int
    page: int
    per_page: int
    pages: int


class FolderSummary(BaseModel):
    """Summary of a unique folder with usage count."""

    folder: str
    count: int


class FolderSummaryListResponse(BaseModel):
    """List of unique folders with counts."""

    items: list[FolderSummary]
    total: int


class SmartFolderResetAccountResult(BaseModel):
    """Per-account result of a smart folder reset operation."""

    account_id: str
    account_name: str
    moved_to_inbox: int | None = None
    imap_folder_deleted: bool | None = None
    error: str | None = None


class SmartFolderResetResponse(BaseModel):
    """Summary of a full smart folder reset operation."""

    folder: str
    accounts: list[SmartFolderResetAccountResult]
    deleted_assigned_folders: int
    deleted_folder_change_logs: int
    reset_tracked_emails: int


class SmartFolderReprocessResponse(BaseModel):
    """Summary of a reprocess-in-place operation."""

    folder: str
    requeued_emails: int
