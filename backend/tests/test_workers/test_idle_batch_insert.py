"""Tests for _insert_tracked_uids batching in idle_monitor.

Verifies that bulk INSERTs are split into sub-batches to stay under
PostgreSQL's 32,767 bind-parameter limit (issue #129).
"""

from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.idle_monitor import _insert_tracked_uids

_BATCH_SIZE = 2000


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


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.pg_insert")
async def test_insert_small_batch_single_execute(mock_pg_insert: MagicMock) -> None:
    """UIDs <= 2000 should produce exactly one db.execute call."""
    uids = [str(i) for i in range(500)]
    db = _make_db([500])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    result = await _insert_tracked_uids(db, uuid4(), uuid4(), uids)

    assert result == 500
    assert db.execute.await_count == 1


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.pg_insert")
async def test_insert_large_batch_splits_into_multiple_executes(mock_pg_insert: MagicMock) -> None:
    """>2000 UIDs must be split into multiple batches."""
    uids = [str(i) for i in range(4500)]
    expected_batches = math.ceil(len(uids) / _BATCH_SIZE)  # 3
    db = _make_db([2000, 2000, 500])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    result = await _insert_tracked_uids(db, uuid4(), uuid4(), uids)

    assert db.execute.await_count == expected_batches
    assert result == 4500


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.pg_insert")
async def test_insert_count_accumulated_across_batches_with_conflicts(mock_pg_insert: MagicMock) -> None:
    """Returned count must be the sum of rowcounts from all batches."""
    uids = [str(i) for i in range(3000)]
    # Simulate conflicts: first batch inserts 1800, second inserts 700
    db = _make_db([1800, 700])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    result = await _insert_tracked_uids(db, uuid4(), uuid4(), uids)

    assert result == 2500


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.pg_insert")
async def test_insert_empty_uids_no_execute(mock_pg_insert: MagicMock) -> None:
    """Empty UID list should not call db.execute at all."""
    db = _make_db([])

    result = await _insert_tracked_uids(db, uuid4(), uuid4(), [])

    assert result == 0
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.pg_insert")
async def test_insert_exact_boundary_single_batch(mock_pg_insert: MagicMock) -> None:
    """Exactly 2000 UIDs should produce one batch, not two."""
    uids = [str(i) for i in range(_BATCH_SIZE)]
    db = _make_db([2000])
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg_insert.return_value.values.return_value = mock_stmt

    result = await _insert_tracked_uids(db, uuid4(), uuid4(), uids)

    assert db.execute.await_count == 1
    assert result == 2000
