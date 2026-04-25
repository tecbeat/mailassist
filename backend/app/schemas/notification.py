"""Pydantic schemas for notification system API requests and responses."""

import re
from datetime import datetime
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, Field


class NotifyOnConfig(BaseModel):
    """Toggles for which events trigger notifications."""

    reply_needed: bool = False
    spam_detected: bool = False
    coupon_found: bool = False
    calendar_event_created: bool = False
    rule_executed: bool = False
    newsletter_detected: bool = False
    email_summary: bool = False
    ai_error: bool = False
    contact_assigned: bool = False
    approval_needed: bool = False


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


class NotificationConfigResponse(BaseModel):
    """Response schema for notification configuration."""

    id: UUID
    apprise_urls: list[str]
    templates: dict
    notify_on: dict
    updated_at: datetime

    model_config = {"from_attributes": True}


class NotificationConfigUpdate(BaseModel):
    """Update schema for notification configuration."""

    apprise_urls: list[str] | None = Field(default=None, max_length=10)
    templates: dict = Field(default_factory=dict)
    notify_on: NotifyOnConfig = Field(default_factory=NotifyOnConfig)


class NotificationUrlAdd(BaseModel):
    """Request to add a new Apprise URL."""

    url: str = Field(min_length=1, max_length=1000)


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
