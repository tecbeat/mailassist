"""Tests for token usage TTL behaviour.

Verifies that the TTL on token-usage keys is only set once (on creation)
and not reset on every subsequent increment.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


@pytest.mark.asyncio
async def test_token_ttl_not_reset_on_second_increment(
    mock_cache_client: MagicMock,
    fake_valkey,
) -> None:
    """TTL should be set on first call but not overwritten on second call."""
    from app.services.ai import _track_tokens

    settings = MagicMock()
    settings.ai_token_usage_ttl_days = 30

    with patch("app.services.ai.get_settings", return_value=settings):
        await _track_tokens("user-1", 100)

    # First call should have set the TTL
    ttl_keys = getattr(fake_valkey, "_ttls", {})
    assert len(ttl_keys) == 1
    key = list(ttl_keys.keys())[0]
    first_ttl = ttl_keys[key]
    assert first_ttl == 30 * 86400

    # Manually change TTL to simulate time passing
    fake_valkey._ttls[key] = 12345

    with patch("app.services.ai.get_settings", return_value=settings):
        await _track_tokens("user-1", 50)

    # TTL should NOT have been reset (nx=True prevents it)
    assert fake_valkey._ttls[key] == 12345


@pytest.mark.asyncio
async def test_token_zero_tokens_skipped(mock_cache_client: MagicMock, fake_valkey) -> None:
    """Zero or negative token counts should be ignored."""
    from app.services.ai import _track_tokens

    await _track_tokens("user-1", 0)
    await _track_tokens("user-1", -5)

    assert len(fake_valkey._store) == 0
