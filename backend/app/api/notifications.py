"""Notification configuration API endpoints.

Provides management for Apprise notification URLs, templates, and event toggles.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUserId, DbSession, get_or_create
from app.api.prompts import _TEMPLATE_VARIABLES, _build_preview_context
from app.core.templating import get_template_engine
from app.models import NotificationConfig
from app.schemas.notification import (
    DefaultTemplateResponse,
    NotificationConfigResponse,
    NotificationConfigUpdate,
    NotificationPreviewRequest,
    NotificationPreviewResponse,
    NotificationTestRequest,
    NotificationTestResponse,
    NotificationUrlAdd,
    mask_apprise_url,
)
from app.schemas.prompt import TemplateVariable
from app.services.notifications import send_test_notification

logger = structlog.get_logger()

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# Notification-specific template variables (in addition to the 28 base variables from prompts)
_NOTIFICATION_VARIABLES: list[dict[str, Any]] = [
    {
        "name": "action_taken",
        "var_type": "String",
        "description": "Action performed by the AI plugin",
        "example": "Moved to Work/Projects",
    },
    {
        "name": "ai_summary",
        "var_type": "String",
        "description": "AI-generated summary of the email",
        "example": "Meeting confirmation for tomorrow at 2pm...",
    },
    {
        "name": "coupon_codes",
        "var_type": "List",
        "description": "Extracted coupon/discount codes",
        "example": '["SAVE20", "FREESHIP"]',
    },
    {
        "name": "calendar_event",
        "var_type": "Dict",
        "description": "Extracted calendar event details",
        "example": '{"title": "Team Meeting", "start": "2026-03-31T14:00:00Z"}',
    },
    {"name": "spam_score", "var_type": "Float", "description": "Spam detection confidence score", "example": "0.15"},
    {
        "name": "labels_applied",
        "var_type": "List",
        "description": "Labels applied by the AI",
        "example": '["work", "meeting"]',
    },
    {
        "name": "moved_to",
        "var_type": "String",
        "description": "Folder the email was moved to",
        "example": "Work/Projects",
    },
    {
        "name": "rule_name",
        "var_type": "String",
        "description": "Name of the rule that triggered",
        "example": "Auto-label work emails",
    },
    {
        "name": "summary",
        "var_type": "String",
        "description": "Short email summary text",
        "example": "Meeting confirmation for Q2 report discussion.",
    },
    {
        "name": "key_points",
        "var_type": "List",
        "description": "Key points extracted from the email",
        "example": '["Meeting at 2pm", "Bring Q2 report"]',
    },
    {"name": "urgency", "var_type": "String", "description": "Urgency level of the email", "example": "medium"},
    {
        "name": "action_required",
        "var_type": "Boolean",
        "description": "Whether user action is required",
        "example": "true",
    },
    {
        "name": "action_description",
        "var_type": "String",
        "description": "Description of required action",
        "example": "Prepare Q2 report for meeting",
    },
    {
        "name": "contact_name",
        "var_type": "String",
        "description": "Name of the assigned contact",
        "example": "Max Müller",
    },
    {
        "name": "confidence",
        "var_type": "Float",
        "description": "Confidence score of the contact assignment",
        "example": "0.92",
    },
    {
        "name": "is_new_contact_suggestion",
        "var_type": "Boolean",
        "description": "Whether this is a new contact suggestion",
        "example": "true",
    },
    {
        "name": "reasoning",
        "var_type": "String",
        "description": "AI reasoning for the contact assignment",
        "example": "Email address matches known contact",
    },
]


@router.get("/config")
async def get_config(
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationConfigResponse:
    """Get the notification configuration for the current user.

    Returns default empty config if none exists.
    Apprise URLs are masked for security (they may contain tokens/passwords).
    """
    config = await get_or_create(
        db,
        NotificationConfig,
        UUID(user_id),
        apprise_urls=[],
        templates={},
        notify_on={},
    )
    response = NotificationConfigResponse.model_validate(config)
    response.apprise_urls = [mask_apprise_url(u) for u in (config.apprise_urls or [])]
    return response


@router.put("/config")
async def update_config(
    data: NotificationConfigUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationConfigResponse:
    """Update notification configuration (templates and notify_on only).

    Apprise URLs are managed via dedicated add/remove endpoints.
    """
    uid = UUID(user_id)
    config = await get_or_create(
        db,
        NotificationConfig,
        uid,
        apprise_urls=[],
        templates={},
        notify_on={},
    )

    # Only update templates and notify_on; URLs managed separately
    if data.apprise_urls is not None:
        config.apprise_urls = data.apprise_urls
    config.templates = data.templates
    config.notify_on = data.notify_on.model_dump()

    await db.flush()
    logger.info("notification_config_updated", user_id=user_id)
    response = NotificationConfigResponse.model_validate(config)
    response.apprise_urls = [mask_apprise_url(u) for u in (config.apprise_urls or [])]
    return response


@router.post("/config/urls")
async def add_url(
    data: NotificationUrlAdd,
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationConfigResponse:
    """Add a new Apprise URL to the notification configuration."""
    uid = UUID(user_id)
    config = await get_or_create(
        db,
        NotificationConfig,
        uid,
        apprise_urls=[],
        templates={},
        notify_on={},
    )

    urls = list(config.apprise_urls or [])
    if len(urls) >= 10:
        raise HTTPException(status_code=400, detail="Maximum of 10 URLs allowed")
    urls.append(data.url)
    config.apprise_urls = urls

    await db.flush()
    logger.info("notification_url_added", user_id=user_id)
    response = NotificationConfigResponse.model_validate(config)
    response.apprise_urls = [mask_apprise_url(u) for u in config.apprise_urls]
    return response


@router.delete("/config/urls/{index}")
async def remove_url(
    index: int,
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationConfigResponse:
    """Remove an Apprise URL by index."""
    uid = UUID(user_id)
    config = await get_or_create(
        db,
        NotificationConfig,
        uid,
        apprise_urls=[],
        templates={},
        notify_on={},
    )

    urls = list(config.apprise_urls or [])
    if index < 0 or index >= len(urls):
        raise HTTPException(status_code=404, detail="URL index out of range")
    urls.pop(index)
    config.apprise_urls = urls

    await db.flush()
    logger.info("notification_url_removed", user_id=user_id, index=index)
    response = NotificationConfigResponse.model_validate(config)
    response.apprise_urls = [mask_apprise_url(u) for u in config.apprise_urls]
    return response


@router.post("/test")
async def test_notification(
    data: NotificationTestRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationTestResponse:
    """Send a test notification to all configured Apprise URLs."""
    config = await get_or_create(
        db,
        NotificationConfig,
        UUID(user_id),
        apprise_urls=[],
        templates={},
        notify_on={},
    )

    if not config.apprise_urls:
        return NotificationTestResponse(
            success=False,
            message="No Apprise URLs configured",
        )

    try:
        success = await send_test_notification(config.apprise_urls, data.message)
    except Exception as e:
        logger.error("test_notification_failed", error=str(e))
        return NotificationTestResponse(
            success=False,
            message="Failed to send test notification",
        )

    return NotificationTestResponse(
        success=success,
        message="Test notification sent successfully" if success else "Failed to send test notification",
    )


@router.get("/variables")
async def list_variables(user_id: CurrentUserId) -> list[TemplateVariable]:
    """List all template variables available for notification templates.

    Returns the 28 base email variables plus 13 notification-specific variables.
    """
    all_vars = _TEMPLATE_VARIABLES + _NOTIFICATION_VARIABLES
    return [TemplateVariable(**v) for v in all_vars]


# Map frontend event types to on-disk .j2 template filenames
_TEMPLATE_FILE_MAP: dict[str, str] = {
    "reply_needed": "notifications/reply_needed.j2",
    "coupon_found": "notifications/coupon_found.j2",
    "calendar_event_created": "notifications/calendar_created.j2",
    "email_summary": "notifications/email_summary.j2",
    "contact_assigned": "notifications/contact_assigned.j2",
}
_DEFAULT_TEMPLATE_FILE = "notifications/default.j2"
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


@router.get("/templates/default/{event_type}")
async def get_default_template(event_type: str, user_id: CurrentUserId) -> DefaultTemplateResponse:
    """Return the default on-disk Jinja2 template for a given event type.

    Falls back to the generic ``default.j2`` for event types without a
    dedicated template file.
    """
    rel_path = _TEMPLATE_FILE_MAP.get(event_type, _DEFAULT_TEMPLATE_FILE)
    template_path = _TEMPLATES_DIR / rel_path
    if not template_path.is_file():
        raise HTTPException(status_code=404, detail="Default template not found")
    content = template_path.read_text(encoding="utf-8")
    return DefaultTemplateResponse(event_type=event_type, template=content)


@router.post("/preview")
async def preview_notification(
    data: NotificationPreviewRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> NotificationPreviewResponse:
    """Preview a rendered notification template with sample data."""
    engine = get_template_engine()

    # Build user-aware base context (resolves language/timezone from settings)
    base_context = await _build_preview_context(db, user_id)

    context = {
        **base_context,
        "action_taken": "Moved to Work/Projects",
        "ai_summary": "Meeting confirmation for tomorrow at 2pm with discussion of Q2 report.",
        "coupon_codes": ["SAVE20", "FREESHIP"],
        "calendar_event": {"title": "Team Meeting", "start": "2026-03-31T14:00:00Z"},
        "spam_score": 0.15,
        "labels_applied": ["work", "meeting"],
        "moved_to": "Work/Projects",
        "rule_name": "Auto-label work emails",
        "summary": "Meeting confirmation for Q2 report discussion.",
        "key_points": ["Meeting at 2pm", "Bring Q2 report"],
        "urgency": "medium",
        "action_required": True,
        "action_description": "Prepare Q2 report for meeting",
        "contact_name": "Max Müller",
        "confidence": 0.92,
        "is_new_contact_suggestion": False,
        "reasoning": "Email address matches known contact",
    }

    errors: list[str] = []
    rendered = ""

    try:
        rendered = engine.render_string(data.template, context)
    except Exception as e:
        errors.append(str(e))

    return NotificationPreviewResponse(rendered=rendered, errors=errors)
