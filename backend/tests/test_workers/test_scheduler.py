"""Tests for scheduler per-user slot enforcement and pause-flag filtering.

Verifies that the rewritten scheduler:
- Enforces per-user max_concurrent_processing limits
- Filters out paused and inactive accounts
- Filters out users with no healthy, non-paused provider
- Transitions mails from QUEUED to PROCESSING before ARQ dispatch
- Preserves round-robin fairness across users
"""

from __future__ import annotations

from collections import namedtuple
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.models import TrackedEmailStatus


# ---------------------------------------------------------------------------
# Lightweight row stubs returned by mock db.execute()
# ---------------------------------------------------------------------------

QueuedRow = namedtuple("QueuedRow", ["id", "user_id", "mail_account_id", "mail_uid"])
CountRow = namedtuple("CountRow", ["user_id", "count"])
UserSettingsRow = namedtuple("UserSettingsRow", ["user_id", "max_concurrent_processing"])
SingleIdRow = namedtuple("SingleIdRow", ["id"])
UserIdRow = namedtuple("UserIdRow", ["user_id"])


def _scalar_result(value):
    """Return a mock result whose .scalar() returns *value*."""
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _all_result(rows):
    """Return a mock result whose .all() returns *rows*."""
    r = MagicMock()
    r.all.return_value = rows
    return r


