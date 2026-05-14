"""Tests for app.services.notifications."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.notifications import (
    _render_notification,
    _split_title_body,
    send_notification,
    send_test_notification,
)

# ---------------------------------------------------------------------------
# _split_title_body
# ---------------------------------------------------------------------------


class TestSplitTitleBody:
    def test_single_line(self):
        title, body = _split_title_body("Hello World")
        assert title == "Hello World"
        assert body == ""

    def test_multi_line_with_blank_separator(self):
        rendered = "My Title\n\nLine one\nLine two"
        title, body = _split_title_body(rendered)
        assert title == "My Title"
        assert body == "Line one\nLine two"

    def test_multi_line_no_blank_separator(self):
        rendered = "My Title\nLine one\nLine two"
        title, body = _split_title_body(rendered)
        assert title == "My Title"
        # body_start stays at 1 since no blank line found
        assert body == "Line one\nLine two"

    def test_empty_string(self):
        title, body = _split_title_body("")
        assert title == ""
        assert body == ""

    def test_strips_title_whitespace(self):
        title, _body = _split_title_body("  My Title  \n\nBody")
        assert title == "My Title"


# ---------------------------------------------------------------------------
# _render_notification
# ---------------------------------------------------------------------------


class TestRenderNotification:
    def test_custom_template(self):
        engine = MagicMock()
        engine.render_string.return_value = "Custom rendered"

        result = _render_notification(engine, "reply_needed", {"key": "val"}, "Hello {{ key }}")
        assert result == "Custom rendered"
        engine.render_string.assert_called_once_with("Hello {{ key }}", {"key": "val"})

    def test_custom_template_failure_falls_back(self):
        engine = MagicMock()
        engine.render_string.side_effect = Exception("bad template")
        engine.render.return_value = "Default rendered"

        result = _render_notification(engine, "reply_needed", {}, "{{ broken")
        assert result == "Default rendered"

    def test_default_template(self):
        engine = MagicMock()
        engine.render.return_value = "Default rendered"

        result = _render_notification(engine, "reply_needed", {"subject": "Hi"})
        assert result == "Default rendered"
        engine.render.assert_called_once_with("notifications/reply_needed.j2", {"subject": "Hi"})

    def test_unknown_event_type_uses_fallback_template(self):
        engine = MagicMock()
        engine.render.return_value = "Fallback rendered"

        _render_notification(engine, "unknown_event", {})
        engine.render.assert_called_once_with("notifications/default.j2", {})

    def test_all_templates_fail_hardcoded_fallback(self):
        engine = MagicMock()
        engine.render.side_effect = Exception("not found")

        result = _render_notification(engine, "reply_needed", {"subject": "Test", "sender": "bob@test.com"})
        assert "reply_needed" in result
        assert "bob@test.com" in result
        assert "Test" in result


# ---------------------------------------------------------------------------
# send_notification
# ---------------------------------------------------------------------------


class TestSendNotification:
    @pytest.mark.asyncio
    async def test_no_urls_returns_false(self):
        result = await send_notification([], "reply_needed", {})
        assert result is False

    @pytest.mark.asyncio
    async def test_sends_notification(self):
        mock_engine = MagicMock()
        mock_engine.render.return_value = "Title\n\nBody text"

        with (
            patch("app.services.notifications.get_template_engine", return_value=mock_engine),
            patch("app.services.notifications._send_async", new_callable=AsyncMock, return_value=True) as mock_send,
        ):
            result = await send_notification(["http://example.com"], "reply_needed", {})

        assert result is True
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_exception_returns_false(self):
        mock_engine = MagicMock()
        mock_engine.render.return_value = "Title\n\nBody"

        with (
            patch("app.services.notifications.get_template_engine", return_value=mock_engine),
            patch("app.services.notifications._send_async", new_callable=AsyncMock, side_effect=Exception("fail")),
        ):
            result = await send_notification(["http://example.com"], "reply_needed", {})

        assert result is False


# ---------------------------------------------------------------------------
# send_test_notification
# ---------------------------------------------------------------------------


class TestSendTestNotification:
    @pytest.mark.asyncio
    async def test_no_urls_returns_false(self):
        result = await send_test_notification([], "Hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_success(self):
        with patch(
            "app.services.notifications._send_async",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_send:
            result = await send_test_notification(["http://example.com"], "Test message")

        assert result is True
        mock_send.assert_awaited_once()
        call_kwargs = mock_send.call_args
        assert call_kwargs.kwargs["body"] == "Test message"
        assert "Test Notification" in call_kwargs.kwargs["title"]

    @pytest.mark.asyncio
    async def test_exception_returns_false(self):
        with patch(
            "app.services.notifications._send_async",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            result = await send_test_notification(["http://example.com"], "Test")

        assert result is False
