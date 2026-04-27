"""Tests for _persist context manager session cleanup.

Verifies that the refactored _persist properly closes DB sessions
in all code paths, preventing connection leaks.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.persistence import _persist


@pytest.mark.asyncio
async def test_persist_own_session_closes_properly():
    """When own_session=True, the session must be committed and closed."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.persistence.get_session_ctx", return_value=mock_ctx):
        async with _persist(own_session=True, db=None) as session:
            assert session is mock_session

    mock_ctx.__aenter__.assert_awaited_once()
    mock_ctx.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_own_session_closes_on_error():
    """When own_session=True and body raises, session context must still exit."""
    mock_session = AsyncMock()

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.persistence.get_session_ctx", return_value=mock_ctx):
        with pytest.raises(RuntimeError, match="test error"):
            async with _persist(own_session=True, db=None) as session:
                raise RuntimeError("test error")

    mock_ctx.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_external_session_flushes():
    """When db is provided, it should flush but not commit."""
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()

    async with _persist(own_session=False, db=mock_db) as session:
        assert session is mock_db

    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_no_session_raises():
    """When own_session=False and db=None, ValueError is raised."""
    with pytest.raises(ValueError, match="Either own_session=True or db must be provided"):
        async with _persist(own_session=False, db=None):
            pass
