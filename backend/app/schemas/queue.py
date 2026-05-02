"""Pydantic schemas for the Mail Processing Queue API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.models.mail import CompletionReason, ErrorType, TrackedEmailStatus


class PluginResultEntry(BaseModel):
    """Summary of a single plugin's execution result."""

    status: str  # "completed", "failed", "skipped", "warning"
    display_name: str
    summary: str | None = None
    details: dict[str, Any] | None = None


class PipelinePluginName(BaseModel):
    """Plugin name/display_name pair for progress tracking."""

    name: str
    display_name: str


class PipelineProgress(BaseModel):
    """Live pipeline progress for a processing email (from Valkey)."""

    phase: str | None = None
    current_plugin: str | None = None
    current_plugin_display: str | None = None
    plugin_index: int | None = None
    plugins_total: int | None = None
    plugin_names: list[PipelinePluginName] | None = None


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
    plugin_results: dict[str, PluginResultEntry] | None = None
    pipeline_progress: PipelineProgress | None = None
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
