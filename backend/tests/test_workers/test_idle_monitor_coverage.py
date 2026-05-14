"""Tests for app.workers.idle_monitor — IDLE task lifecycle and helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers import idle_monitor
from app.workers.idle_monitor import (
    _insert_tracked_uids,
    _search_and_insert_new,
    check_idle_health,
    is_idle_active,
    start_idle_for_account,
    stop_all_idle,
    stop_idle_for_account,
)


@pytest.fixture(autouse=True)
def _clear_idle_tasks():
    """Ensure the global _idle_tasks dict is clean for every test."""
    idle_monitor._idle_tasks.clear()
    yield
    idle_monitor._idle_tasks.clear()


# ---------------------------------------------------------------------------
# start_idle_for_account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.workers.idle_monitor._idle_loop", new_callable=AsyncMock)
async def test_start_idle_for_account_creates_task(mock_loop: AsyncMock) -> None:
    account = MagicMock()
    account.id = uuid4()

    await start_idle_for_account(account)

    assert str(account.id) in idle_monitor._idle_tasks


@pytest.mark.asyncio
@patch("app.workers.idle_monitor._idle_loop", new_callable=AsyncMock)
async def test_start_idle_for_account_skips_if_already_running(mock_loop: AsyncMock) -> None:
    account = MagicMock()
    account.id = uuid4()
    aid = str(account.id)

    # Simulate already-running task
    task = MagicMock(spec=asyncio.Task)
    task.done.return_value = False
    idle_monitor._idle_tasks[aid] = task

    await start_idle_for_account(account)

    # Original task should still be there, not replaced
    assert idle_monitor._idle_tasks[aid] is task


# ---------------------------------------------------------------------------
# is_idle_active
# ---------------------------------------------------------------------------


def test_is_idle_active_running_task_returns_true() -> None:
    task = MagicMock(spec=asyncio.Task)
    task.done.return_value = False
    idle_monitor._idle_tasks["acc1"] = task
    assert is_idle_active("acc1") is True


def test_is_idle_active_no_task_returns_false() -> None:
    assert is_idle_active("nonexistent") is False


def test_is_idle_active_finished_task_returns_false() -> None:
    task = MagicMock(spec=asyncio.Task)
    task.done.return_value = True
    idle_monitor._idle_tasks["acc1"] = task
    assert is_idle_active("acc1") is False


# ---------------------------------------------------------------------------
# stop_idle_for_account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_idle_for_account_cancels_running_task() -> None:
    aid = "acc-stop"

    # Create a real asyncio task that we can cancel
    async def _never_finish():
        await asyncio.sleep(999)

    task = asyncio.create_task(_never_finish())
    idle_monitor._idle_tasks[aid] = task

    await stop_idle_for_account(aid)

    assert task.cancelled()
    assert aid not in idle_monitor._idle_tasks


@pytest.mark.asyncio
async def test_stop_idle_for_account_noop_if_not_present() -> None:
    await stop_idle_for_account("missing")  # should not raise


# ---------------------------------------------------------------------------
# stop_all_idle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_all_idle_cancels_all_tasks() -> None:
    async def _never_finish():
        await asyncio.sleep(999)

    for i in range(3):
        task = asyncio.create_task(_never_finish())
        idle_monitor._idle_tasks[f"acc-{i}"] = task

    await stop_all_idle()

    assert len(idle_monitor._idle_tasks) == 0


# ---------------------------------------------------------------------------
# check_idle_health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_idle_health_no_dead_tasks_logs_ok() -> None:
    task = MagicMock(spec=asyncio.Task)
    task.done.return_value = False
    idle_monitor._idle_tasks["healthy"] = task

    await check_idle_health()

    assert "healthy" in idle_monitor._idle_tasks


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.get_session_ctx")
@patch("app.workers.idle_monitor.start_idle_for_account", new_callable=AsyncMock)
async def test_check_idle_health_restarts_crashed_task(
    mock_start: AsyncMock,
    mock_session_ctx: MagicMock,
) -> None:
    aid = str(uuid4())
    task = MagicMock(spec=asyncio.Task)
    task.done.return_value = True
    task.cancelled.return_value = False
    task.exception.return_value = RuntimeError("boom")
    idle_monitor._idle_tasks[aid] = task

    # Mock DB returning the account
    mock_account = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_account
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_db)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_session_ctx.return_value = cm

    await check_idle_health()

    mock_start.assert_awaited_once_with(mock_account)
    assert aid not in idle_monitor._idle_tasks  # cleaned up before restart


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.get_session_ctx")
async def test_check_idle_health_skips_paused_account(
    mock_session_ctx: MagicMock,
) -> None:
    aid = str(uuid4())
    task = MagicMock(spec=asyncio.Task)
    task.done.return_value = True
    task.cancelled.return_value = False
    task.exception.return_value = None
    idle_monitor._idle_tasks[aid] = task

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # account gone/paused
    mock_db.execute.return_value = mock_result

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_db)
    cm.__aexit__ = AsyncMock(return_value=False)
    mock_session_ctx.return_value = cm

    await check_idle_health()

    assert aid not in idle_monitor._idle_tasks


# ---------------------------------------------------------------------------
# _search_and_insert_new
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.update_account_sync_status", new_callable=AsyncMock)
@patch("app.workers.idle_monitor.get_session_ctx")
@patch("app.workers.idle_monitor.search_uids", new_callable=AsyncMock)
async def test_search_and_insert_new_inserts_new_uids(
    mock_search: AsyncMock,
    mock_session_ctx: MagicMock,
    mock_update_status: AsyncMock,
) -> None:
    conn = MagicMock()
    aid = str(uuid4())
    uid = str(uuid4())

    mock_search.return_value = (["100", "101"], 12345)

    # First session call: uid diff query returns one new uid
    mock_diff_result = MagicMock()
    mock_diff_result.all.return_value = [("101",)]
    mock_diff_db = AsyncMock()
    mock_diff_db.execute.return_value = mock_diff_result

    # Second session call: insert
    mock_insert_result = MagicMock()
    mock_insert_result.rowcount = 1
    mock_insert_db = AsyncMock()
    mock_insert_db.execute.return_value = mock_insert_result
    mock_insert_db.flush = AsyncMock()

    # Third session call: update_account_sync_status
    mock_status_db = AsyncMock()

    session_cms = []
    for db in [mock_diff_db, mock_insert_db, mock_status_db]:
        cm = AsyncMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)
        session_cms.append(cm)

    mock_session_ctx.side_effect = session_cms

    with patch("app.workers.idle_monitor.pg_insert") as mock_pg:
        mock_stmt = MagicMock()
        mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
        mock_pg.return_value.values.return_value = mock_stmt

        result = await _search_and_insert_new(conn, aid, uid)

    assert result == 1


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.search_uids", new_callable=AsyncMock)
async def test_search_and_insert_new_search_fails_returns_zero(
    mock_search: AsyncMock,
) -> None:
    mock_search.side_effect = RuntimeError("IMAP fail")
    conn = MagicMock()

    result = await _search_and_insert_new(conn, "a", "u")

    assert result == 0


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.search_uids", new_callable=AsyncMock)
async def test_search_and_insert_new_empty_inbox_returns_zero(
    mock_search: AsyncMock,
) -> None:
    mock_search.return_value = ([], None)
    conn = MagicMock()

    result = await _search_and_insert_new(conn, "a", "u")

    assert result == 0


# ---------------------------------------------------------------------------
# _insert_tracked_uids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.pg_insert")
async def test_insert_tracked_uids_empty_list_returns_zero(mock_pg: MagicMock) -> None:
    db = AsyncMock()
    result = await _insert_tracked_uids(db, uuid4(), uuid4(), [])
    assert result == 0
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.workers.idle_monitor.pg_insert")
async def test_insert_tracked_uids_returns_rowcount(mock_pg: MagicMock) -> None:
    mock_stmt = MagicMock()
    mock_stmt.on_conflict_do_nothing.return_value = mock_stmt
    mock_pg.return_value.values.return_value = mock_stmt

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 3
    db.execute.return_value = mock_result
    db.flush = AsyncMock()

    result = await _insert_tracked_uids(db, uuid4(), uuid4(), ["1", "2", "3"])
    assert result == 3
