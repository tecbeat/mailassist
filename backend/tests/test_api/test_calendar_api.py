"""Tests for the Calendar (CalDAV) API endpoints.

Covers config get/create/update, test connection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _make_caldav_config(*, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        caldav_url="https://caldav.example.com/dav",
        encrypted_credentials=b"encrypted",
        default_calendar="Personal",
        include_past_events=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestGetConfig:
    """GET /api/calendar/config"""

    @pytest.mark.asyncio
    async def test_returns_config(self):
        from app.api.calendar import get_config

        config = _make_caldav_config()
        db = AsyncMock()

        with (
            patch("app.api.calendar._get_config", new=AsyncMock(return_value=config)),
            patch("app.api.calendar.CalDAVConfigResponse.model_validate", return_value=MagicMock()),
        ):
            await get_config(db=db, user_id=config.user_id)

    @pytest.mark.asyncio
    async def test_returns_none_when_not_configured(self):
        from app.api.calendar import get_config

        db = AsyncMock()

        with patch("app.api.calendar._get_config", new=AsyncMock(return_value=None)):
            result = await get_config(db=db, user_id=uuid4())

        assert result is None


class TestUpdateConfig:
    """PUT /api/calendar/config"""

    @pytest.mark.asyncio
    async def test_creates_new_config(self):
        from app.api.calendar import update_config
        from app.schemas.calendar import CalDAVConfigUpdate

        db = AsyncMock()
        uid = uuid4()
        data = CalDAVConfigUpdate(
            caldav_url="https://caldav.example.com/dav",
            username="user",
            password="pass",
            default_calendar="Personal",
        )

        with (
            patch("app.api.calendar._get_config", new=AsyncMock(return_value=None)),
            patch("app.services.calendar.encrypt_caldav_credentials", return_value=b"encrypted"),
            patch("app.api.calendar.CalDAVConfigResponse.model_validate", return_value=MagicMock()),
        ):
            await update_config(data=data, db=db, user_id=uid)

        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_config(self):
        from app.api.calendar import update_config
        from app.schemas.calendar import CalDAVConfigUpdate

        config = _make_caldav_config()
        db = AsyncMock()
        data = CalDAVConfigUpdate(
            caldav_url="https://new-caldav.example.com/dav",
            username="newuser",
            password="newpass",
            default_calendar="Work",
        )

        with (
            patch("app.api.calendar._get_config", new=AsyncMock(return_value=config)),
            patch("app.services.calendar.encrypt_caldav_credentials", return_value=b"new-encrypted"),
            patch("app.api.calendar.CalDAVConfigResponse.model_validate", return_value=MagicMock()),
        ):
            await update_config(data=data, db=db, user_id=config.user_id)

        assert config.caldav_url == "https://new-caldav.example.com/dav"
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_without_credentials_raises_422(self):
        from app.api.calendar import update_config
        from app.schemas.calendar import CalDAVConfigUpdate

        db = AsyncMock()
        data = CalDAVConfigUpdate(
            caldav_url="https://caldav.example.com/dav",
            username="",
            password="",
            default_calendar="Personal",
        )

        with (
            patch("app.api.calendar._get_config", new=AsyncMock(return_value=None)),
            pytest.raises(HTTPException) as exc_info,
        ):
            await update_config(data=data, db=db, user_id=uuid4())

        assert exc_info.value.status_code == 422


class TestTestConfig:
    """POST /api/calendar/config/test"""

    @pytest.mark.asyncio
    async def test_with_inline_credentials(self):
        from app.api.calendar import test_config
        from app.schemas.calendar import CalDAVTestRequest

        db = AsyncMock()
        uid = uuid4()
        data = CalDAVTestRequest(
            caldav_url="https://caldav.example.com/dav",
            username="user",
            password="pass",
        )

        test_result = SimpleNamespace(
            success=True,
            message="Connected",
            details={"calendars": ["Personal", "Work"]},
        )

        with patch("app.services.calendar.test_caldav_connection", new=AsyncMock(return_value=test_result)):
            resp = await test_config(db=db, user_id=uid, data=data)

        assert resp.success is True
        assert "Personal" in resp.calendars

    @pytest.mark.asyncio
    async def test_with_stored_config(self):
        from app.api.calendar import test_config

        config = _make_caldav_config()
        db = AsyncMock()

        test_result = SimpleNamespace(
            success=True,
            message="Connected",
            details={"calendars": ["Personal"]},
        )

        with (
            patch("app.api.calendar._get_config", new=AsyncMock(return_value=config)),
            patch("app.services.calendar.get_caldav_credentials", return_value=("user", "pass")),
            patch("app.services.calendar.test_caldav_connection", new=AsyncMock(return_value=test_result)),
        ):
            resp = await test_config(db=db, user_id=config.user_id, data=None)

        assert resp.success is True

    @pytest.mark.asyncio
    async def test_no_config_no_credentials_raises_404(self):
        from app.api.calendar import test_config

        db = AsyncMock()

        with (
            patch("app.api.calendar._get_config", new=AsyncMock(return_value=None)),
            pytest.raises(HTTPException) as exc_info,
        ):
            await test_config(db=db, user_id=uuid4(), data=None)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_connection_failure_raises_502(self):
        from app.api.calendar import test_config
        from app.schemas.calendar import CalDAVTestRequest

        db = AsyncMock()
        data = CalDAVTestRequest(
            caldav_url="https://caldav.example.com/dav",
            username="user",
            password="pass",
        )

        with (
            patch("app.services.calendar.test_caldav_connection", new=AsyncMock(side_effect=Exception("timeout"))),
            pytest.raises(HTTPException) as exc_info,
        ):
            await test_config(db=db, user_id=uuid4(), data=data)

        assert exc_info.value.status_code == 502
