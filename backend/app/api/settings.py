"""User settings API endpoints.

Provides user-level application settings management including
approval modes per function, draft expiry, polling defaults, and timezone.
"""

import structlog
from fastapi import APIRouter

from app.api.deps import CurrentUserId, DbSession, get_or_create
from app.models import UserSettings
from app.schemas.settings import (
    ApprovalModes,
    SettingsResponse,
    SettingsUpdate,
)

# Maps ApprovalModesUpdate field names to UserSettings column names
_APPROVAL_MODE_COLUMNS = {
    "spam": "approval_mode_spam",
    "labeling": "approval_mode_labeling",
    "smart_folder": "approval_mode_smart_folder",
    "newsletter": "approval_mode_newsletter",
    "auto_reply": "approval_mode_auto_reply",
    "coupon": "approval_mode_coupon",
    "calendar": "approval_mode_calendar",
    "summary": "approval_mode_summary",
    "rules": "approval_mode_rules",
    "contacts": "approval_mode_contacts",
    "notifications": "approval_mode_notifications",
}

logger = structlog.get_logger()

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _to_response(settings: UserSettings) -> SettingsResponse:
    """Convert ORM model to response schema with nested approval modes."""
    return SettingsResponse(
        id=settings.id,
        timezone=settings.timezone,
        language=settings.language,
        default_polling_interval_minutes=settings.default_polling_interval_minutes,
        draft_expiry_hours=settings.draft_expiry_hours,
        max_concurrent_processing=settings.max_concurrent_processing,
        ai_timeout_seconds=settings.ai_timeout_seconds,
        approval_modes=ApprovalModes(
            spam=settings.approval_mode_spam,
            labeling=settings.approval_mode_labeling,
            smart_folder=settings.approval_mode_smart_folder,
            newsletter=settings.approval_mode_newsletter,
            auto_reply=settings.approval_mode_auto_reply,
            coupon=settings.approval_mode_coupon,
            calendar=settings.approval_mode_calendar,
            summary=settings.approval_mode_summary,
            rules=settings.approval_mode_rules,
            contacts=settings.approval_mode_contacts,
            notifications=settings.approval_mode_notifications,
        ),
        plugin_order=settings.plugin_order,
        plugin_provider_map=settings.plugin_provider_map,
        updated_at=settings.updated_at,
    )


@router.get("")
async def get_settings(
    db: DbSession,
    user_id: CurrentUserId,
) -> SettingsResponse:
    """Get current user settings.

    Returns default settings if none exist yet (auto-provisioned).
    """
    settings = await get_or_create(db, UserSettings, user_id)
    return _to_response(settings)


@router.put("")
async def update_settings(
    data: SettingsUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> SettingsResponse:
    """Update user settings (partial update -- only provided fields are changed)."""
    uid = user_id
    settings = await get_or_create(db, UserSettings, uid)

    if data.timezone is not None:
        settings.timezone = data.timezone
    if data.language is not None:
        settings.language = data.language
    if data.default_polling_interval_minutes is not None:
        settings.default_polling_interval_minutes = data.default_polling_interval_minutes
    if data.draft_expiry_hours is not None:
        settings.draft_expiry_hours = data.draft_expiry_hours
    if data.approval_modes is not None:
        for field_name, column_name in _APPROVAL_MODE_COLUMNS.items():
            value = getattr(data.approval_modes, field_name)
            if value is not None:
                setattr(settings, column_name, value.value)
    if data.max_concurrent_processing is not None:
        settings.max_concurrent_processing = data.max_concurrent_processing
    if data.ai_timeout_seconds is not None:
        settings.ai_timeout_seconds = data.ai_timeout_seconds
    if data.plugin_order is not None:
        settings.plugin_order = data.plugin_order
    if data.plugin_provider_map is not None:
        settings.plugin_provider_map = data.plugin_provider_map

    await db.flush()
    logger.info("user_settings_updated", user_id=user_id)
    return _to_response(settings)
