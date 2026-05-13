"""Coverage tests for mail_poller, contact_sync, and draft_monitor.

Targets uncovered lines in:
- mail_poller.py: 73-144, 256-260, 334, 359, 369, 503, 595-614
- contact_sync.py: 27-28, 39-104
- draft_monitor.py: 30-64
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ===========================================================================
# Helpers
# ===========================================================================


def _make_account(
    *,
    account_id=None,
    user_id=None,
    initial_scan_done=True,
    scan_existing_emails=False,
    excluded_folders=None,
    is_paused=False,
    polling_enabled=True,
    polling_interval_minutes=5,
    consecutive_errors=0,
    last_error_at=None,
    last_sync_at=None,
    idle_enabled=False,
):
    account = MagicMock()
    account.id = account_id or uuid4()
    account.user_id = user_id or uuid4()
    account.name = "Test"
    account.email_address = "t@t.com"
    account.imap_host = "imap.t.com"
    account.imap_port = 993
    account.is_paused = is_paused
    account.initial_scan_done = initial_scan_done
    account.scan_existing_emails = scan_existing_emails
    account.excluded_folders = excluded_folders or []
    account.polling_enabled = polling_enabled
    account.polling_interval_minutes = polling_interval_minutes
    account.consecutive_errors = consecutive_errors
    account.last_error_at = last_error_at
    account.last_sync_at = last_sync_at
    account.idle_enabled = idle_enabled
    return account


def _mock_get_session_ctx(db=None):
    @asynccontextmanager
    async def _ctx():
        d = db or AsyncMock()
        if db is None:
            result = MagicMock()
            result.scalar_one_or_none.return_value = MagicMock(initial_scan_done=False)
            d.execute = AsyncMock(return_value=result)
        yield d

    return _ctx


# ===========================================================================
# mail_poller: poll_mail_accounts (lines 73-144)
# ===========================================================================


class TestPollMailAccounts:
    """Tests for the poll_mail_accounts entry point."""

    @pytest.mark.asyncio
    async def test_poll_no_accounts_returns_early(self):
        """No active accounts → early return (lines 93-95)."""
        from app.workers.mail_poller import poll_mail_accounts

        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result)

        with patch("app.workers.mail_poller.get_session_ctx", _mock_get_session_ctx(mock_db)):
            await poll_mail_accounts({})

    @pytest.mark.asyncio
    async def test_poll_filters_by_interval_and_backoff(self):
        """Accounts not due or in backoff are filtered out (lines 98-124)."""
        from collections import namedtuple

        from app.workers.mail_poller import poll_mail_accounts

        Row = namedtuple(
            "Row", ["id", "user_id", "polling_interval_minutes", "last_sync_at", "consecutive_errors", "last_error_at"]
        )

        now = datetime.now(UTC)
        rows = [
            # Recently synced — should be skipped (line 105-106)
            Row(uuid4(), uuid4(), 5, now - timedelta(seconds=30), 0, None),
            # In backoff — should be skipped (lines 109-119)
            Row(uuid4(), uuid4(), 5, now - timedelta(hours=1), 3, now - timedelta(seconds=10)),
            # Due for sync — should be included (line 121)
            Row(uuid4(), uuid4(), 5, now - timedelta(hours=1), 0, None),
        ]

        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = rows
        mock_db.execute = AsyncMock(return_value=result)

        poll_called_with = []

        async def _fake_poll(account, *, force=False):
            poll_called_with.append(str(account.id))

        # Mock the inner session for _poll_with_semaphore
        inner_db = AsyncMock()
        inner_result = MagicMock()
        account_mock = _make_account(account_id=rows[2].id)
        inner_result.scalar_one_or_none.return_value = account_mock
        inner_db.execute = AsyncMock(return_value=inner_result)

        call_count = 0

        @asynccontextmanager
        async def _session_ctx():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield mock_db
            else:
                yield inner_db

        settings = MagicMock()
        settings.poll_concurrency = 5

        with (
            patch("app.workers.mail_poller.get_session_ctx", _session_ctx),
            patch("app.workers.mail_poller.get_settings", return_value=settings),
            patch("app.workers.mail_poller._poll_single_account", side_effect=_fake_poll) as mock_poll,
        ):
            await poll_mail_accounts({})

        assert mock_poll.call_count == 1

    @pytest.mark.asyncio
    async def test_poll_no_accounts_after_filtering(self):
        """All accounts filtered → empty list, early return (lines 123-124)."""
        from collections import namedtuple

        from app.workers.mail_poller import poll_mail_accounts

        Row = namedtuple(
            "Row", ["id", "user_id", "polling_interval_minutes", "last_sync_at", "consecutive_errors", "last_error_at"]
        )

        now = datetime.now(UTC)
        rows = [
            Row(uuid4(), uuid4(), 5, now - timedelta(seconds=30), 0, None),  # too recent
        ]

        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = rows
        mock_db.execute = AsyncMock(return_value=result)

        with patch("app.workers.mail_poller.get_session_ctx", _mock_get_session_ctx(mock_db)):
            await poll_mail_accounts({})

    @pytest.mark.asyncio
    async def test_poll_skips_paused_account_in_phase2(self):
        """Account becomes paused between phase1 and phase2 (line 140-141)."""
        from collections import namedtuple

        from app.workers.mail_poller import poll_mail_accounts

        Row = namedtuple(
            "Row", ["id", "user_id", "polling_interval_minutes", "last_sync_at", "consecutive_errors", "last_error_at"]
        )

        aid = uuid4()
        rows = [Row(aid, uuid4(), 5, None, 0, None)]

        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = rows
        mock_db.execute = AsyncMock(return_value=result)

        # Inner session returns paused account
        inner_db = AsyncMock()
        paused_acct = _make_account(account_id=aid, is_paused=True)
        inner_result = MagicMock()
        inner_result.scalar_one_or_none.return_value = paused_acct
        inner_db.execute = AsyncMock(return_value=inner_result)

        call_count = 0

        @asynccontextmanager
        async def _session_ctx():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield mock_db
            else:
                yield inner_db

        settings = MagicMock()
        settings.poll_concurrency = 5

        with (
            patch("app.workers.mail_poller.get_session_ctx", _session_ctx),
            patch("app.workers.mail_poller.get_settings", return_value=settings),
            patch("app.workers.mail_poller._poll_single_account") as mock_poll,
        ):
            await poll_mail_accounts({})
            mock_poll.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_account_not_found_in_phase2(self):
        """Account deleted between phase1 and phase2 (line 140)."""
        from collections import namedtuple

        from app.workers.mail_poller import poll_mail_accounts

        Row = namedtuple(
            "Row", ["id", "user_id", "polling_interval_minutes", "last_sync_at", "consecutive_errors", "last_error_at"]
        )

        rows = [Row(uuid4(), uuid4(), 5, None, 0, None)]

        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = rows
        mock_db.execute = AsyncMock(return_value=result)

        inner_db = AsyncMock()
        inner_result = MagicMock()
        inner_result.scalar_one_or_none.return_value = None
        inner_db.execute = AsyncMock(return_value=inner_result)

        call_count = 0

        @asynccontextmanager
        async def _session_ctx():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield mock_db
            else:
                yield inner_db

        settings = MagicMock()
        settings.poll_concurrency = 5

        with (
            patch("app.workers.mail_poller.get_session_ctx", _session_ctx),
            patch("app.workers.mail_poller.get_settings", return_value=settings),
            patch("app.workers.mail_poller._poll_single_account") as mock_poll,
        ):
            await poll_mail_accounts({})
            mock_poll.assert_not_called()


# ===========================================================================
# mail_poller: _poll_single_account error path (lines 256-260)
# ===========================================================================


class TestPollSingleAccountError:
    @pytest.mark.asyncio
    async def test_polling_failure_updates_error_status(self):
        """IMAP failure triggers error status update + circuit breaker (lines 256-260)."""
        from app.workers.mail_poller import _poll_single_account

        account = _make_account()
        mock_db = AsyncMock()

        with (
            patch(
                "app.workers.mail_poller.connect_imap", new_callable=AsyncMock, side_effect=RuntimeError("IMAP down")
            ),
            patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
            patch("app.workers.mail_poller.timed_operation") as mock_timed,
            patch("app.workers.mail_poller.is_idle_active", return_value=False),
            patch("app.workers.mail_poller.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch("app.workers.mail_poller.update_account_sync_status", new_callable=AsyncMock) as mock_update,
            patch("app.workers.mail_poller.check_circuit_breaker", new_callable=AsyncMock) as mock_cb,
        ):
            mock_timed.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("IMAP down"))
            mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)

            await _poll_single_account(account)

            mock_update.assert_called()
            mock_cb.assert_called()


# ===========================================================================
# mail_poller: _poll_folder uidvalidity relink log (line 334)
# ===========================================================================


class TestPollFolderUidvalidity:
    @pytest.mark.asyncio
    async def test_uidvalidity_relink_logs(self):
        """UIDVALIDITY change triggers relink (line 334)."""
        from app.workers.mail_poller import _poll_folder

        conn = MagicMock()
        account = _make_account()

        _mock_db = AsyncMock()
        # First call: uidvalidity check returns old value
        uv_result = MagicMock()
        uv_result.scalar_one_or_none.return_value = 99999  # old uidvalidity
        # Second call: _get_new_uids returns empty
        new_uids_result = MagicMock()
        new_uids_result.all.return_value = []

        call_count = 0

        @asynccontextmanager
        async def _session_ctx():
            nonlocal call_count
            call_count += 1
            d = AsyncMock()
            if call_count == 1:
                d.execute = AsyncMock(return_value=uv_result)
            else:
                d.execute = AsyncMock(return_value=new_uids_result)
            yield d

        with (
            patch("app.workers.mail_poller.search_uids", new_callable=AsyncMock, return_value=(["1", "2"], 12345)),
            patch("app.workers.mail_poller.get_session_ctx", _session_ctx),
            patch("app.workers.mail_poller._get_new_uids", new_callable=AsyncMock, return_value=[]),
            patch(
                "app.workers.mail_poller._relink_uids_by_message_id", new_callable=AsyncMock, return_value=3
            ) as mock_relink,
        ):
            result = await _poll_folder(conn, account, "INBOX", search_criterion="ALL", is_initial_scan=False)

            assert result == 0
            mock_relink.assert_called_once()


# ===========================================================================
# mail_poller: envelope skip for large backlog (line 359, 369)
# ===========================================================================


class TestPollFolderLargeBacklog:
    @pytest.mark.asyncio
    async def test_large_backlog_skips_envelopes(self):
        """>5000 new UIDs skips envelope fetch (lines 366-375)."""
        from app.workers.mail_poller import _poll_folder

        conn = MagicMock()
        account = _make_account()

        uids = [str(i) for i in range(5001)]

        mock_db = AsyncMock()
        mock_insert_result = MagicMock()
        mock_insert_result.rowcount = 5001
        mock_db.execute = AsyncMock(return_value=mock_insert_result)
        mock_db.flush = AsyncMock()

        @asynccontextmanager
        async def _session_ctx():
            yield mock_db

        settings = MagicMock()
        settings.poll_initial_scan_batch = 10000

        with (
            patch("app.workers.mail_poller.search_uids", new_callable=AsyncMock, return_value=(uids, None)),
            patch("app.workers.mail_poller.get_session_ctx", _session_ctx),
            patch("app.workers.mail_poller._get_new_uids", new_callable=AsyncMock, return_value=uids),
            patch("app.workers.mail_poller.fetch_envelopes", new_callable=AsyncMock) as mock_env,
            patch("app.workers.mail_poller._insert_tracked_batch", new_callable=AsyncMock, return_value=5001),
            patch("app.workers.mail_poller.get_settings", return_value=settings),
        ):
            result = await _poll_folder(conn, account, "INBOX", search_criterion="ALL", is_initial_scan=False)

            mock_env.assert_not_called()
            assert result == 5001


# ===========================================================================
# mail_poller: _get_new_uids empty input (line 502-503)
# ===========================================================================


class TestGetNewUids:
    @pytest.mark.asyncio
    async def test_empty_candidates_returns_empty(self):
        """Empty candidate list returns empty (lines 502-503)."""
        from app.workers.mail_poller import _get_new_uids

        db = AsyncMock()
        result = await _get_new_uids(db, str(uuid4()), [])
        assert result == []


# ===========================================================================
# mail_poller: poll_single_account (lines 595-614)
# ===========================================================================


class TestPollSingleAccount:
    @pytest.mark.asyncio
    async def test_poll_single_account_found(self):
        """Manual poll dispatches to _poll_single_account (lines 595-614)."""
        from app.workers.mail_poller import poll_single_account

        uid = uuid4()
        aid = uuid4()
        account = _make_account(account_id=aid, user_id=uid)

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = account
        mock_db.execute = AsyncMock(return_value=result)

        with (
            patch("app.workers.mail_poller.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch("app.workers.mail_poller._poll_single_account", new_callable=AsyncMock) as mock_poll,
        ):
            await poll_single_account({}, str(uid), str(aid))
            mock_poll.assert_called_once_with(account, force=True)

    @pytest.mark.asyncio
    async def test_poll_single_account_not_found(self):
        """Account not found returns early (lines 609-611)."""
        from app.workers.mail_poller import poll_single_account

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result)

        with (
            patch("app.workers.mail_poller.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch("app.workers.mail_poller._poll_single_account", new_callable=AsyncMock) as mock_poll,
        ):
            await poll_single_account({}, str(uuid4()), str(uuid4()))
            mock_poll.assert_not_called()


# ===========================================================================
# contact_sync: _get_backoff_minutes (lines 27-28)
# ===========================================================================


class TestContactSyncBackoff:
    def test_get_backoff_minutes_first_error(self):
        """First error returns first backoff value (lines 27-28)."""
        from app.workers.contact_sync import _get_backoff_minutes

        assert _get_backoff_minutes(0) == 5

    def test_get_backoff_minutes_capped(self):
        """High error count caps at max (lines 27-28)."""
        from app.workers.contact_sync import _get_backoff_minutes

        assert _get_backoff_minutes(100) == 120

    def test_get_backoff_minutes_mid(self):
        from app.workers.contact_sync import _get_backoff_minutes

        assert _get_backoff_minutes(2) == 30


# ===========================================================================
# contact_sync: sync_all_contacts (lines 39-104)
# ===========================================================================


class TestSyncAllContacts:
    @pytest.mark.asyncio
    async def test_no_active_configs_returns_early(self):
        """No active CardDAV configs → early return (lines 46-48)."""
        from app.workers.contact_sync import sync_all_contacts

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result)

        with patch("app.workers.contact_sync.get_session_ctx", _mock_get_session_ctx(mock_db)):
            await sync_all_contacts({})

    @pytest.mark.asyncio
    async def test_config_not_due_skipped(self):
        """Config synced recently is skipped (lines 52-60)."""
        from app.workers.contact_sync import sync_all_contacts

        config = MagicMock()
        config.user_id = uuid4()
        config.last_sync_at = datetime.now(UTC) - timedelta(minutes=1)
        config.sync_interval = 60  # 60 min interval, only 1 min elapsed
        config.consecutive_errors = 0

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [config]
        mock_db.execute = AsyncMock(return_value=result)

        with (
            patch("app.workers.contact_sync.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch("app.workers.contact_sync.sync_contacts", new_callable=AsyncMock) as mock_sync,
        ):
            await sync_all_contacts({})
            mock_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_config_in_backoff_skipped(self):
        """Config with errors in backoff period is skipped (lines 63-73)."""
        from app.workers.contact_sync import sync_all_contacts

        config = MagicMock()
        config.user_id = uuid4()
        config.last_sync_at = None
        config.sync_interval = 5
        config.consecutive_errors = 2
        config.last_error_at = datetime.now(UTC) - timedelta(minutes=1)  # 1 min ago, backoff=15

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [config]
        mock_db.execute = AsyncMock(return_value=result)

        with (
            patch("app.workers.contact_sync.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch("app.workers.contact_sync.sync_contacts", new_callable=AsyncMock) as mock_sync,
        ):
            await sync_all_contacts({})
            mock_sync.assert_not_called()

    @pytest.mark.asyncio
    async def test_config_sync_success_resets_errors(self):
        """Successful sync resets error state (lines 75-88)."""
        from app.workers.contact_sync import sync_all_contacts

        config = MagicMock()
        config.user_id = uuid4()
        config.last_sync_at = None
        config.sync_interval = 5
        config.consecutive_errors = 0
        config.last_error_at = None

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [config]
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.flush = AsyncMock()

        with (
            patch("app.workers.contact_sync.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch(
                "app.workers.contact_sync.sync_contacts",
                new_callable=AsyncMock,
                return_value={"created": 5, "updated": 2},
            ),
        ):
            await sync_all_contacts({})

            assert config.consecutive_errors == 0
            assert config.last_error is None

    @pytest.mark.asyncio
    async def test_config_sync_failure_increments_errors(self):
        """Failed sync increments error count (lines 89-108)."""
        from app.workers.contact_sync import sync_all_contacts

        config = MagicMock()
        config.user_id = uuid4()
        config.last_sync_at = None
        config.sync_interval = 5
        config.consecutive_errors = 0
        config.last_error_at = None

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [config]
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.flush = AsyncMock()

        with (
            patch("app.workers.contact_sync.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch(
                "app.workers.contact_sync.sync_contacts",
                new_callable=AsyncMock,
                side_effect=RuntimeError("CardDAV error"),
            ),
        ):
            await sync_all_contacts({})

            assert config.consecutive_errors == 1
            assert config.last_error is not None

    @pytest.mark.asyncio
    async def test_config_sync_circuit_breaker_tripped(self):
        """Repeated failures trip circuit breaker (lines 95-101)."""
        from app.workers.contact_sync import sync_all_contacts

        config = MagicMock()
        config.user_id = uuid4()
        config.last_sync_at = None
        config.sync_interval = 5
        config.consecutive_errors = 9  # will become 10
        config.last_error_at = None
        config.is_active = True

        mock_db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [config]
        mock_db.execute = AsyncMock(return_value=result)
        mock_db.flush = AsyncMock()

        settings = MagicMock()
        settings.contact_sync_max_errors = 10

        with (
            patch("app.workers.contact_sync.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch("app.workers.contact_sync.sync_contacts", new_callable=AsyncMock, side_effect=RuntimeError("fail")),
            patch("app.workers.contact_sync.get_settings", return_value=settings),
        ):
            await sync_all_contacts({})

            assert config.is_active is False
            assert config.consecutive_errors == 10


# ===========================================================================
# draft_monitor: cleanup_all_drafts (lines 30-64)
# ===========================================================================


class TestCleanupAllDrafts:
    @pytest.mark.asyncio
    async def test_no_active_drafts_returns_early(self):
        """No accounts with active drafts → early return (lines 46-48)."""
        from app.workers.draft_monitor import cleanup_all_drafts

        mock_db = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result)

        settings = MagicMock()
        settings.draft_expiry_days = 7

        with (
            patch("app.workers.draft_monitor.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch("app.workers.draft_monitor.get_settings", return_value=settings),
        ):
            await cleanup_all_drafts({})

    @pytest.mark.asyncio
    async def test_paused_account_skipped(self):
        """Paused account is skipped (lines 58-59)."""
        from app.workers.draft_monitor import cleanup_all_drafts

        account_id = uuid4()
        mock_db = AsyncMock()

        # First execute: account_ids query
        ids_result = MagicMock()
        ids_result.all.return_value = [(account_id,)]

        # Second execute: account lookup returns None (paused/not found)
        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = None

        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ids_result
            return acct_result

        mock_db.execute = AsyncMock(side_effect=_execute)

        settings = MagicMock()
        settings.draft_expiry_days = 7

        with (
            patch("app.workers.draft_monitor.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch("app.workers.draft_monitor.get_settings", return_value=settings),
            patch("app.workers.draft_monitor.cleanup_drafts_for_account", new_callable=AsyncMock) as mock_cleanup,
        ):
            await cleanup_all_drafts({})
            mock_cleanup.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_runs_for_active_account(self):
        """Active account triggers cleanup (lines 61-66)."""
        from app.workers.draft_monitor import cleanup_all_drafts

        account_id = uuid4()
        account = _make_account(account_id=account_id)

        mock_db = AsyncMock()

        ids_result = MagicMock()
        ids_result.all.return_value = [(account_id,)]

        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = account

        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ids_result
            return acct_result

        mock_db.execute = AsyncMock(side_effect=_execute)

        settings = MagicMock()
        settings.draft_expiry_days = 7

        with (
            patch("app.workers.draft_monitor.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch("app.workers.draft_monitor.get_settings", return_value=settings),
            patch(
                "app.workers.draft_monitor.cleanup_drafts_for_account",
                new_callable=AsyncMock,
                return_value={"deleted": 3, "expired": 1},
            ) as mock_cleanup,
            patch("app.workers.draft_monitor.worker_error_handler") as mock_weh,
        ):
            # Make worker_error_handler a passthrough async context manager
            @asynccontextmanager
            async def _weh(db, account_id, *, operation=""):
                yield

            mock_weh.side_effect = _weh

            await cleanup_all_drafts({})
            mock_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_no_stats_no_log(self):
        """Cleanup with all-zero stats doesn't log (line 63 false branch)."""
        from app.workers.draft_monitor import cleanup_all_drafts

        account_id = uuid4()
        account = _make_account(account_id=account_id)

        mock_db = AsyncMock()

        ids_result = MagicMock()
        ids_result.all.return_value = [(account_id,)]

        acct_result = MagicMock()
        acct_result.scalar_one_or_none.return_value = account

        call_count = 0

        async def _execute(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ids_result
            return acct_result

        mock_db.execute = AsyncMock(side_effect=_execute)

        settings = MagicMock()
        settings.draft_expiry_days = 7

        with (
            patch("app.workers.draft_monitor.get_session_ctx", _mock_get_session_ctx(mock_db)),
            patch("app.workers.draft_monitor.get_settings", return_value=settings),
            patch(
                "app.workers.draft_monitor.cleanup_drafts_for_account",
                new_callable=AsyncMock,
                return_value={"deleted": 0, "expired": 0},
            ),
            patch("app.workers.draft_monitor.worker_error_handler") as mock_weh,
        ):

            @asynccontextmanager
            async def _weh(db, account_id, *, operation=""):
                yield

            mock_weh.side_effect = _weh

            await cleanup_all_drafts({})
