"""Coverage tests for scheduler.py — targeting uncovered lines.

Covers: schedule_pending_mails, schedule_now, _reset_stale_processing,
_user_has_healthy_provider edge cases, dedup/enqueue failures, and
mail-already-taken paths.
"""

from __future__ import annotations

from collections import namedtuple
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import TrackedEmailStatus
from app.models.user import ApprovalMode

QueuedRow = namedtuple(
    "QueuedRow",
    ["id", "user_id", "mail_account_id", "mail_uid", "current_folder"],
    defaults=["INBOX"],
)


def _scalar_result(value):
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _all_result(rows):
    r = MagicMock()
    r.all.return_value = rows
    return r


def _scalars_all_result(items):
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _scalar_one_none_result(value):
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


class _FakeTrackedEmail:
    def __init__(self, te_id, status=TrackedEmailStatus.QUEUED):
        self.id = te_id
        self.status = status


def _make_provider(user_id, *, is_paused=False, is_default=True):
    p = MagicMock()
    p.id = uuid4()
    p.user_id = user_id
    p.is_paused = is_paused
    p.is_default = is_default
    p.created_at = datetime.now(UTC)
    return p


def _make_user_settings(user_id, *, max_concurrent=5, plugin_provider_map=None, approval_mode_spam=ApprovalMode.AUTO):
    us = MagicMock()
    us.user_id = user_id
    us.plugin_provider_map = plugin_provider_map or {}
    us.max_concurrent_processing = max_concurrent
    us.approval_mode_spam = approval_mode_spam
    return us


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.worker_max_jobs = 10
    settings.scheduler_reserved_slots = 2
    settings.scheduler_max_batch = 100
    settings.scheduler_default_max_concurrent = 3
    settings.stale_job_threshold_seconds = 300
    with patch("app.workers.scheduler.get_settings", return_value=settings):
        yield settings


# ---------------------------------------------------------------------------
# Lines 67-71: schedule_pending_mails entry point
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_pending_mails_calls_reset_and_schedule(mock_settings):
    """schedule_pending_mails opens session, calls reset + schedule (lines 67-71)."""
    from app.workers.scheduler import schedule_pending_mails

    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    # Make _reset_stale_processing and _schedule no-ops via global_processing=max
    mock_db.execute = AsyncMock(
        side_effect=[
            _scalar_result(0),  # _reset_stale_processing: result with no rows
            _scalar_result(8),  # _schedule: global_processing at capacity
        ]
    )
    # _reset_stale_processing returns no stale rows
    first_result = MagicMock()
    first_result.scalars.return_value.all.return_value = []
    # _schedule: at capacity
    second_result = _scalar_result(8)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return first_result
        return second_result

    mock_db.execute = AsyncMock(side_effect=_side_effect)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_session():
        yield mock_db

    arq = AsyncMock()
    ctx = {"redis": arq}

    with patch("app.workers.scheduler.get_session_ctx", _fake_session):
        await schedule_pending_mails(ctx)


# ---------------------------------------------------------------------------
# Lines 76-77: schedule_now
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_now_calls_schedule(mock_settings):
    """schedule_now opens session and calls _schedule (lines 76-77)."""
    from app.workers.scheduler import schedule_now

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=_scalar_result(8))  # at capacity
    mock_db.commit = AsyncMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_session():
        yield mock_db

    arq = AsyncMock()

    with patch("app.workers.scheduler.get_session_ctx", _fake_session):
        await schedule_now(arq)


# ---------------------------------------------------------------------------
# Lines 87-107: _reset_stale_processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_stale_processing_resets_stuck_mails(mock_settings):
    """_reset_stale_processing resets stale PROCESSING mails (lines 87-107)."""
    from app.workers.scheduler import _reset_stale_processing

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [uuid4(), uuid4()]
    mock_db.execute = AsyncMock(return_value=result)
    mock_db.commit = AsyncMock()

    await _reset_stale_processing(mock_db)

    mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_reset_stale_processing_no_stale_mails(mock_settings):
    """_reset_stale_processing does nothing when no stale mails (line 105 false branch)."""
    from app.workers.scheduler import _reset_stale_processing

    mock_db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=result)
    mock_db.commit = AsyncMock()

    await _reset_stale_processing(mock_db)

    mock_db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Lines 170: no queued rows early return
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_no_queued_rows_returns_early(mock_settings):
    """_schedule returns early when no queued rows (line 170)."""
    from app.workers.scheduler import _schedule

    mock_db = AsyncMock()
    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result([])  # no queued rows
        return _all_result([])

    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    arq = AsyncMock()

    await _schedule(mock_db, arq)
    arq.enqueue_job.assert_not_called()


