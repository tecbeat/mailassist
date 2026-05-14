"""Tests for the notification event handler.

Covers: _build_event_type_map, _channel_matches, handle_ai_processing_complete,
and register_notification_handlers.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.notification_handler import (
    _build_event_type_map,
    _channel_matches,
    handle_ai_processing_complete,
    register_notification_handlers,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin(name: str, event_type: str | None) -> MagicMock:
    """Create a mock plugin with name and notification_event_type."""
    p = MagicMock()
    p.name = name
    p.notification_event_type = event_type
    return p


def _make_channel(
    *,
    mail_account_ids: list[str] | None = None,
    event_types: list[str] | None = None,
    url: str = "json://localhost",
    user_id=None,
) -> MagicMock:
    """Create a mock NotificationChannel."""
    c = MagicMock()
    c.mail_account_ids = mail_account_ids
    c.event_types = event_types
    c.url = url
    c.user_id = user_id or uuid4()
    return c


def _make_event(
    *,
    plugins_executed: list[str] | None = None,
    approvals_created: int = 0,
    user_id=None,
    account_id=None,
    mail_uid: str = "uid-1",
    mail_id=None,
    current_folder: str = "INBOX",
    correlation_id: str | None = None,
) -> MagicMock:
    """Create a mock AIProcessingCompleteEvent."""
    from app.core.events import AIProcessingCompleteEvent

    evt = MagicMock(spec=AIProcessingCompleteEvent)
    evt.plugins_executed = plugins_executed or []
    evt.approvals_created = approvals_created
    evt.user_id = user_id or uuid4()
    evt.account_id = account_id or uuid4()
    evt.mail_uid = mail_uid
    evt.mail_id = mail_id
    evt.current_folder = current_folder
    evt.correlation_id = correlation_id
    return evt


# ---------------------------------------------------------------------------
# _build_event_type_map
# ---------------------------------------------------------------------------


class TestBuildEventTypeMap:
    """Test dynamic plugin→event_type mapping."""

    @patch("app.workers.notification_handler.get_plugin_registry")
    def test_maps_plugins_with_event_types(self, mock_registry):
        registry = MagicMock()
        registry.get_all_plugins.return_value = [
            _make_plugin("summarize", "email_summarized"),
            _make_plugin("label", "email_labeled"),
        ]
        mock_registry.return_value = registry

        result = _build_event_type_map()

        assert result == {"summarize": "email_summarized", "label": "email_labeled"}

    @patch("app.workers.notification_handler.get_plugin_registry")
    def test_skips_plugins_without_event_type(self, mock_registry):
        registry = MagicMock()
        registry.get_all_plugins.return_value = [
            _make_plugin("summarize", "email_summarized"),
            _make_plugin("internal", None),
        ]
        mock_registry.return_value = registry

        result = _build_event_type_map()

        assert result == {"summarize": "email_summarized"}
        assert "internal" not in result

    @patch("app.workers.notification_handler.get_plugin_registry")
    def test_empty_registry(self, mock_registry):
        registry = MagicMock()
        registry.get_all_plugins.return_value = []
        mock_registry.return_value = registry

        assert _build_event_type_map() == {}


# ---------------------------------------------------------------------------
# _channel_matches
# ---------------------------------------------------------------------------


class TestChannelMatches:
    """Test per-channel filtering logic."""

    def test_no_filters_matches_all(self):
        channel = _make_channel()
        assert _channel_matches(channel, uuid4(), "any_event") is True

    def test_account_filter_match(self):
        aid = uuid4()
        channel = _make_channel(mail_account_ids=[str(aid)])
        assert _channel_matches(channel, aid, "any_event") is True

    def test_account_filter_no_match(self):
        channel = _make_channel(mail_account_ids=[str(uuid4())])
        assert _channel_matches(channel, uuid4(), "any_event") is False

    def test_event_type_filter_match(self):
        channel = _make_channel(event_types=["email_summarized"])
        assert _channel_matches(channel, uuid4(), "email_summarized") is True

    def test_event_type_filter_no_match(self):
        channel = _make_channel(event_types=["email_summarized"])
        assert _channel_matches(channel, uuid4(), "email_labeled") is False

    def test_both_filters_match(self):
        aid = uuid4()
        channel = _make_channel(
            mail_account_ids=[str(aid)],
            event_types=["email_summarized"],
        )
        assert _channel_matches(channel, aid, "email_summarized") is True

    def test_account_match_event_no_match(self):
        aid = uuid4()
        channel = _make_channel(
            mail_account_ids=[str(aid)],
            event_types=["email_labeled"],
        )
        assert _channel_matches(channel, aid, "email_summarized") is False


# ---------------------------------------------------------------------------
# handle_ai_processing_complete
# ---------------------------------------------------------------------------


class TestHandleAIProcessingComplete:
    """Test the main notification dispatch handler."""

    @pytest.mark.asyncio
    async def test_returns_early_no_plugins_no_approvals(self):
        """No plugins executed and no approvals → early return."""
        event = _make_event(plugins_executed=[], approvals_created=0)
        # Should not raise and should return without DB access
        await handle_ai_processing_complete(event)

    @pytest.mark.asyncio
    @patch("app.workers.notification_handler.get_event_bus")
    @patch("app.workers.notification_handler.send_notification", new_callable=AsyncMock)
    @patch("app.workers.notification_handler._load_plugin_context", new_callable=AsyncMock)
    @patch("app.workers.notification_handler._build_event_type_map")
    @patch("app.workers.notification_handler.get_session_ctx")
    async def test_no_channels_returns_early(self, mock_session_ctx, mock_map, mock_ctx, mock_send, mock_bus):
        """Channels query returns empty → skip sending."""
        aid = uuid4()
        event = _make_event(plugins_executed=["summarize"], account_id=aid)

        mock_map.return_value = {"summarize": "email_summarized"}

        # Mock DB session
        db = AsyncMock()
        channels_result = MagicMock()
        channels_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=channels_result)

        ctx_mgr = AsyncMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=db)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = ctx_mgr

        await handle_ai_processing_complete(event)

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.workers.notification_handler.get_event_bus")
    @patch("app.workers.notification_handler.send_notification", new_callable=AsyncMock)
    @patch("app.workers.notification_handler._load_plugin_context", new_callable=AsyncMock)
    @patch("app.workers.notification_handler._build_event_type_map")
    @patch("app.workers.notification_handler.get_session_ctx")
    async def test_matching_channel_sends_notification(self, mock_session_ctx, mock_map, mock_ctx, mock_send, mock_bus):
        """A channel matching both account and event type gets a notification."""
        aid = uuid4()
        uid = uuid4()
        mail_id = uuid4()
        event = _make_event(
            plugins_executed=["summarize"],
            account_id=aid,
            user_id=uid,
            mail_id=mail_id,
        )

        mock_map.return_value = {"summarize": "email_summarized"}
        mock_ctx.return_value = {"summary": "test summary"}
        mock_send.return_value = True

        channel = _make_channel(url="json://localhost")

        # Build mock DB that returns different results per query
        tracked = MagicMock()
        tracked.subject = "Test Subject"
        tracked.sender = "Alice <alice@example.com>"
        tracked.id = mail_id

        account = MagicMock()
        account.name = "Main"
        account.email_address = "me@example.com"

        summary = MagicMock()
        summary.notified = False

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # channels query
                result.scalars.return_value.all.return_value = [channel]
            elif call_count == 2:
                # tracked email
                result.scalars.return_value.first.return_value = tracked
            elif call_count == 3:
                # mail account
                result.scalar_one_or_none.return_value = account
            elif call_count == 4:
                # notification config
                result.scalar_one_or_none.return_value = None
            elif call_count == 5:
                # email summary for notified flag
                result.scalar_one_or_none.return_value = summary
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)
        db.commit = AsyncMock()

        ctx_mgr = AsyncMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=db)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = ctx_mgr

        bus = AsyncMock()
        mock_bus.return_value = bus

        await handle_ai_processing_complete(event)

        mock_send.assert_called_once()
        assert mock_send.call_args.kwargs["event_type"] == "email_summarized"
        assert mock_send.call_args.kwargs["apprise_urls"] == ["json://localhost"]

    @pytest.mark.asyncio
    @patch("app.workers.notification_handler.get_event_bus")
    @patch("app.workers.notification_handler.send_notification", new_callable=AsyncMock)
    @patch("app.workers.notification_handler._load_plugin_context", new_callable=AsyncMock)
    @patch("app.workers.notification_handler._build_event_type_map")
    @patch("app.workers.notification_handler.get_session_ctx")
    async def test_non_matching_channel_skips(self, mock_session_ctx, mock_map, mock_ctx, mock_send, mock_bus):
        """A channel filtered to a different account does not receive a notification."""
        aid = uuid4()
        event = _make_event(plugins_executed=["summarize"], account_id=aid)

        mock_map.return_value = {"summarize": "email_summarized"}

        # Channel filters to a different account
        channel = _make_channel(mail_account_ids=[str(uuid4())])

        tracked = MagicMock()
        tracked.subject = "Test"
        tracked.sender = "bob@example.com"
        tracked.id = uuid4()

        account = MagicMock()
        account.name = "Main"
        account.email_address = "me@example.com"

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalars.return_value.all.return_value = [channel]
            elif call_count == 2:
                result.scalars.return_value.first.return_value = tracked
            elif call_count == 3:
                result.scalar_one_or_none.return_value = account
            elif call_count == 4:
                result.scalar_one_or_none.return_value = None
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=mock_execute)

        ctx_mgr = AsyncMock()
        ctx_mgr.__aenter__ = AsyncMock(return_value=db)
        ctx_mgr.__aexit__ = AsyncMock(return_value=False)
        mock_session_ctx.return_value = ctx_mgr

        await handle_ai_processing_complete(event)

        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_approval_needed_event_type(self):
        """Approvals created triggers approval_needed event type."""
        event = _make_event(plugins_executed=[], approvals_created=2)

        with (
            patch("app.workers.notification_handler._build_event_type_map", return_value={}),
            patch("app.workers.notification_handler.get_session_ctx") as mock_ctx,
            patch("app.workers.notification_handler.send_notification", new_callable=AsyncMock) as mock_send,
            patch("app.workers.notification_handler._load_plugin_context", new_callable=AsyncMock) as mock_lpc,
            patch("app.workers.notification_handler.get_event_bus") as mock_bus,
        ):
            mock_lpc.return_value = {}
            mock_send.return_value = True

            channel = _make_channel(event_types=["approval_needed"])

            tracked = MagicMock()
            tracked.subject = "Test"
            tracked.sender = "bob@example.com"
            tracked.id = uuid4()

            account = MagicMock()
            account.name = "Main"
            account.email_address = "me@example.com"

            summary = MagicMock()
            summary.notified = False

            call_count = 0

            async def mock_execute(stmt):
                nonlocal call_count
                call_count += 1
                result = MagicMock()
                if call_count == 1:
                    result.scalars.return_value.all.return_value = [channel]
                elif call_count == 2:
                    result.scalars.return_value.first.return_value = tracked
                elif call_count == 3:
                    result.scalar_one_or_none.return_value = account
                elif call_count == 4:
                    result.scalar_one_or_none.return_value = None
                elif call_count == 5:
                    result.scalar_one_or_none.return_value = summary
                return result

            db = AsyncMock()
            db.execute = AsyncMock(side_effect=mock_execute)
            db.commit = AsyncMock()

            ctx_mgr_obj = AsyncMock()
            ctx_mgr_obj.__aenter__ = AsyncMock(return_value=db)
            ctx_mgr_obj.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.return_value = ctx_mgr_obj

            bus = AsyncMock()
            mock_bus.return_value = bus

            await handle_ai_processing_complete(event)

            mock_send.assert_called_once()
            assert mock_send.call_args.kwargs["event_type"] == "approval_needed"


# ---------------------------------------------------------------------------
# register_notification_handlers
# ---------------------------------------------------------------------------


class TestRegisterNotificationHandlers:
    """Test handler registration on the event bus."""

    @patch("app.workers.notification_handler.get_event_bus")
    def test_subscribes_to_ai_processing_complete(self, mock_get_bus):
        bus = MagicMock()
        mock_get_bus.return_value = bus

        register_notification_handlers()

        bus.subscribe.assert_called_once()
        args = bus.subscribe.call_args[0]
        from app.core.events import AIProcessingCompleteEvent

        assert args[0] is AIProcessingCompleteEvent
        assert args[1] is handle_ai_processing_complete