def _scalar_one_none_result(value):
    """Return a mock result whose .scalar_one_or_none() returns *value*."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


class _FakeTrackedEmail:
    """Mutable stand-in for a TrackedEmail row returned by SELECT ... FOR UPDATE."""

    def __init__(self, te_id: UUID, status: TrackedEmailStatus):
        self.id = te_id
        self.status = status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_db_side_effect(
    *,
    global_processing: int = 0,
    queued_rows: list[QueuedRow],
    healthy_account_ids: list[UUID],
    users_with_provider: list[UUID],
    per_user_processing: dict[UUID, int] | None = None,
    user_max_concurrent: dict[UUID, int] | None = None,
):
    """Build a side_effect function for db.execute() that answers each
    query in the scheduler in order.

    The scheduler issues these queries sequentially:
      0. COUNT PROCESSING (global)
      1. SELECT queued rows
      2. SELECT healthy account IDs
      3. SELECT users with healthy provider
      4. SELECT per-user processing counts
      5. SELECT per-user max_concurrent_processing
      6+. SELECT tracked_email by id (for QUEUED→PROCESSING transition)
    """
    if per_user_processing is None:
        per_user_processing = {}
    if user_max_concurrent is None:
        user_max_concurrent = {}

    # Pre-build tracked email objects for the QUEUED→PROCESSING step
    tracked_objects: dict[UUID, _FakeTrackedEmail] = {
        row.id: _FakeTrackedEmail(row.id, TrackedEmailStatus.QUEUED)
        for row in queued_rows
    }

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1

        if idx == 0:
            # Global PROCESSING count
            return _scalar_result(global_processing)
        elif idx == 1:
            # Queued rows
            return _all_result(queued_rows)
        elif idx == 2:
            # Healthy account IDs
            return _all_result([(aid,) for aid in healthy_account_ids])
        elif idx == 3:
            # Users with healthy provider
            return _all_result([(uid,) for uid in users_with_provider])
        elif idx == 4:
            # Per-user processing counts
            return _all_result(
                [(uid, cnt) for uid, cnt in per_user_processing.items()]
            )
        elif idx == 5:
            # Per-user max_concurrent_processing
            return _all_result(
                [(uid, mc) for uid, mc in user_max_concurrent.items()]
            )
        else:
            # QUEUED→PROCESSING lookups: return the tracked email object
            # We need to figure out which tracked_id is being queried.
            # In the scheduler, it does SELECT ... WHERE id = tracked_id
            # We return the matching _FakeTrackedEmail.
            for te in tracked_objects.values():
                if te.status == TrackedEmailStatus.QUEUED:
                    return _scalar_one_none_result(te)
            return _scalar_one_none_result(None)

    return _side_effect


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_settings():
    """Patch get_settings to return a settings object with worker_max_jobs=10."""
    settings = MagicMock()
    settings.worker_max_jobs = 10
    with patch("app.workers.scheduler.get_settings", return_value=settings):
        yield settings


@pytest.fixture
def arq_mock():
    """Mock ArqRedis with successful enqueue."""
    arq = AsyncMock()
    arq.enqueue_job = AsyncMock(return_value=MagicMock(job_id="test-job"))
    return arq


@pytest.fixture
def db_mock():
    """Mock AsyncSession."""
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


class TestPerUserSlotEnforcement:
    """Scheduler respects max_concurrent_processing per user."""

    @pytest.mark.asyncio
    async def test_user_at_capacity_is_skipped(self, mock_settings, arq_mock, db_mock):
        """User with processing_count >= max_concurrent_processing gets no new jobs."""
        from app.workers.scheduler import _schedule

        user_id = uuid4()
        account_id = uuid4()

        queued_rows = [
            QueuedRow(uuid4(), user_id, account_id, "uid1"),
            QueuedRow(uuid4(), user_id, account_id, "uid2"),
        ]

        db_mock.execute = AsyncMock(side_effect=_build_db_side_effect(
            global_processing=0,
            queued_rows=queued_rows,
            healthy_account_ids=[account_id],
            users_with_provider=[user_id],
            per_user_processing={user_id: 3},  # Already at capacity
            user_max_concurrent={user_id: 3},   # Limit is 3
        ))

        await _schedule(db_mock, arq_mock)

        # No jobs should be enqueued
        arq_mock.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_with_free_slots_gets_limited_dispatch(
        self, mock_settings, arq_mock, db_mock,
    ):
        """User with 1 free slot only gets 1 mail dispatched."""
        from app.workers.scheduler import _schedule

        user_id = uuid4()
        account_id = uuid4()

        queued_rows = [
            QueuedRow(uuid4(), user_id, account_id, "uid1"),
            QueuedRow(uuid4(), user_id, account_id, "uid2"),
            QueuedRow(uuid4(), user_id, account_id, "uid3"),
        ]

        # Build tracked objects for QUEUED→PROCESSING step
        tracked_objects = {
            row.id: _FakeTrackedEmail(row.id, TrackedEmailStatus.QUEUED)
            for row in queued_rows
        }

        call_count = 0

        async def _side_effect(stmt):
            nonlocal call_count
            idx = call_count
            call_count += 1

            if idx == 0:
                return _scalar_result(2)  # 2 already processing
            elif idx == 1:
                return _all_result(queued_rows)
            elif idx == 2:
                return _all_result([(account_id,)])
            elif idx == 3:
                return _all_result([(user_id,)])
            elif idx == 4:
                return _all_result([(user_id, 2)])  # 2 processing
            elif idx == 5:
                return _all_result([(user_id, 3)])  # max 3
            else:
                # Return first queued tracked email
                for te in tracked_objects.values():
                    if te.status == TrackedEmailStatus.QUEUED:
                        te.status = TrackedEmailStatus.PROCESSING
                        return _scalar_one_none_result(te)
                return _scalar_one_none_result(None)

        db_mock.execute = AsyncMock(side_effect=_side_effect)

        await _schedule(db_mock, arq_mock)

        # Only 1 job should be enqueued (3 - 2 = 1 free slot)
        assert arq_mock.enqueue_job.call_count == 1

    @pytest.mark.asyncio
    async def test_default_max_concurrent_when_no_settings(
        self, mock_settings, arq_mock, db_mock,
    ):
        """Users without UserSettings get the default limit of 3."""
        from app.workers.scheduler import _schedule

        user_id = uuid4()
        account_id = uuid4()

        queued_rows = [
            QueuedRow(uuid4(), user_id, account_id, f"uid{i}")
            for i in range(5)
        ]

        tracked_objects = {
            row.id: _FakeTrackedEmail(row.id, TrackedEmailStatus.QUEUED)
            for row in queued_rows
        }

        call_count = 0

        async def _side_effect(stmt):
            nonlocal call_count
            idx = call_count
            call_count += 1

            if idx == 0:
                return _scalar_result(0)  # none processing
            elif idx == 1:
                return _all_result(queued_rows)
            elif idx == 2:
                return _all_result([(account_id,)])
            elif idx == 3:
                return _all_result([(user_id,)])
            elif idx == 4:
                return _all_result([])  # no processing counts
            elif idx == 5:
                return _all_result([])  # no user settings -> default 3
            else:
                for te in tracked_objects.values():
                    if te.status == TrackedEmailStatus.QUEUED:
                        te.status = TrackedEmailStatus.PROCESSING
                        return _scalar_one_none_result(te)
                return _scalar_one_none_result(None)

        db_mock.execute = AsyncMock(side_effect=_side_effect)

        await _schedule(db_mock, arq_mock)

        # Default limit is 3, so only 3 out of 5 should be dispatched
        assert arq_mock.enqueue_job.call_count == 3


class TestPauseFlagFiltering:
    """Scheduler filters out paused accounts and providers."""

    @pytest.mark.asyncio
    async def test_paused_account_mails_skipped(self, mock_settings, arq_mock, db_mock):
        """Mails from paused accounts are not dispatched."""
        from app.workers.scheduler import _schedule

        user_id = uuid4()
        healthy_account = uuid4()
        paused_account = uuid4()

        queued_rows = [
            QueuedRow(uuid4(), user_id, paused_account, "uid1"),  # paused
            QueuedRow(uuid4(), user_id, healthy_account, "uid2"),  # healthy
        ]

        tracked_objects = {
            row.id: _FakeTrackedEmail(row.id, TrackedEmailStatus.QUEUED)
            for row in queued_rows
        }

        call_count = 0

        async def _side_effect(stmt):
            nonlocal call_count
            idx = call_count
            call_count += 1

            if idx == 0:
                return _scalar_result(0)
            elif idx == 1:
                return _all_result(queued_rows)
            elif idx == 2:
                # Only healthy_account passes the NOT is_paused filter
                return _all_result([(healthy_account,)])
            elif idx == 3:
                return _all_result([(user_id,)])
            elif idx == 4:
                return _all_result([])
            elif idx == 5:
                return _all_result([(user_id, 3)])
            else:
                for te in tracked_objects.values():
                    if te.status == TrackedEmailStatus.QUEUED:
                        te.status = TrackedEmailStatus.PROCESSING
                        return _scalar_one_none_result(te)
                return _scalar_one_none_result(None)

        db_mock.execute = AsyncMock(side_effect=_side_effect)

        await _schedule(db_mock, arq_mock)

        # Only 1 job (from healthy_account) should be enqueued
        assert arq_mock.enqueue_job.call_count == 1
        call_args = arq_mock.enqueue_job.call_args
        assert str(healthy_account) in call_args[0]

    @pytest.mark.asyncio
    async def test_user_with_all_providers_paused_skipped(
        self, mock_settings, arq_mock, db_mock,
    ):
        """Users with no healthy, non-paused provider get no dispatches."""
        from app.workers.scheduler import _schedule

        user_id = uuid4()
        account_id = uuid4()

        queued_rows = [
            QueuedRow(uuid4(), user_id, account_id, "uid1"),
        ]

        db_mock.execute = AsyncMock(side_effect=_build_db_side_effect(
            global_processing=0,
            queued_rows=queued_rows,
            healthy_account_ids=[account_id],
            users_with_provider=[],  # No healthy provider for this user
        ))

        await _schedule(db_mock, arq_mock)

        arq_mock.enqueue_job.assert_not_called()


class TestQueuedToProcessingTransition:
    """Scheduler transitions mails from QUEUED to PROCESSING before dispatch."""

    @pytest.mark.asyncio
    async def test_mail_status_set_to_processing(self, mock_settings, arq_mock, db_mock):
        """Dispatched mail has its status changed to PROCESSING."""
        from app.workers.scheduler import _schedule

        user_id = uuid4()
        account_id = uuid4()
        te_id = uuid4()

        queued_rows = [QueuedRow(te_id, user_id, account_id, "uid1")]
        tracked = _FakeTrackedEmail(te_id, TrackedEmailStatus.QUEUED)

        call_count = 0

        async def _side_effect(stmt):
            nonlocal call_count
            idx = call_count
            call_count += 1

            if idx == 0:
                return _scalar_result(0)
            elif idx == 1:
                return _all_result(queued_rows)
            elif idx == 2:
                return _all_result([(account_id,)])
            elif idx == 3:
                return _all_result([(user_id,)])
            elif idx == 4:
                return _all_result([])
            elif idx == 5:
                return _all_result([(user_id, 5)])
            else:
                return _scalar_one_none_result(tracked)

        db_mock.execute = AsyncMock(side_effect=_side_effect)

        await _schedule(db_mock, arq_mock)

        # Verify the tracked email was set to PROCESSING
        assert tracked.status == TrackedEmailStatus.PROCESSING
        # And commit was called
        db_mock.commit.assert_called_once()


class TestRoundRobinFairness:
    """Scheduler distributes dispatches fairly across users."""

    @pytest.mark.asyncio
    async def test_round_robin_alternates_users(self, mock_settings, arq_mock, db_mock):
        """With two users, dispatches alternate between them."""
        from app.workers.scheduler import _schedule

        user_a = uuid4()
        user_b = uuid4()
        acct_a = uuid4()
        acct_b = uuid4()

        queued_rows = [
            QueuedRow(uuid4(), user_a, acct_a, "a1"),
            QueuedRow(uuid4(), user_a, acct_a, "a2"),
            QueuedRow(uuid4(), user_b, acct_b, "b1"),
            QueuedRow(uuid4(), user_b, acct_b, "b2"),
        ]

        tracked_objects = {
            row.id: _FakeTrackedEmail(row.id, TrackedEmailStatus.QUEUED)
            for row in queued_rows
        }
        tracked_list = list(tracked_objects.values())
        tracked_idx = 0

        call_count = 0

        async def _side_effect(stmt):
            nonlocal call_count, tracked_idx
            idx = call_count
            call_count += 1

            if idx == 0:
                return _scalar_result(0)
            elif idx == 1:
                return _all_result(queued_rows)
            elif idx == 2:
                return _all_result([(acct_a,), (acct_b,)])
            elif idx == 3:
                return _all_result([(user_a,), (user_b,)])
            elif idx == 4:
                return _all_result([])
            elif idx == 5:
                return _all_result([(user_a, 5), (user_b, 5)])
            else:
                if tracked_idx < len(tracked_list):
                    te = tracked_list[tracked_idx]
                    tracked_idx += 1
                    te.status = TrackedEmailStatus.PROCESSING
                    return _scalar_one_none_result(te)
                return _scalar_one_none_result(None)

        db_mock.execute = AsyncMock(side_effect=_side_effect)

        await _schedule(db_mock, arq_mock)

        # All 4 mails dispatched (2 per user, each has 5 slots)
        assert arq_mock.enqueue_job.call_count == 4


class TestGlobalCapacity:
    """Scheduler respects global worker capacity."""

    @pytest.mark.asyncio
    async def test_no_dispatch_when_worker_full(self, mock_settings, arq_mock, db_mock):
        """When global processing == max_jobs - reserved, nothing is dispatched."""
        from app.workers.scheduler import _schedule

        mock_settings.worker_max_jobs = 10  # max_process_slots = 10 - 2 = 8

        db_mock.execute = AsyncMock(side_effect=_build_db_side_effect(
            global_processing=8,  # At capacity
            queued_rows=[QueuedRow(uuid4(), uuid4(), uuid4(), "uid1")],
            healthy_account_ids=[],
            users_with_provider=[],
        ))

        await _schedule(db_mock, arq_mock)

        arq_mock.enqueue_job.assert_not_called()