# ---------------------------------------------------------------------------
# Lines 227-228, 234, 237, 243, 247: _user_has_healthy_provider internals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_no_settings_skipped(mock_settings):
    """User with no UserSettings row is skipped (line 214-215)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]
    provider = _make_provider(user_id)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([provider])
        if idx == 4:
            return _scalars_all_result([])  # no UserSettings
        if idx == 5:
            return _all_result([])
        return _scalar_one_none_result(None)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    arq = AsyncMock()

    await _schedule(mock_db, arq)
    arq.enqueue_job.assert_not_called()


@pytest.mark.asyncio
async def test_user_default_provider_fallback_non_default(mock_settings):
    """Provider that is not is_default but not paused is used as fallback (lines 227-228)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]

    # Provider is active but not is_default
    provider = _make_provider(user_id, is_default=False)
    us = _make_user_settings(user_id)

    tracked = _FakeTrackedEmail(queued[0].id)
    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([provider])
        if idx == 4:
            return _scalars_all_result([us])
        if idx == 5:
            return _all_result([])
        return _scalar_one_none_result(tracked)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    arq = AsyncMock()
    arq.enqueue_job = AsyncMock(return_value=MagicMock(job_id="j1"))

    await _schedule(mock_db, arq)
    assert arq.enqueue_job.call_count == 1


@pytest.mark.asyncio
async def test_user_all_plugins_disabled_skipped(mock_settings):
    """User with all plugins DISABLED is skipped (line 237 + has_any_enabled=False → line 249)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]

    provider = _make_provider(user_id)
    us = _make_user_settings(user_id, approval_mode_spam=ApprovalMode.DISABLED)
    # Make ALL approval columns return DISABLED
    for attr in [
        "approval_mode_spam",
        "approval_mode_labeling",
        "approval_mode_smart_folder",
        "approval_mode_newsletter",
        "approval_mode_otp",
        "approval_mode_coupon",
        "approval_mode_calendar",
        "approval_mode_auto_reply",
        "approval_mode_summary",
        "approval_mode_contacts",
    ]:
        setattr(us, attr, ApprovalMode.DISABLED)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([provider])
        if idx == 4:
            return _scalars_all_result([us])
        if idx == 5:
            return _all_result([])
        return _scalar_one_none_result(None)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    arq = AsyncMock()

    await _schedule(mock_db, arq)
    arq.enqueue_job.assert_not_called()


@pytest.mark.asyncio
async def test_user_assigned_provider_used_over_default(mock_settings):
    """Plugin with explicit provider in plugin_provider_map uses it (line 242-243)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]

    default_provider = _make_provider(user_id, is_default=True)
    assigned_provider = _make_provider(user_id, is_default=False)

    us = _make_user_settings(
        user_id,
        plugin_provider_map={"spam_detection": str(assigned_provider.id)},
    )

    tracked = _FakeTrackedEmail(queued[0].id)
    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([default_provider, assigned_provider])
        if idx == 4:
            return _scalars_all_result([us])
        if idx == 5:
            return _all_result([])
        return _scalar_one_none_result(tracked)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()
    arq = AsyncMock()
    arq.enqueue_job = AsyncMock(return_value=MagicMock(job_id="j1"))

    await _schedule(mock_db, arq)
    assert arq.enqueue_job.call_count == 1


@pytest.mark.asyncio
async def test_user_enabled_plugin_paused_provider_skipped(mock_settings):
    """Enabled plugin with paused assigned provider blocks user (line 246-247)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]

    paused_provider = _make_provider(user_id, is_paused=True, is_default=True)
    us = _make_user_settings(user_id)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([paused_provider])
        if idx == 4:
            return _scalars_all_result([us])
        if idx == 5:
            return _all_result([])
        return _scalar_one_none_result(None)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    arq = AsyncMock()

    await _schedule(mock_db, arq)
    arq.enqueue_job.assert_not_called()


# ---------------------------------------------------------------------------
# Lines 350-355: mail already taken (scalar_one_or_none returns None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mail_already_taken_skipped(mock_settings):
    """Mail picked up by another scheduler returns None (lines 350-355)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]

    provider = _make_provider(user_id)
    us = _make_user_settings(user_id)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([provider])
        if idx == 4:
            return _scalars_all_result([us])
        if idx == 5:
            return _all_result([])
        return _scalar_one_none_result(None)  # already taken

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    arq = AsyncMock()

    await _schedule(mock_db, arq)
    arq.enqueue_job.assert_not_called()


