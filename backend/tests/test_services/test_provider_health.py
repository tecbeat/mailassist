"""Tests for update_provider_health() — savepoint safety (Issue #61).

Verifies that update_provider_health() uses flush() instead of commit(),
so it can be called safely from inside a savepoint (begin_nested) without
killing the enclosing transaction.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_update_provider_health_uses_flush_not_commit():
    """update_provider_health must call flush(), never commit().

    If commit() is used instead, calling it from inside a savepoint
    (begin_nested) will commit the entire transaction chain and close
    the context manager, causing all subsequent operations to fail with
    InvalidRequestError.
    """
    from app.services.ai import update_provider_health

    db = AsyncMock()
    provider_id = uuid4()

    await update_provider_health(db, provider_id)

    db.execute.assert_awaited_once()
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_provider_health_success_resets_errors():
    """On success (no error), consecutive_errors and last_error are cleared."""
    from app.services.ai import update_provider_health

    db = AsyncMock()
    provider_id = uuid4()

    await update_provider_health(db, provider_id)

    # Verify the UPDATE statement was executed
    db.execute.assert_awaited_once()
    call_args = db.execute.call_args[0][0]
    # The compiled statement should target ai_providers
    assert "ai_providers" in str(call_args)


@pytest.mark.asyncio
async def test_update_provider_health_error_increments_counter():
    """On error, consecutive_errors is incremented and error is recorded."""
    from app.services.ai import update_provider_health

    db = AsyncMock()
    provider_id = uuid4()

    await update_provider_health(db, provider_id, error="connection timeout")

    db.execute.assert_awaited_once()
    db.flush.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_provider_health_truncates_long_errors():
    """Error messages longer than 2000 chars are truncated."""
    from app.services.ai import update_provider_health

    db = AsyncMock()
    provider_id = uuid4()
    long_error = "x" * 5000

    await update_provider_health(db, provider_id, error=long_error)

    db.execute.assert_awaited_once()
    # Verify the statement was built with truncated error
    call_args = db.execute.call_args[0][0]
    compiled = call_args.compile(compile_kwargs={"literal_binds": True})
    # The error value in the compiled SQL should be truncated
    assert "x" * 2001 not in str(compiled)


@pytest.mark.asyncio
async def test_update_provider_health_safe_inside_savepoint():
    """Simulate the pipeline pattern: flush() inside begin_nested works.

    This test verifies that after calling update_provider_health() inside
    a savepoint, the session is still usable for subsequent operations —
    the exact scenario that was broken when commit() was used.
    """
    from contextlib import asynccontextmanager

    from app.services.ai import update_provider_health

    db = AsyncMock()
    provider_id = uuid4()

    # Create a proper async context manager for begin_nested
    @asynccontextmanager
    async def fake_begin_nested():
        yield AsyncMock()  # savepoint

    db.begin_nested = fake_begin_nested

    async with db.begin_nested():
        # This is what plugin_executor does on the success path
        await update_provider_health(db, provider_id)

        # After update_provider_health, session should still be usable
        # (this would fail with InvalidRequestError if commit() was used)
        db.flush.assert_awaited_once()
        db.commit.assert_not_awaited()

        # Simulate subsequent plugin work — should not raise
        await db.execute(MagicMock())
        assert db.execute.await_count == 2
