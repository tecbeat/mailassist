"""Tests for _insert_tracked_batch in mail_poller.

Verifies that uidvalidity and first_seen fields are correctly included
in bulk-inserted rows, and that ON CONFLICT DO NOTHING handles duplicates.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.mail_poller import _insert_tracked_batch


def _make_db(rowcounts: list[int]) -> AsyncMock:
    """Return a mock AsyncSession whose execute returns the given rowcounts."""
    db = AsyncMock()
    results = []
    for rc in rowcounts:
        r = MagicMock()
        r.rowcount = rc
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    db.flush = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# uidvalidity and first_seen fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.workers.mail_poller.pg_insert")
async def test_insert_includes_uidvalidity(mock_pg_insert: MagicMock) -> None:
    """Each row must contain the uidvalidity value passed to the function."""
    db = _make_db([2])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    uids = ["1", "2"]
    envelopes: dict[str, tuple[str | None, str | None, datetime | None]] = {}

    await _insert_tracked_batch(
        db,
        uuid4(),
        uuid4(),
        uids,
        envelopes,
        uidvalidity=12345,
    )

    call_args = mock_pg_insert.return_value.values.call_args[0][0]
    for row in call_args:
        assert row["uidvalidity"] == 12345


@pytest.mark.asyncio
@patch("app.workers.mail_poller.pg_insert")
async def test_insert_includes_first_seen_uid(mock_pg_insert: MagicMock) -> None:
    """first_seen_uid must equal the UID at discovery time."""
    db = _make_db([3])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    uids = ["10", "20", "30"]
    envelopes: dict[str, tuple[str | None, str | None, datetime | None]] = {}

    await _insert_tracked_batch(
        db,
        uuid4(),
        uuid4(),
        uids,
        envelopes,
    )

    call_args = mock_pg_insert.return_value.values.call_args[0][0]
    for row in call_args:
        assert row["first_seen_uid"] == row["mail_uid"]


@pytest.mark.asyncio
@patch("app.workers.mail_poller.pg_insert")
async def test_insert_includes_first_seen_folder(mock_pg_insert: MagicMock) -> None:
    """first_seen_folder must equal current_folder at discovery time."""
    db = _make_db([1])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    uids = ["5"]
    envelopes: dict[str, tuple[str | None, str | None, datetime | None]] = {}

    await _insert_tracked_batch(
        db,
        uuid4(),
        uuid4(),
        uids,
        envelopes,
        current_folder="Sent",
    )

    call_args = mock_pg_insert.return_value.values.call_args[0][0]
    assert call_args[0]["first_seen_folder"] == "Sent"
    assert call_args[0]["current_folder"] == "Sent"


@pytest.mark.asyncio
@patch("app.workers.mail_poller.pg_insert")
async def test_insert_uses_envelope_data(mock_pg_insert: MagicMock) -> None:
    """Subject, sender, received_at from envelopes are included in rows."""
    db = _make_db([2])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    now = datetime.now(UTC)
    uids = ["1", "2"]
    envelopes = {
        "1": ("Subject A", "alice@x.com", now),
        "2": (None, None, None),
    }

    await _insert_tracked_batch(
        db,
        uuid4(),
        uuid4(),
        uids,
        envelopes,
    )

    call_args = mock_pg_insert.return_value.values.call_args[0][0]
    assert call_args[0]["subject"] == "Subject A"
    assert call_args[0]["sender"] == "alice@x.com"
    assert call_args[0]["received_at"] is now
    assert call_args[1]["subject"] is None
    assert call_args[1]["sender"] is None


@pytest.mark.asyncio
@patch("app.workers.mail_poller.pg_insert")
async def test_insert_uidvalidity_none_when_not_provided(mock_pg_insert: MagicMock) -> None:
    """When uidvalidity is not passed, rows should have None."""
    db = _make_db([1])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    await _insert_tracked_batch(
        db,
        uuid4(),
        uuid4(),
        ["1"],
        {},
    )

    call_args = mock_pg_insert.return_value.values.call_args[0][0]
    assert call_args[0]["uidvalidity"] is None


# ---------------------------------------------------------------------------
# ON CONFLICT DO NOTHING and return value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.workers.mail_poller.pg_insert")
async def test_insert_returns_actual_inserted_count(mock_pg_insert: MagicMock) -> None:
    """Return value is rowcount (excludes conflicts)."""
    db = _make_db([3])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    result = await _insert_tracked_batch(
        db,
        uuid4(),
        uuid4(),
        ["1", "2", "3", "4", "5"],
        {},
    )

    assert result == 3  # only 3 actually inserted (2 were conflicts)


@pytest.mark.asyncio
async def test_insert_empty_uids_returns_zero() -> None:
    """Empty UID list returns 0 without any DB calls."""
    db = AsyncMock()
    result = await _insert_tracked_batch(
        db,
        uuid4(),
        uuid4(),
        [],
        {},
    )
    assert result == 0
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.workers.mail_poller.pg_insert")
async def test_insert_uses_on_conflict_do_nothing(mock_pg_insert: MagicMock) -> None:
    """The INSERT statement must use ON CONFLICT DO NOTHING."""
    db = _make_db([1])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    await _insert_tracked_batch(
        db,
        uuid4(),
        uuid4(),
        ["1"],
        {},
    )

    mock_stmt.on_conflict_do_nothing.assert_called_once_with(constraint="uq_tracked_email_account_uid")
