"""Tests for _persist context manager session cleanup.

Verifies that the refactored _persist properly closes DB sessions
in all code paths, preventing connection leaks.  Also verifies that
save_calendar_event expunges the record from the session before calling
_sync_event_to_caldav, preventing DetachedInstanceError.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.persistence import _persist, save_calendar_event


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


@pytest.mark.asyncio
async def test_save_calendar_event_flushes_and_expunges_before_caldav_sync():
    """flush+expunge must happen inside _persist before _sync_event_to_caldav.

    Regression test for DetachedInstanceError: record attributes must remain
    accessible after the session closes (i.e. after expunge, not expire).
    """
    call_order: list[str] = []
    captured_record: list[object] = []

    mock_session = AsyncMock()

    async def track_flush() -> None:
        call_order.append("flush")

    def track_expunge(obj: object) -> None:
        call_order.append("expunge")
        captured_record.append(obj)

    mock_session.flush = AsyncMock(side_effect=track_flush)
    mock_session.expunge = MagicMock(side_effect=track_expunge)

    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)

    sync_calls: list[object] = []

    async def fake_sync(record: object) -> None:
        call_order.append("sync")
        sync_calls.append(record)

    with (
        patch("app.services.persistence.get_session_ctx", return_value=mock_ctx),
        patch("app.services.persistence._sync_event_to_caldav", side_effect=fake_sync),
    ):
        await save_calendar_event(
            user_id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            mail_uid="test-uid-123",
            mail_subject="Team Meeting Invite",
            has_event=True,
            title="Team Meeting",
            start=datetime(2024, 6, 1, 10, 0, tzinfo=UTC),
            end=datetime(2024, 6, 1, 11, 0, tzinfo=UTC),
            own_session=True,
        )

    # flush must precede expunge; both must precede the CalDAV sync
    assert call_order == ["flush", "expunge", "sync"], (
        f"Expected ['flush', 'expunge', 'sync'], got {call_order}"
    )

    # _sync_event_to_caldav receives the same record object that was expunged
    assert len(sync_calls) == 1
    assert sync_calls[0] is captured_record[0]
