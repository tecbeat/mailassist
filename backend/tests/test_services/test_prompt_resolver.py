"""Tests for app.services.prompt_resolver."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.prompt_resolver import resolve_prompts
from tests.conftest import make_mail_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plugin(name: str = "labeling", template: str = "prompts/labeling.j2"):
    plugin = MagicMock()
    plugin.name = name
    plugin.default_prompt_template = template
    return plugin


def _make_engine():
    engine = MagicMock()
    engine.render_string.side_effect = lambda src, ctx: f"rendered:{src[:20]}"
    engine.render.side_effect = lambda name, ctx: f"file:{name}"
    return engine


# ---------------------------------------------------------------------------
# resolve_prompts
# ---------------------------------------------------------------------------


class TestResolvePrompts:
    @pytest.mark.asyncio
    async def test_custom_prompt_found(self):
        user_id = uuid4()
        plugin = _make_plugin()
        engine = _make_engine()
        context = make_mail_context()

        custom = MagicMock()
        custom.is_custom = True
        custom.system_prompt = "You are a labeling assistant."
        custom.user_prompt = "Label this email."

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = custom
        mock_db.execute.return_value = mock_result

        system, user = await resolve_prompts(mock_db, user_id, plugin, engine, context)
        engine.render_string.assert_called()
        assert system.startswith("rendered:")
        assert user.startswith("rendered:")

    @pytest.mark.asyncio
    async def test_custom_prompt_no_user_prompt(self):
        user_id = uuid4()
        plugin = _make_plugin()
        engine = _make_engine()
        context = make_mail_context()

        custom = MagicMock()
        custom.is_custom = True
        custom.system_prompt = "System prompt text"
        custom.user_prompt = None

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = custom
        mock_db.execute.return_value = mock_result

        _system, user = await resolve_prompts(mock_db, user_id, plugin, engine, context)
        assert "JSON format" in user

    @pytest.mark.asyncio
    async def test_no_custom_prompt_uses_filesystem(self):
        user_id = uuid4()
        plugin = _make_plugin()
        engine = _make_engine()
        context = make_mail_context()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        system, user = await resolve_prompts(mock_db, user_id, plugin, engine, context)
        engine.render.assert_called_once()
        assert engine.render.call_args[0][0] == "prompts/labeling.j2"
        assert system == "file:prompts/labeling.j2"
        assert "JSON format" in user

    @pytest.mark.asyncio
    async def test_non_custom_prompt_uses_filesystem(self):
        """A Prompt row exists but is_custom is False -> use filesystem."""
        user_id = uuid4()
        plugin = _make_plugin()
        engine = _make_engine()
        context = make_mail_context()

        prompt_row = MagicMock()
        prompt_row.is_custom = False

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = prompt_row
        mock_db.execute.return_value = mock_result

        system, _user = await resolve_prompts(mock_db, user_id, plugin, engine, context)
        engine.render.assert_called_once()
        assert system == "file:prompts/labeling.j2"

    @pytest.mark.asyncio
    async def test_timezone_handling(self):
        """Verify that a valid timezone is applied without error."""
        user_id = uuid4()
        plugin = _make_plugin()
        engine = _make_engine()
        context = make_mail_context()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        system, _user = await resolve_prompts(mock_db, user_id, plugin, engine, context, timezone="Europe/Berlin")
        assert system is not None

    @pytest.mark.asyncio
    async def test_invalid_timezone_falls_back_to_utc(self):
        user_id = uuid4()
        plugin = _make_plugin()
        engine = _make_engine()
        context = make_mail_context()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        # Should not raise
        system, _user = await resolve_prompts(mock_db, user_id, plugin, engine, context, timezone="Invalid/Zone")
        assert system is not None
