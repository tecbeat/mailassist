"""Tests for AI provider resolution logic (Issue #42).

Verifies that get_default_provider correctly filters by is_paused and
prefers is_default providers, and that create/update wiring is correct.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# get_default_provider resolution tests
# ---------------------------------------------------------------------------


class TestGetDefaultProvider:
    """get_default_provider selects the correct provider."""

    @pytest.mark.asyncio
    async def test_returns_active_default_provider(self):
        """An active provider with is_default=True is returned first."""
        user_id = uuid4()

        provider_default = MagicMock()
        provider_default.is_paused = False
        provider_default.is_default = True

        # Mock the DB to return the default provider on first query
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = provider_default

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.services.provider_resolver import get_default_provider

        result = await get_default_provider(mock_db, user_id)
        assert result is provider_default

    @pytest.mark.asyncio
    async def test_falls_back_to_oldest_active_when_no_default(self):
        """When no is_default=True provider exists, the oldest active is used."""
        user_id = uuid4()

        provider_oldest = MagicMock()
        provider_oldest.is_paused = False
        provider_oldest.is_default = False

        # First query (is_default=True): returns None
        mock_result_empty = MagicMock()
        mock_result_empty.scalar_one_or_none.return_value = None

        # Second query (oldest active): returns provider_oldest
        mock_result_fallback = MagicMock()
        mock_result_fallback.scalar_one_or_none.return_value = provider_oldest

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result_empty, mock_result_fallback],
        )

        from app.services.provider_resolver import get_default_provider

        result = await get_default_provider(mock_db, user_id)
        assert result is provider_oldest

    @pytest.mark.asyncio
    async def test_returns_none_when_all_inactive(self):
        """When all providers are inactive (circuit-broken), returns None."""
        user_id = uuid4()

        # Both queries return None
        mock_result_empty = MagicMock()
        mock_result_empty.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result_empty)

        from app.services.provider_resolver import get_default_provider

        result = await get_default_provider(mock_db, user_id)
        assert result is None

    @pytest.mark.asyncio
    async def test_skips_inactive_default_provider(self):
        """An inactive provider with is_default=True is NOT returned."""
        user_id = uuid4()

        provider_active = MagicMock()
        provider_active.is_paused = False
        provider_active.is_default = False

        # First query (is_default=True + is_paused=False): returns None
        # because the default provider is inactive
        mock_result_no_default = MagicMock()
        mock_result_no_default.scalar_one_or_none.return_value = None

        # Second query (oldest active): returns the non-default active one
        mock_result_fallback = MagicMock()
        mock_result_fallback.scalar_one_or_none.return_value = provider_active

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(
            side_effect=[mock_result_no_default, mock_result_fallback],
        )

        from app.services.provider_resolver import get_default_provider

        result = await get_default_provider(mock_db, user_id)
        assert result is provider_active


# ---------------------------------------------------------------------------
# resolve_plugin_provider tests
# ---------------------------------------------------------------------------


class TestResolvePluginProvider:
    """resolve_plugin_provider picks the correct provider per plugin."""

    def test_uses_assigned_provider(self):
        """Plugin-specific assignment takes precedence over default."""
        from app.services.provider_resolver import resolve_plugin_provider

        provider_a = MagicMock()
        provider_b = MagicMock()
        providers = {"id-a": provider_a, "id-b": provider_b}
        plugin_map = {"email_summary": "id-b"}

        result = resolve_plugin_provider(
            "email_summary", plugin_map, providers, provider_a,
        )
        assert result is provider_b

    def test_falls_back_to_default(self):
        """When no assignment exists, the default provider is returned."""
        from app.services.provider_resolver import resolve_plugin_provider

        default = MagicMock()
        result = resolve_plugin_provider("labeling", {}, {}, default)
        assert result is default

    def test_returns_none_when_no_default(self):
        """When no assignment and no default, returns None."""
        from app.services.provider_resolver import resolve_plugin_provider

        result = resolve_plugin_provider("labeling", {}, {}, None)
        assert result is None
