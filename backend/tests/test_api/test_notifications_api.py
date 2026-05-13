"""Tests for the Notifications API endpoints.

Covers channel CRUD, test notification, config get/update, events listing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _make_channel(*, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        url="slack://token-a/token-b/token-c",
        mail_account_ids=None,
        event_types=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_config(*, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        templates={},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestListChannels:
    """GET /api/notifications/channels"""

    @pytest.mark.asyncio
    async def test_returns_channels(self):
        from app.api.notifications import list_channels

        channel = _make_channel()
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [channel]
        db.execute.return_value = result

        with patch("app.api.notifications._mask_channel", return_value=MagicMock()):
            resp = await list_channels(db=db, user_id=channel.user_id)

        assert len(resp) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        from app.api.notifications import list_channels

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute.return_value = result

        resp = await list_channels(db=db, user_id=uuid4())
        assert resp == []


class TestCreateChannel:
    """POST /api/notifications/channels"""

    @pytest.mark.asyncio
    async def test_creates_channel(self):
        from app.api.notifications import create_channel
        from app.schemas.notification import NotificationChannelCreate

        db = AsyncMock()
        uid = uuid4()
        data = NotificationChannelCreate(url="slack://tok/tok/tok")

        # Count existing: 0
        count_result = MagicMock()
        count_result.scalars.return_value.all.return_value = []
        db.execute.return_value = count_result

        with patch("app.api.notifications._mask_channel", return_value=MagicMock()):
            await create_channel(data=data, db=db, user_id=uid)

        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_max_channels_raises_400(self):
        from app.api.notifications import create_channel
        from app.schemas.notification import NotificationChannelCreate

        db = AsyncMock()
        uid = uuid4()
        data = NotificationChannelCreate(url="slack://tok/tok/tok")

        # 10 existing channels
        count_result = MagicMock()
        count_result.scalars.return_value.all.return_value = [MagicMock()] * 10
        db.execute.return_value = count_result

        with pytest.raises(HTTPException) as exc_info:
            await create_channel(data=data, db=db, user_id=uid)

        assert exc_info.value.status_code == 400


class TestUpdateChannel:
    """PATCH /api/notifications/channels/{channel_id}"""

    @pytest.mark.asyncio
    async def test_updates_channel(self):
        from app.api.notifications import update_channel
        from app.schemas.notification import NotificationChannelUpdate

        channel = _make_channel()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = channel
        db.execute.return_value = result

        data = NotificationChannelUpdate(event_types=["email_summary"])

        with patch("app.api.notifications._mask_channel", return_value=MagicMock()):
            await update_channel(channel_id=channel.id, data=data, db=db, user_id=channel.user_id)

        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.notifications import update_channel
        from app.schemas.notification import NotificationChannelUpdate

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        data = NotificationChannelUpdate(event_types=["email_summary"])

        with pytest.raises(HTTPException) as exc_info:
            await update_channel(channel_id=uuid4(), data=data, db=db, user_id=uuid4())

        assert exc_info.value.status_code == 404


class TestDeleteChannel:
    """DELETE /api/notifications/channels/{channel_id}"""

    @pytest.mark.asyncio
    async def test_deletes_channel(self):
        from app.api.notifications import delete_channel

        channel = _make_channel()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = channel
        db.execute.return_value = result

        await delete_channel(channel_id=channel.id, db=db, user_id=channel.user_id)

        db.delete.assert_awaited_once_with(channel)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.notifications import delete_channel

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        with pytest.raises(HTTPException) as exc_info:
            await delete_channel(channel_id=uuid4(), db=db, user_id=uuid4())

        assert exc_info.value.status_code == 404


class TestTestChannel:
    """POST /api/notifications/channels/{channel_id}/test"""

    @pytest.mark.asyncio
    async def test_successful_test(self):
        from app.api.notifications import test_channel
        from app.schemas.notification import NotificationTestRequest

        channel = _make_channel()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = channel
        db.execute.return_value = result

        data = NotificationTestRequest(message="Hello")

        with patch("app.api.notifications.send_test_notification", new=AsyncMock(return_value=True)):
            resp = await test_channel(channel_id=channel.id, data=data, db=db, user_id=channel.user_id)

        assert resp.success is True

    @pytest.mark.asyncio
    async def test_failed_test(self):
        from app.api.notifications import test_channel
        from app.schemas.notification import NotificationTestRequest

        channel = _make_channel()
        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = channel
        db.execute.return_value = result

        data = NotificationTestRequest(message="Hello")

        with patch("app.api.notifications.send_test_notification", new=AsyncMock(side_effect=Exception("fail"))):
            resp = await test_channel(channel_id=channel.id, data=data, db=db, user_id=channel.user_id)

        assert resp.success is False

    @pytest.mark.asyncio
    async def test_channel_not_found_raises_404(self):
        from app.api.notifications import test_channel
        from app.schemas.notification import NotificationTestRequest

        db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        db.execute.return_value = result

        data = NotificationTestRequest(message="Hello")

        with pytest.raises(HTTPException) as exc_info:
            await test_channel(channel_id=uuid4(), data=data, db=db, user_id=uuid4())

        assert exc_info.value.status_code == 404


class TestGetConfig:
    """GET /api/notifications/config"""

    @pytest.mark.asyncio
    async def test_returns_config(self):
        from app.api.notifications import get_config

        config = _make_config()
        db = AsyncMock()

        with (
            patch("app.api.notifications.get_or_create", new=AsyncMock(return_value=config)),
            patch("app.api.notifications.NotificationConfigResponse.model_validate", return_value=MagicMock()),
        ):
            await get_config(db=db, user_id=config.user_id)


class TestUpdateConfig:
    """PUT /api/notifications/config"""

    @pytest.mark.asyncio
    async def test_updates_config(self):
        from app.api.notifications import update_config
        from app.schemas.notification import NotificationConfigUpdate

        config = _make_config()
        db = AsyncMock()
        data = NotificationConfigUpdate(templates={"email_summary": "custom template"})

        with (
            patch("app.api.notifications.get_or_create", new=AsyncMock(return_value=config)),
            patch("app.api.notifications.NotificationConfigResponse.model_validate", return_value=MagicMock()),
        ):
            await update_config(data=data, db=db, user_id=config.user_id)

        assert config.templates == {"email_summary": "custom template"}
        db.flush.assert_awaited_once()


class TestListEvents:
    """GET /api/notifications/events"""

    @pytest.mark.asyncio
    async def test_returns_events(self):
        from app.api.notifications import list_events

        mock_plugin = MagicMock()
        mock_plugin.notification_event_type = "email_summary"
        mock_plugin.name = "email_summary"
        mock_plugin.display_name = "Email Summary"
        mock_plugin.execution_order = 10

        with patch("app.api.notifications._get_event_registry", return_value={"email_summary": mock_plugin}):
            resp = await list_events(user_id=uuid4())

        # Should include the plugin event + the system approval_needed event
        assert len(resp) >= 2
        event_types = [e.event_type for e in resp]
        assert "email_summary" in event_types
        assert "approval_needed" in event_types
