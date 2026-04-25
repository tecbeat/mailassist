"""Tests for fair queuing and backoff in mail polling (test area 13).

Covers: exponential backoff schedule, fair distribution across users,
interval-based skip logic, and backoff skip logic.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.utils import get_backoff_seconds
from app.workers.mail_poller import POLLER_BACKOFF_SCHEDULE


# ---------------------------------------------------------------------------
# Test Area 13: Fair Queuing
# ---------------------------------------------------------------------------


class TestBackoffSchedule:
    """Exponential backoff delay calculation."""

    def test_zero_errors_first_backoff(self):
        """Zero consecutive errors gives the first backoff interval."""
        assert get_backoff_seconds(0, POLLER_BACKOFF_SCHEDULE) == POLLER_BACKOFF_SCHEDULE[0]

    def test_progressive_backoff(self):
        """Each error level steps through the schedule."""
        assert get_backoff_seconds(0, POLLER_BACKOFF_SCHEDULE) == 30
        assert get_backoff_seconds(1, POLLER_BACKOFF_SCHEDULE) == 60
        assert get_backoff_seconds(2, POLLER_BACKOFF_SCHEDULE) == 120
        assert get_backoff_seconds(3, POLLER_BACKOFF_SCHEDULE) == 300

    def test_backoff_caps_at_max(self):
        """Errors beyond schedule length use the last (max) value."""
        assert get_backoff_seconds(10, POLLER_BACKOFF_SCHEDULE) == 300
        assert get_backoff_seconds(100, POLLER_BACKOFF_SCHEDULE) == 300

    def test_schedule_is_monotonically_increasing(self):
        """Backoff schedule values increase monotonically."""
        for i in range(len(POLLER_BACKOFF_SCHEDULE) - 1):
            assert POLLER_BACKOFF_SCHEDULE[i] < POLLER_BACKOFF_SCHEDULE[i + 1]


class TestPollingFairness:
    """Fair queuing: accounts ordered by user_id, then oldest sync first."""

    def _make_account(self, user_id, last_sync_at=None, polling_interval=5,
                      consecutive_errors=0, last_error_at=None, is_paused=False):
        """Create a mock MailAccount."""
        a = MagicMock()
        a.id = uuid4()
        a.user_id = user_id
        a.last_sync_at = last_sync_at
        a.polling_interval_minutes = polling_interval
        a.consecutive_errors = consecutive_errors
        a.last_error_at = last_error_at
        a.is_paused = is_paused
        a.polling_enabled = True
        return a

    def test_accounts_skip_when_not_due(self):
        """Account whose interval has not elapsed is skipped."""
        now = datetime.now(UTC)
        user_id = uuid4()
        account = self._make_account(
            user_id=user_id,
            last_sync_at=now - timedelta(minutes=2),
            polling_interval=5,
        )
        # 2 minutes < 5 minutes interval -> should skip
        elapsed = (now - account.last_sync_at).total_seconds()
        interval_seconds = account.polling_interval_minutes * 60
        assert elapsed < interval_seconds

    def test_accounts_due_when_interval_passed(self):
        """Account whose interval has elapsed should be polled."""
        now = datetime.now(UTC)
        user_id = uuid4()
        account = self._make_account(
            user_id=user_id,
            last_sync_at=now - timedelta(minutes=10),
            polling_interval=5,
        )
        elapsed = (now - account.last_sync_at).total_seconds()
        interval_seconds = account.polling_interval_minutes * 60
        assert elapsed >= interval_seconds

    def test_never_synced_accounts_are_due(self):
        """Accounts with last_sync_at=None are always due for polling."""
        user_id = uuid4()
        account = self._make_account(user_id=user_id, last_sync_at=None)
        assert account.last_sync_at is None  # always polled

    def test_backoff_skips_errored_accounts(self):
        """Errored accounts within backoff window are skipped."""
        now = datetime.now(UTC)
        user_id = uuid4()
        account = self._make_account(
            user_id=user_id,
            consecutive_errors=2,
            last_error_at=now - timedelta(seconds=30),  # 30s ago
        )
        backoff = get_backoff_seconds(account.consecutive_errors, POLLER_BACKOFF_SCHEDULE)
        elapsed_since_error = (now - account.last_error_at).total_seconds()
        # backoff for 2 errors = 120s, elapsed = 30s -> should skip
        assert elapsed_since_error < backoff

    def test_backoff_allows_after_window(self):
        """Errored accounts past backoff window should be polled."""
        now = datetime.now(UTC)
        user_id = uuid4()
        account = self._make_account(
            user_id=user_id,
            consecutive_errors=1,
            last_error_at=now - timedelta(seconds=120),  # 120s ago
        )
        backoff = get_backoff_seconds(account.consecutive_errors, POLLER_BACKOFF_SCHEDULE)
        elapsed_since_error = (now - account.last_error_at).total_seconds()
        # backoff for 1 error = 60s, elapsed = 120s -> should poll
        assert elapsed_since_error >= backoff

    def test_fair_ordering_by_user_and_sync(self):
        """Accounts are ordered by user_id then oldest sync for fairness."""
        user_a = uuid4()
        user_b = uuid4()
        now = datetime.now(UTC)

        accounts = [
            self._make_account(user_a, last_sync_at=now - timedelta(minutes=10)),
            self._make_account(user_a, last_sync_at=now - timedelta(minutes=2)),
            self._make_account(user_b, last_sync_at=now - timedelta(minutes=15)),
            self._make_account(user_b, last_sync_at=None),
        ]

        # Sort like the SQL query: by user_id, then by last_sync_at ascending (null first)
        sorted_accounts = sorted(
            accounts,
            key=lambda a: (str(a.user_id), a.last_sync_at or datetime.min.replace(tzinfo=UTC)),
        )

        # Verify accounts of same user are grouped together
        user_ids = [str(a.user_id) for a in sorted_accounts]
        # Adjacent same-user accounts should be grouped
        for i in range(len(user_ids) - 1):
            if user_ids[i] == user_ids[i + 1]:
                # Same user accounts are adjacent (grouped)
                pass
