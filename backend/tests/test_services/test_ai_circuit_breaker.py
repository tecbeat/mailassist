"""Tests for AI circuit breaker session safety.

Verifies that check_ai_circuit_breaker uses flush() instead of commit(),
preventing unintended finalization of outer transactions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.ai import check_ai_circuit_breaker


def _make_provider(*, consecutive_errors: int = 5, is_paused: bool = False):
    """Create a mock AIProvider."""
    provider = MagicMock()
    provider.id = uuid4()
    provider.name = "test-provider"
    provider.consecutive_errors = consecutive_errors
    provider.is_paused = is_paused
    provider.paused_reason = None
    provider.paused_at = None
    return provider


def _make_db(provider):
    """Create a mock AsyncSession that returns the given provider."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = provider

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_circuit_breaker_uses_flush_not_commit():
    """When circuit breaker trips, it must flush() — never commit()."""
    provider = _make_provider(consecutive_errors=5, is_paused=False)
    db = _make_db(provider)

    tripped = await check_ai_circuit_breaker(db, provider.id, max_errors=5)

    assert tripped is True
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_circuit_breaker_no_trip_below_threshold():
    """Below threshold, circuit breaker should not trip or flush."""
    provider = _make_provider(consecutive_errors=3, is_paused=False)
    db = _make_db(provider)

    tripped = await check_ai_circuit_breaker(db, provider.id, max_errors=5)

    assert tripped is False
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_circuit_breaker_already_paused():
    """Already paused provider should not trip again."""
    provider = _make_provider(consecutive_errors=10, is_paused=True)
    db = _make_db(provider)

    tripped = await check_ai_circuit_breaker(db, provider.id, max_errors=5)

    assert tripped is False
    db.flush.assert_not_awaited()
    db.commit.assert_not_awaited()
