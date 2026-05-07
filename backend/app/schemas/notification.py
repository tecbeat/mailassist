"""Pydantic schemas for notification system API requests and responses."""

import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field


def mask_apprise_url(url: str) -> str:
    """Mask sensitive parts of an Apprise URL for safe display.

    Preserves the scheme and host but replaces credentials, tokens,
    and path segments with '***'.
    """
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme or "unknown"
        host = parsed.hostname or "***"
        # Mask user/password
        masked_user = "***" if parsed.username else ""
        masked_pass = ":***" if parsed.password else ""
        userinfo = f"{masked_user}{masked_pass}@" if parsed.username else ""
        port = f":{parsed.port}" if parsed.port else ""
        # Mask path segments (tokens, IDs, etc.)
        path = parsed.path
        if path and path != "/":
            segments = path.strip("/").split("/")
            masked_segments = ["***" for _ in segments]
            path = "/" + "/".join(masked_segments)
        return f"{scheme}://{userinfo}{host}{port}{path}"
    except Exception:
        # If parsing fails, just mask the whole thing
        return re.sub(r"://.*", "://***", url) if "://" in url else "***"


# ---------------------------------------------------------------------------
# Notification Channel schemas
# ---------------------------------------------------------------------------


class NotificationChannelCreate(BaseModel):
    """Request to create a new notification channel."""

    url: str = Field(min_length=1, max_length=1000)
    mail_account_ids: list[UUID] | None = Field(default=None)
    event_types: list[str] | None = Field(default=None)


class NotificationChannelUpdate(BaseModel):
    """Request to update a notification channel's routing config."""

    mail_account_ids: list[UUID] | None = Field(default=None)
    event_types: list[str] | None = Field(default=None)


class NotificationChannelResponse(BaseModel):
    """Response schema for a single notification channel."""

    id: UUID
    url: str  # masked
    mail_account_ids: list[UUID] | None
    event_types: list[str] | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Notification Config schemas (templates only now)
# ---------------------------------------------------------------------------


class NotificationConfigResponse(BaseModel):
    """Response schema for notification configuration (templates)."""

    id: UUID
    templates: dict[str, Any]
    updated_at: datetime

    model_config = {"from_attributes": True}


class NotificationConfigUpdate(BaseModel):
    """Update schema for notification templates."""

    templates: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Test / Preview / Variables
# ---------------------------------------------------------------------------


class NotificationTestRequest(BaseModel):
    """Request to send a test notification."""

    message: str = Field(default="Test notification from mailassist", max_length=500)


class NotificationTestResponse(BaseModel):
    """Result of a test notification."""

    success: bool
    message: str


class NotificationPreviewRequest(BaseModel):
    """Request to preview a rendered notification template."""

    template: str = Field(max_length=10000)
    event_type: str = Field(max_length=100)


class NotificationPreviewResponse(BaseModel):
    """Rendered notification template preview."""

    rendered: str
    errors: list[str] = Field(default_factory=list)


class DefaultTemplateResponse(BaseModel):
    """Default on-disk Jinja2 notification template content."""

    event_type: str
    template: str


class NotificationEventInfo(BaseModel):
    """Metadata about a notification event type (derived from plugin registry)."""

    event_type: str
    plugin_name: str
    display_name: str
    execution_order: int
