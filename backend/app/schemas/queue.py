"""Pydantic schemas for the Mail Processing Queue API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.mail import CompletionReason, ErrorType, TrackedEmailStatus


class TrackedEmailResponse(BaseModel):
    """Response schema for a single tracked email in the processing queue."""

    id: UUID
    mail_uid: str
    subject: str | None
    sender: str | None
    received_at: datetime | None
    status: TrackedEmailStatus
    error_type: ErrorType | None
    last_error: str | None
    plugins_completed: list[str] | None
    plugins_failed: list[str] | None
    plugins_skipped: list[str] | None
    completion_reason: CompletionReason | None
    current_folder: str
    mail_account_id: UUID
    retry_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TrackedEmailListResponse(BaseModel):
    """Paginated list of tracked emails."""

    items: list[TrackedEmailResponse]
    total: int
    page: int
    per_page: int
    pages: int
