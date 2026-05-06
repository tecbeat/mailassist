"""Notification configuration API endpoints.

Provides management for notification channels (Apprise URLs with per-channel
mail account and event type routing) and notification templates.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUserId, DbSession, get_or_create
from app.core.templating import get_template_engine
from app.models import NotificationChannel, NotificationConfig
from app.plugins.registry import get_plugin_registry
from app.schemas.notification import (
    DefaultTemplateResponse,
    NotificationChannelCreate,
    NotificationChannelResponse,
    NotificationChannelUpdate,
    NotificationConfigResponse,
    NotificationConfigUpdate,
    NotificationEventInfo,
    NotificationPreviewRequest,
    NotificationPreviewResponse,
    NotificationTestRequest,
    NotificationTestResponse,
    mask_apprise_url,
)
from app.schemas.prompt import TemplateVariable
from app.services.notifications import send_test_notification

logger = structlog.get_logger()

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_DEFAULT_TEMPLATE_FILE = "notifications/default.j2"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_event_registry() -> dict[str, Any]:
    """Build notification event metadata from the plugin registry."""
    registry = get_plugin_registry()
    events: dict[str, Any] = {}
    for plugin in registry.get_all_plugins():
        if plugin.notification_event_type:
            events[plugin.notification_event_type] = plugin
    return events


def _mask_channel(channel: NotificationChannel) -> NotificationChannelResponse:
    """Convert a channel ORM object to response with masked URL."""
    resp = NotificationChannelResponse.model_validate(channel)
    resp.url = mask_apprise_url(channel.url)
    return resp


# ---------------------------------------------------------------------------
# Channel CRUD
# ---------------------------------------------------------------------------


@router.get("/channels")
async def list_channels(
    db: DbSession,
    user_id: CurrentUserId,
) -> list[NotificationChannelResponse]:
    """List all notification channels for the current user."""
    result = await db.execute(
        select(NotificationChannel)
        .where(NotificationChannel.user_id == user_id)
        .order_by(NotificationChannel.created_at)
    )
    channels = result.scalars().all()
    return [_mask_channel(c) for c in channels]


@router.post("/channels", status_code=201)
async def create_channel(
    data: NotificationChannelCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationChannelResponse:
    """Create a new notification channel (max 10 per user)."""
    count_result = await db.execute(select(NotificationChannel).where(NotificationChannel.user_id == user_id))
    existing = count_result.scalars().all()
    if len(existing) >= 10:
        raise HTTPException(status_code=400, detail="Maximum of 10 channels allowed")

    channel = NotificationChannel(
        user_id=user_id,
        url=data.url,
        mail_account_ids=[str(aid) for aid in data.mail_account_ids] if data.mail_account_ids else None,
        event_types=data.event_types,
    )
    db.add(channel)
    await db.flush()
    await db.refresh(channel)
    logger.info("notification_channel_created", user_id=user_id, channel_id=str(channel.id))
    return _mask_channel(channel)


@router.patch("/channels/{channel_id}")
async def update_channel(
    channel_id: UUID,
    data: NotificationChannelUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationChannelResponse:
    """Update a notification channel's routing configuration."""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.user_id == user_id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    channel.mail_account_ids = (
        [str(aid) for aid in data.mail_account_ids] if data.mail_account_ids is not None else None
    )
    channel.event_types = data.event_types
    await db.flush()
    await db.refresh(channel)
    logger.info("notification_channel_updated", user_id=user_id, channel_id=str(channel_id))
    return _mask_channel(channel)


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a notification channel."""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.user_id == user_id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    await db.delete(channel)
    await db.flush()
    logger.info("notification_channel_deleted", user_id=user_id, channel_id=str(channel_id))


@router.post("/channels/{channel_id}/test")
async def test_channel(
    channel_id: UUID,
    data: NotificationTestRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationTestResponse:
    """Send a test notification to a specific channel."""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.user_id == user_id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    try:
        success = await send_test_notification([channel.url], data.message)
    except Exception as e:
        logger.error("test_notification_failed", error=str(e))
        return NotificationTestResponse(success=False, message="Failed to send test notification")

    return NotificationTestResponse(
        success=success,
        message="Test notification sent successfully" if success else "Failed to send test notification",
    )


# ---------------------------------------------------------------------------
# Config (templates)
# ---------------------------------------------------------------------------


@router.get("/config")
async def get_config(
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationConfigResponse:
    """Get the notification template configuration for the current user."""
    config = await get_or_create(
        db,
        NotificationConfig,
        user_id,
        templates={},
    )
    return NotificationConfigResponse.model_validate(config)


@router.put("/config")
async def update_config(
    data: NotificationConfigUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationConfigResponse:
    """Update notification templates."""
    config = await get_or_create(
        db,
        NotificationConfig,
        user_id,
        templates={},
    )
    config.templates = data.templates
    await db.flush()
    logger.info("notification_config_updated", user_id=user_id)
    return NotificationConfigResponse.model_validate(config)


# ---------------------------------------------------------------------------
# Event types (dynamic from plugin registry)
# ---------------------------------------------------------------------------


@router.get("/events")
async def list_events(user_id: CurrentUserId) -> list[NotificationEventInfo]:
    """List all available notification event types derived from the plugin registry."""
    events = _get_event_registry()
    result: list[NotificationEventInfo] = []
    for event_type, plugin in sorted(events.items(), key=lambda x: x[1].execution_order):
        result.append(
            NotificationEventInfo(
                event_type=event_type,
                plugin_name=plugin.name,
                display_name=plugin.display_name,
                execution_order=plugin.execution_order,
            )
        )
    # Add the system-level approval_needed event
    result.append(
        NotificationEventInfo(
            event_type="approval_needed",
            plugin_name="_system",
            display_name="Approval Needed",
            execution_order=999,
        )
    )
    return result


# ---------------------------------------------------------------------------
# Variables (dynamic from plugin registry)
# ---------------------------------------------------------------------------


# Base context variables always available in notification templates
_BASE_NOTIFICATION_VARIABLES: list[dict[str, Any]] = [
    {"name": "subject", "var_type": "String", "description": "Email subject line", "example": "Re: Q2 Report"},
    {
        "name": "sender",
        "var_type": "String",
        "description": "Full sender string",
        "example": "Max Müller <max@example.com>",
    },
    {"name": "sender_name", "var_type": "String", "description": "Sender display name", "example": "Max Müller"},
    {"name": "account_name", "var_type": "String", "description": "Mail account name", "example": "Work"},
    {
        "name": "account_email",
        "var_type": "String",
        "description": "Mail account email address",
        "example": "me@work.com",
    },
    {"name": "mail_uid", "var_type": "String", "description": "Unique mail identifier", "example": "12345"},
    {
        "name": "plugins_executed",
        "var_type": "List",
        "description": "List of plugins that processed the email",
        "example": '["email_summary", "coupon_extraction"]',
    },
]


@router.get("/variables")
async def list_variables(
    user_id: CurrentUserId,
    event_type: str | None = None,
) -> list[TemplateVariable]:
    """List available template variables.

    If ``event_type`` is given, returns base variables plus only the variables
    defined by the plugin that owns that event type.  Without ``event_type``,
    returns every variable across all plugins (useful as a full reference).
    """
    base = [TemplateVariable(**v) for v in _BASE_NOTIFICATION_VARIABLES]
    seen_names: set[str] = {v.name for v in base}
    result: list[TemplateVariable] = list(base)

    events = _get_event_registry()

    if event_type is not None:
        # Return base + only this event's plugin variables
        plugin = events.get(event_type)
        if plugin:
            for v in (plugin.get_notification_variables() or []):
                if v["name"] not in seen_names:
                    seen_names.add(v["name"])
                    result.append(TemplateVariable(**v))
    else:
        # Return all plugin variables (full reference)
        for _et, plugin in events.items():
            for v in (plugin.get_notification_variables() or []):
                if v["name"] not in seen_names:
                    seen_names.add(v["name"])
                    result.append(TemplateVariable(**v))

    return result


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


@router.get("/templates/default/{event_type}")
async def get_default_template(event_type: str, user_id: CurrentUserId) -> DefaultTemplateResponse:
    """Return the default on-disk Jinja2 template for a given event type.

    Uses the plugin registry to resolve the template path. Falls back to
    the generic default.j2 for unknown event types.
    """
    events = _get_event_registry()
    plugin = events.get(event_type)
    rel_path = plugin.notification_template if plugin and plugin.notification_template else None

    # Try plugin template, then event-specific file, then default
    candidates = []
    if rel_path:
        candidates.append(_TEMPLATES_DIR / rel_path)
    candidates.append(_TEMPLATES_DIR / f"notifications/{event_type}.j2")
    candidates.append(_TEMPLATES_DIR / _DEFAULT_TEMPLATE_FILE)

    template_path = None
    for candidate in candidates:
        if candidate.is_file():
            template_path = candidate
            break

    if template_path is None:
        raise HTTPException(status_code=404, detail="Default template not found")

    content = template_path.read_text(encoding="utf-8")
    return DefaultTemplateResponse(event_type=event_type, template=content)


@router.post("/preview")
async def preview_notification(
    data: NotificationPreviewRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationPreviewResponse:
    """Preview a rendered notification template with sample data.

    Builds context from the plugin registry's preview data so previews
    match runtime behaviour exactly.
    """
    engine = get_template_engine()

    # Build context from base + plugin preview data
    context: dict[str, Any] = {
        "subject": "Re: Quarterly Planning Meeting",
        "sender": "Max Müller <max@example.com>",
        "sender_name": "Max Müller",
        "account_name": "Work",
        "account_email": "me@work.com",
        "mail_uid": "12345",
        "plugins_executed": ["email_summary", "coupon_extraction"],
        "approvals_created": 0,
    }

    # Add plugin-specific preview context for the requested event type
    events = _get_event_registry()
    plugin = events.get(data.event_type)
    if plugin:
        context.update(plugin.get_preview_context())

    errors: list[str] = []
    rendered = ""

    try:
        rendered = engine.render_string(data.template, context)
    except Exception as e:
        errors.append(str(e))

    return NotificationPreviewResponse(rendered=rendered, errors=errors)
