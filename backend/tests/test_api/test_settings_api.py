"""Tests for the Settings API endpoints.

Covers get settings (auto-provision) and update settings (partial update).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


def _make_settings(*, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        timezone="UTC",
        language="en",
        default_polling_interval_minutes=5,
        draft_expiry_hours=24,
        max_concurrent_processing=3,
        ai_timeout_seconds=30,
        auto_approve_threshold=None,
        approval_mode_spam="auto",
        approval_mode_labeling="auto",
        approval_mode_smart_folder="auto",
        approval_mode_newsletter="auto",
        approval_mode_auto_reply="approval",
        approval_mode_coupon="auto",
        approval_mode_calendar="auto",
        approval_mode_summary="auto",
        approval_mode_rules="auto",
        approval_mode_contacts="auto",
        approval_mode_notifications="auto",
        approval_mode_otp="auto",
        plugin_order=None,
        plugin_provider_map=None,
        tool_modes=None,
        updated_at=datetime.now(UTC),
    )


class TestGetSettings:
    """GET /api/settings"""

    @pytest.mark.asyncio
    async def test_returns_settings(self):
        from app.api.settings import get_settings

        settings = _make_settings()
        db = AsyncMock()

        with patch("app.api.settings.get_or_create", new=AsyncMock(return_value=settings)):
            resp = await get_settings(db=db, user_id=settings.user_id)

        assert resp.timezone == "UTC"
        assert resp.language == "en"
        assert resp.approval_modes.spam == "auto"
        assert resp.approval_modes.auto_reply == "approval"


class TestUpdateSettings:
    """PUT /api/settings"""

    @pytest.mark.asyncio
    async def test_updates_timezone(self):
        from app.api.settings import update_settings
        from app.schemas.settings import SettingsUpdate

        settings = _make_settings()
        db = AsyncMock()
        data = SettingsUpdate(timezone="Europe/Berlin")

        with patch("app.api.settings.get_or_create", new=AsyncMock(return_value=settings)):
            await update_settings(data=data, db=db, user_id=settings.user_id)

        assert settings.timezone == "Europe/Berlin"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_polling_interval(self):
        from app.api.settings import update_settings
        from app.schemas.settings import SettingsUpdate

        settings = _make_settings()
        db = AsyncMock()
        data = SettingsUpdate(default_polling_interval_minutes=10)

        with patch("app.api.settings.get_or_create", new=AsyncMock(return_value=settings)):
            await update_settings(data=data, db=db, user_id=settings.user_id)

        assert settings.default_polling_interval_minutes == 10

    @pytest.mark.asyncio
    async def test_updates_plugin_order(self):
        from app.api.settings import update_settings
        from app.schemas.settings import SettingsUpdate

        settings = _make_settings()
        db = AsyncMock()
        data = SettingsUpdate(plugin_order=["email_summary", "coupon_extraction"])

        with patch("app.api.settings.get_or_create", new=AsyncMock(return_value=settings)):
            await update_settings(data=data, db=db, user_id=settings.user_id)

        assert settings.plugin_order == ["email_summary", "coupon_extraction"]

    @pytest.mark.asyncio
    async def test_partial_update_leaves_other_fields(self):
        from app.api.settings import update_settings
        from app.schemas.settings import SettingsUpdate

        settings = _make_settings()
        db = AsyncMock()
        data = SettingsUpdate(language="de")

        with patch("app.api.settings.get_or_create", new=AsyncMock(return_value=settings)):
            await update_settings(data=data, db=db, user_id=settings.user_id)

        assert settings.language == "de"
        assert settings.timezone == "UTC"  # unchanged
