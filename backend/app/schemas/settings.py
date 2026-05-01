"""Pydantic schemas for user settings API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.user import ApprovalMode


class ApprovalModes(BaseModel):
    """Per-function approval mode configuration (used in responses)."""

    spam: ApprovalMode = ApprovalMode.APPROVAL
    labeling: ApprovalMode = ApprovalMode.APPROVAL
    smart_folder: ApprovalMode = ApprovalMode.APPROVAL
    newsletter: ApprovalMode = ApprovalMode.APPROVAL
    auto_reply: ApprovalMode = ApprovalMode.APPROVAL
    coupon: ApprovalMode = ApprovalMode.APPROVAL
    calendar: ApprovalMode = ApprovalMode.APPROVAL
    summary: ApprovalMode = ApprovalMode.APPROVAL
    rules: ApprovalMode = ApprovalMode.APPROVAL
    contacts: ApprovalMode = ApprovalMode.APPROVAL
    notifications: ApprovalMode = ApprovalMode.APPROVAL


class ApprovalModesUpdate(BaseModel):
    """Per-function approval mode update (all fields optional for true partial updates)."""

    spam: ApprovalMode | None = None
    labeling: ApprovalMode | None = None
    smart_folder: ApprovalMode | None = None
    newsletter: ApprovalMode | None = None
    auto_reply: ApprovalMode | None = None
    coupon: ApprovalMode | None = None
    calendar: ApprovalMode | None = None
    summary: ApprovalMode | None = None
    rules: ApprovalMode | None = None
    contacts: ApprovalMode | None = None
    notifications: ApprovalMode | None = None


class SettingsResponse(BaseModel):
    """Response schema for user settings."""

    id: UUID
    timezone: str
    language: str
    default_polling_interval_minutes: int
    draft_expiry_hours: int
    max_concurrent_processing: int
    ai_timeout_seconds: int
    approval_modes: ApprovalModes
    plugin_order: list[str] | None = None
    plugin_provider_map: dict[str, str] | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class SettingsUpdate(BaseModel):
    """Update schema for user settings (partial update)."""

    timezone: str | None = Field(None, min_length=1, max_length=50, examples=["Europe/Berlin"])
    language: str | None = Field(None, min_length=2, max_length=10, examples=["de"])
    default_polling_interval_minutes: int | None = Field(None, ge=1, le=60)
    draft_expiry_hours: int | None = Field(None, ge=1, le=720)
    max_concurrent_processing: int | None = Field(
        None,
        ge=1,
        le=20,
        description="Max mails in PROCESSING status simultaneously (1-20)",
    )
    ai_timeout_seconds: int | None = Field(
        None,
        ge=10,
        le=600,
        description="Global LLM timeout in seconds (10-600). Per-provider overrides take precedence.",
    )
    approval_modes: ApprovalModesUpdate | None = None
    plugin_order: list[str] | None = None
    plugin_provider_map: dict[str, str] | None = None