# ---------------------------------------------------------------------------
# Lines 358-365: status update exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_update_exception_increments_failed(mock_settings):
    """Exception during QUEUED->PROCESSING transition (lines 358-365)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]

    provider = _make_provider(user_id)
    us = _make_user_settings(user_id)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([provider])
        if idx == 4:
            return _scalars_all_result([us])
        if idx == 5:
            return _all_result([])
        raise RuntimeError("DB error")

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    arq = AsyncMock()

    await _schedule(mock_db, arq)
    arq.enqueue_job.assert_not_called()
    mock_db.commit.assert_called_once()  # final commit still happens


# ---------------------------------------------------------------------------
# Lines 382-401: dedup hit (enqueue_job returns None) + key clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_hit_clears_key_and_reverts(mock_settings):
    """enqueue_job returning None triggers dedup key clear (lines 382-401)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]

    provider = _make_provider(user_id)
    us = _make_user_settings(user_id)
    tracked = _FakeTrackedEmail(queued[0].id)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([provider])
        if idx == 4:
            return _scalars_all_result([us])
        if idx == 5:
            return _all_result([])
        return _scalar_one_none_result(tracked)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()

    arq = AsyncMock()
    arq.enqueue_job = AsyncMock(return_value=None)  # dedup hit
    arq.delete = AsyncMock()

    await _schedule(mock_db, arq)

    arq.delete.assert_called_once()
    assert tracked.status == TrackedEmailStatus.QUEUED


@pytest.mark.asyncio
async def test_dedup_key_clear_failure_handled(mock_settings):
    """Exception during dedup key clear is caught (lines 392-396)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]

    provider = _make_provider(user_id)
    us = _make_user_settings(user_id)
    tracked = _FakeTrackedEmail(queued[0].id)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([provider])
        if idx == 4:
            return _scalars_all_result([us])
        if idx == 5:
            return _all_result([])
        return _scalar_one_none_result(tracked)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()

    arq = AsyncMock()
    arq.enqueue_job = AsyncMock(return_value=None)
    arq.delete = AsyncMock(side_effect=RuntimeError("redis error"))

    await _schedule(mock_db, arq)
    assert tracked.status == TrackedEmailStatus.QUEUED


# ---------------------------------------------------------------------------
# Lines 405-418: enqueue_job raises exception + revert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enqueue_exception_reverts_to_queued(mock_settings):
    """Exception during enqueue_job reverts status (lines 405-418)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]

    provider = _make_provider(user_id)
    us = _make_user_settings(user_id)
    tracked = _FakeTrackedEmail(queued[0].id)

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([provider])
        if idx == 4:
            return _scalars_all_result([us])
        if idx == 5:
            return _all_result([])
        return _scalar_one_none_result(tracked)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock()

    arq = AsyncMock()
    arq.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))

    await _schedule(mock_db, arq)
    assert tracked.status == TrackedEmailStatus.QUEUED


@pytest.mark.asyncio
async def test_enqueue_exception_revert_also_fails(mock_settings):
    """Exception during status revert after enqueue failure (lines 414-418)."""
    from app.workers.scheduler import _schedule

    user_id = uuid4()
    account_id = uuid4()
    queued = [QueuedRow(uuid4(), user_id, account_id, "uid1")]

    provider = _make_provider(user_id)
    us = _make_user_settings(user_id)
    tracked = _FakeTrackedEmail(queued[0].id)

    call_count = 0
    flush_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1
        if idx == 0:
            return _scalar_result(0)
        if idx == 1:
            return _all_result(queued)
        if idx == 2:
            return _all_result([(account_id,)])
        if idx == 3:
            return _scalars_all_result([provider])
        if idx == 4:
            return _scalars_all_result([us])
        if idx == 5:
            return _all_result([])
        return _scalar_one_none_result(tracked)

    async def _flush_side_effect():
        nonlocal flush_count
        flush_count += 1
        if flush_count == 1:
            return  # first flush (QUEUED->PROCESSING) succeeds
        raise RuntimeError("flush failed")  # revert flush fails

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_side_effect)
    mock_db.commit = AsyncMock()
    mock_db.flush = AsyncMock(side_effect=_flush_side_effect)

    arq = AsyncMock()
    arq.enqueue_job = AsyncMock(side_effect=RuntimeError("redis down"))

    # Should not raise — the double exception is caught
    await _schedule(mock_db, arq)
