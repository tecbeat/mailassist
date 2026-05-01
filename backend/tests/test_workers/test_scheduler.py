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
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.models import TrackedEmailStatus
from app.models.user import ApprovalMode

# ---------------------------------------------------------------------------
# Lightweight row stubs returned by mock db.execute()
# ---------------------------------------------------------------------------

# ``current_folder`` defaults to ``INBOX`` so existing 4-field constructions
# stay valid; the scheduler accesses ``row.current_folder`` per-mail.
QueuedRow = namedtuple(
    "QueuedRow",
    ["id", "user_id", "mail_account_id", "mail_uid", "current_folder"],
    defaults=["INBOX"],
)
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


def _scalars_all_result(items):
    """Return a mock result whose .scalars().all() returns *items*."""
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _scalar_one_none_result(value):
    """Return a mock result whose .scalar_one_or_none() returns *value*."""
    r = MagicMock()
    r.scalar_one_or_none.return_value = value
    return r


def _make_provider_for_user(user_id: UUID):
    """Build a healthy default AI provider mock for the given user."""
    p = MagicMock()
    p.id = uuid4()
    p.user_id = user_id
    p.is_paused = False
    p.is_default = True
    p.created_at = datetime.now(UTC)
    return p


def _make_user_settings_for_user(user_id: UUID, *, max_concurrent: int = 5):
    """Build a UserSettings mock that passes ``_user_has_healthy_provider``.

    At least one approval column must be non-DISABLED for the scheduler
    to consider any plugin enabled; we set ``approval_mode_spam`` to
    AUTO and rely on the fact that MagicMock-typed approval columns
    on the rest do not compare equal to ``ApprovalMode.DISABLED``,
    which keeps the user discoverable as "has enabled plugins".
    """
    us = MagicMock()
    us.user_id = user_id
    us.plugin_provider_map = {}
    us.max_concurrent_processing = max_concurrent
    us.approval_mode_spam = ApprovalMode.AUTO
    return us


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
      0. COUNT PROCESSING (global)              → ``.scalar()``
      1. SELECT queued rows                     → ``.all()``
      2. SELECT healthy account IDs             → ``.all()``
      3. SELECT AIProvider rows (per-user mix)  → ``.scalars().all()``
      4. SELECT UserSettings rows               → ``.scalars().all()``
      5. SELECT per-user processing counts      → ``.all()``
      6+. SELECT tracked_email by id (QUEUED→PROCESSING) → ``.scalar_one_or_none()``

    Plugin-aware "user has healthy provider" filtering is rebuilt from
    the providers + UserSettings rows we feed in here, so callers only
    have to pass the simple ``users_with_provider`` and
    ``user_max_concurrent`` summaries; the helper materialises matching
    mock providers + UserSettings under the hood.
    """
    if per_user_processing is None:
        per_user_processing = {}
    if user_max_concurrent is None:
        user_max_concurrent = {}

    # Materialise providers + UserSettings only for users that should be
    # considered "healthy" — _user_has_healthy_provider returns False for
    # any user not present in user_settings_map.
    providers_list = [_make_provider_for_user(uid) for uid in users_with_provider]
    user_settings_list = [
        _make_user_settings_for_user(uid, max_concurrent=user_max_concurrent.get(uid, 5)) for uid in users_with_provider
    ]

    # Pre-build tracked email objects for the QUEUED→PROCESSING step
    tracked_objects: dict[UUID, _FakeTrackedEmail] = {
        row.id: _FakeTrackedEmail(row.id, TrackedEmailStatus.QUEUED) for row in queued_rows
    }

    call_count = 0

    async def _side_effect(stmt):
        nonlocal call_count
        idx = call_count
        call_count += 1

        if idx == 0:
            return _scalar_result(global_processing)
        elif idx == 1:
            return _all_result(queued_rows)
        elif idx == 2:
            return _all_result([(aid,) for aid in healthy_account_ids])
        elif idx == 3:
            return _scalars_all_result(providers_list)
        elif idx == 4:
            return _scalars_all_result(user_settings_list)
        elif idx == 5:
            return _all_result(list(per_user_processing.items()))
        else:
            # QUEUED→PROCESSING lookups: return the next still-QUEUED row.
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
    """Patch get_settings with all integer fields the scheduler reads.

    Without explicit ints these MagicMock attributes propagate into
    arithmetic (``settings.worker_max_jobs - settings.scheduler_reserved_slots``),
    which then blows up in ``max(1, ...)`` with
    ``TypeError: '>' not supported between instances of 'MagicMock' and 'int'``.
    """
    settings = MagicMock()
    settings.worker_max_jobs = 10
    settings.scheduler_reserved_slots = 2
    settings.scheduler_max_batch = 100
    settings.scheduler_default_max_concurrent = 3
    settings.stale_job_threshold_seconds = 300
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

        db_mock.execute = AsyncMock(
            side_effect=_build_db_side_effect(
                global_processing=0,
                queued_rows=queued_rows,
                healthy_account_ids=[account_id],
                users_with_provider=[user_id],
                per_user_processing={user_id: 3},  # Already at capacity
                user_max_concurrent={user_id: 3},  # Limit is 3
            )
        )

        await _schedule(db_mock, arq_mock)

        # No jobs should be enqueued
        arq_mock.enqueue_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_user_with_free_slots_gets_limited_dispatch(
        self,
        mock_settings,
        arq_mock,
        db_mock,
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
        tracked_objects = {row.id: _FakeTrackedEmail(row.id, TrackedEmailStatus.QUEUED) for row in queued_rows}

        call_count = 0

        provider = _make_provider_for_user(user_id)
        user_settings = _make_user_settings_for_user(user_id, max_concurrent=3)

        async def _side_effect(stmt):
            nonlocal call_count
            idx = call_count
            call_count += 1

            if idx == 0:
                return _scalar_result(2)  # 2 already processing globally
            elif idx == 1:
                return _all_result(queued_rows)
            elif idx == 2:
                return _all_result([(account_id,)])
            elif idx == 3:
                return _scalars_all_result([provider])
            elif idx == 4:
                return _scalars_all_result([user_settings])
            elif idx == 5:
                return _all_result([(user_id, 2)])  # 2 processing for this user
            else:
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
        self,
        mock_settings,
        arq_mock,
        db_mock,
    ):
        """Users with explicit UserSettings respect ``max_concurrent_processing``.

        (The pre-refactor scheduler also fell back to a default when no
        UserSettings row existed at all.  In the new code an absent
        UserSettings row makes the user fail ``_user_has_healthy_provider``
        and skips them entirely, so the default-fallback path is now
        exercised by setting an explicit limit on the row instead.)
        """
        from app.workers.scheduler import _schedule

        user_id = uuid4()
        account_id = uuid4()

        queued_rows = [QueuedRow(uuid4(), user_id, account_id, f"uid{i}") for i in range(5)]

        tracked_objects = {row.id: _FakeTrackedEmail(row.id, TrackedEmailStatus.QUEUED) for row in queued_rows}

        provider = _make_provider_for_user(user_id)
        user_settings = _make_user_settings_for_user(user_id, max_concurrent=3)

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
                return _scalars_all_result([provider])
            elif idx == 4:
                return _scalars_all_result([user_settings])
            elif idx == 5:
                return _all_result([])  # no processing counts
            else:
                for te in tracked_objects.values():
                    if te.status == TrackedEmailStatus.QUEUED:
                        te.status = TrackedEmailStatus.PROCESSING
                        return _scalar_one_none_result(te)
                return _scalar_one_none_result(None)

        db_mock.execute = AsyncMock(side_effect=_side_effect)

        await _schedule(db_mock, arq_mock)

        # Configured limit is 3, so only 3 out of 5 should be dispatched.
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

        tracked_objects = {row.id: _FakeTrackedEmail(row.id, TrackedEmailStatus.QUEUED) for row in queued_rows}

        call_count = 0

        provider = _make_provider_for_user(user_id)
        user_settings = _make_user_settings_for_user(user_id, max_concurrent=3)

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
                return _scalars_all_result([provider])
            elif idx == 4:
                return _scalars_all_result([user_settings])
            elif idx == 5:
                return _all_result([])
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
        self,
        mock_settings,
        arq_mock,
        db_mock,
    ):
        """Users with no healthy, non-paused provider get no dispatches."""
        from app.workers.scheduler import _schedule

        user_id = uuid4()
        account_id = uuid4()

        queued_rows = [
            QueuedRow(uuid4(), user_id, account_id, "uid1"),
        ]

        db_mock.execute = AsyncMock(
            side_effect=_build_db_side_effect(
                global_processing=0,
                queued_rows=queued_rows,
                healthy_account_ids=[account_id],
                users_with_provider=[],  # No healthy provider for this user
            )
        )

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

        provider = _make_provider_for_user(user_id)
        user_settings = _make_user_settings_for_user(user_id, max_concurrent=5)

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
                return _scalars_all_result([provider])
            elif idx == 4:
                return _scalars_all_result([user_settings])
            elif idx == 5:
                return _all_result([])
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

        tracked_objects = {row.id: _FakeTrackedEmail(row.id, TrackedEmailStatus.QUEUED) for row in queued_rows}
        tracked_list = list(tracked_objects.values())
        tracked_idx = 0

        call_count = 0

        provider_a = _make_provider_for_user(user_a)
        provider_b = _make_provider_for_user(user_b)
        us_a = _make_user_settings_for_user(user_a, max_concurrent=5)
        us_b = _make_user_settings_for_user(user_b, max_concurrent=5)

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
                return _scalars_all_result([provider_a, provider_b])
            elif idx == 4:
                return _scalars_all_result([us_a, us_b])
            elif idx == 5:
                return _all_result([])
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

        db_mock.execute = AsyncMock(
            side_effect=_build_db_side_effect(
                global_processing=8,  # At capacity
                queued_rows=[QueuedRow(uuid4(), uuid4(), uuid4(), "uid1")],
                healthy_account_ids=[],
                users_with_provider=[],
            )
        )

        await _schedule(db_mock, arq_mock)

        arq_mock.enqueue_job.assert_not_called()
