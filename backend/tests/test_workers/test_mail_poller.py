"""Tests for mail_poller — verifying correct UID handling and scan behaviour.

The poller uses ``imap-tools`` which returns real IMAP UIDs directly
from ``mailbox.uids()`` — no sequence-number-to-UID resolution needed.

Tests cover:
* **Normal polling** (``initial_scan_done=True``): INBOX only, ``SEARCH UNSEEN``.
* **Initial scan** (``scan_existing_emails=True``): all folders (minus
  ``excluded_folders``), ``SEARCH ALL``.
* **Initial scan skipped** (``scan_existing_emails=False``): immediately
  marks ``initial_scan_done``, then INBOX ``SEARCH UNSEEN``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.mail_poller import _poll_single_account, _get_new_uids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(
    *,
    account_id=None,
    user_id=None,
    initial_scan_done=True,
    scan_existing_emails=False,
    excluded_folders=None,
):
    """Create a minimal mock MailAccount for polling tests."""
    account = MagicMock()
    account.id = account_id or uuid4()
    account.user_id = user_id or uuid4()
    account.name = "Test Account"
    account.email_address = "test@example.com"
    account.imap_host = "imap.example.com"
    account.imap_port = 993
    account.is_paused = False
    account.initial_scan_done = initial_scan_done
    account.scan_existing_emails = scan_existing_emails
    account.excluded_folders = excluded_folders or []
    account.encrypted_credentials = b"fake"
    account.polling_interval_minutes = 5
    account.consecutive_errors = 0
    account.last_error = None
    account.last_error_at = None
    account.last_sync_at = None
    account.idle_enabled = False
    return account


def _make_mock_conn():
    """Create a mock ImapConnection with a mock MailBox."""
    conn = MagicMock()
    conn.mailbox = MagicMock()
    conn.separator = "/"
    conn.capabilities = ["IMAP4rev1", "IDLE", "UIDPLUS"]
    return conn


# ---------------------------------------------------------------------------
# Integration tests for _poll_single_account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poller_uses_search_uids_and_fetch_envelopes():
    """Poller should use search_uids() and fetch_envelopes() from mail.py."""
    account = _make_account()
    mock_conn = _make_mock_conn()
    mock_db = AsyncMock()

    with (
        patch("app.workers.mail_poller.connect_imap", new_callable=AsyncMock, return_value=mock_conn),
        patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
        patch("app.workers.mail_poller.search_uids", new_callable=AsyncMock) as mock_search,
        patch("app.workers.mail_poller.fetch_envelopes", new_callable=AsyncMock) as mock_envelopes,
        patch("app.workers.mail_poller._get_new_uids", new_callable=AsyncMock) as mock_get_new,
        patch("app.workers.mail_poller._insert_tracked_batch", return_value=3) as mock_insert,
        patch("app.workers.mail_poller.timed_operation") as mock_timed,
        patch("app.workers.mail_poller.worker_error_handler") as mock_error_handler,
    ):
        mock_search.return_value = ["501", "502", "503"]
        mock_get_new.return_value = ["501", "502", "503"]
        mock_envelopes.return_value = {
            "501": ("Subject A", None, None),
            "502": ("Subject B", None, None),
            "503": ("Subject C", None, None),
        }
        mock_timed.return_value.__aenter__ = AsyncMock()
        mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_error_handler.return_value.__aenter__ = AsyncMock()
        mock_error_handler.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_single_account(mock_db, account)

        # search_uids called with UNSEEN for normal polling
        mock_search.assert_called_once_with(mock_conn, folder="INBOX", criteria="UNSEEN")

        # fetch_envelopes called with the UIDs
        mock_envelopes.assert_called_once()
        assert mock_envelopes.call_args[0][1] == ["501", "502", "503"]

        # _insert_tracked_batch received real UIDs
        mock_insert.assert_called_once()
        inserted_uids = mock_insert.call_args[0][3]
        assert inserted_uids == ["501", "502", "503"]


@pytest.mark.asyncio
async def test_poller_skips_idle_enabled_accounts():
    """Poller should skip accounts with idle_enabled after initial scan."""
    account = _make_account(initial_scan_done=True)
    account.idle_enabled = True

    mock_db = AsyncMock()

    with (
        patch("app.workers.mail_poller.connect_imap") as mock_connect,
        patch("app.workers.mail_poller.timed_operation") as mock_timed,
        patch("app.workers.mail_poller.worker_error_handler") as mock_error_handler,
    ):
        mock_timed.return_value.__aenter__ = AsyncMock()
        mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_error_handler.return_value.__aenter__ = AsyncMock()
        mock_error_handler.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_single_account(mock_db, account)

        # IMAP should never be called — account skipped
        mock_connect.assert_not_called()


@pytest.mark.asyncio
async def test_poller_subtracts_already_tracked_uids():
    """Poller should skip UIDs that are already in tracked_emails."""
    account = _make_account()
    mock_conn = _make_mock_conn()
    mock_db = AsyncMock()

    with (
        patch("app.workers.mail_poller.connect_imap", new_callable=AsyncMock, return_value=mock_conn),
        patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
        patch("app.workers.mail_poller.search_uids", new_callable=AsyncMock) as mock_search,
        patch("app.workers.mail_poller.fetch_envelopes", new_callable=AsyncMock) as mock_envelopes,
        # UIDs 100 and 300 are already tracked, only 200 and 400 are new
        patch("app.workers.mail_poller._get_new_uids", new_callable=AsyncMock) as mock_get_new,
        patch("app.workers.mail_poller._insert_tracked_batch", return_value=2) as mock_insert,
        patch("app.workers.mail_poller.timed_operation") as mock_timed,
        patch("app.workers.mail_poller.worker_error_handler") as mock_error_handler,
    ):
        mock_search.return_value = ["100", "200", "300", "400"]
        mock_get_new.return_value = ["200", "400"]
        mock_envelopes.return_value = {
            "200": (None, None, None),
            "400": (None, None, None),
        }
        mock_timed.return_value.__aenter__ = AsyncMock()
        mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_error_handler.return_value.__aenter__ = AsyncMock()
        mock_error_handler.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_single_account(mock_db, account)

        # Only new UIDs should be inserted
        mock_insert.assert_called_once()
        inserted_uids = mock_insert.call_args[0][3]
        assert inserted_uids == ["200", "400"]


@pytest.mark.asyncio
async def test_poller_handles_empty_mailbox():
    """Poller should handle empty mailbox gracefully."""
    account = _make_account()
    mock_conn = _make_mock_conn()
    mock_db = AsyncMock()

    with (
        patch("app.workers.mail_poller.connect_imap", new_callable=AsyncMock, return_value=mock_conn),
        patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
        patch("app.workers.mail_poller.search_uids", new_callable=AsyncMock) as mock_search,
        patch("app.workers.mail_poller._insert_tracked_batch") as mock_insert,
        patch("app.workers.mail_poller.timed_operation") as mock_timed,
        patch("app.workers.mail_poller.worker_error_handler") as mock_error_handler,
    ):
        mock_search.return_value = []
        mock_timed.return_value.__aenter__ = AsyncMock()
        mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_error_handler.return_value.__aenter__ = AsyncMock()
        mock_error_handler.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_single_account(mock_db, account)

        # No insertion should happen for empty mailbox
        mock_insert.assert_not_called()


# ---------------------------------------------------------------------------
# Scan behaviour tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_normal_polling_uses_inbox_unseen():
    """After initial scan, poller should search INBOX with UNSEEN."""
    account = _make_account(initial_scan_done=True)
    mock_conn = _make_mock_conn()
    mock_db = AsyncMock()

    with (
        patch("app.workers.mail_poller.connect_imap", new_callable=AsyncMock, return_value=mock_conn),
        patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
        patch("app.workers.mail_poller.search_uids", new_callable=AsyncMock) as mock_search,
        patch("app.workers.mail_poller._get_new_uids", new_callable=AsyncMock) as mock_get_new,
        patch("app.workers.mail_poller.fetch_envelopes", new_callable=AsyncMock) as mock_envelopes,
        patch("app.workers.mail_poller._insert_tracked_batch", return_value=1),
        patch("app.workers.mail_poller.timed_operation") as mock_timed,
        patch("app.workers.mail_poller.worker_error_handler") as mock_error_handler,
    ):
        mock_search.return_value = ["10"]
        mock_get_new.return_value = ["10"]
        mock_envelopes.return_value = {"10": (None, None, None)}
        mock_timed.return_value.__aenter__ = AsyncMock()
        mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_error_handler.return_value.__aenter__ = AsyncMock()
        mock_error_handler.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_single_account(mock_db, account)

        mock_search.assert_called_once_with(mock_conn, folder="INBOX", criteria="UNSEEN")


@pytest.mark.asyncio
async def test_initial_scan_skipped_when_scan_existing_false():
    """When scan_existing_emails=False, initial scan should be skipped."""
    account = _make_account(initial_scan_done=False, scan_existing_emails=False)
    mock_conn = _make_mock_conn()
    mock_db = AsyncMock()

    with (
        patch("app.workers.mail_poller.connect_imap", new_callable=AsyncMock, return_value=mock_conn),
        patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
        patch("app.workers.mail_poller.search_uids", new_callable=AsyncMock) as mock_search,
        patch("app.workers.mail_poller._get_new_uids", new_callable=AsyncMock) as mock_get_new,
        patch("app.workers.mail_poller.fetch_envelopes", new_callable=AsyncMock) as mock_envelopes,
        patch("app.workers.mail_poller._insert_tracked_batch", return_value=2),
        patch("app.workers.mail_poller.timed_operation") as mock_timed,
        patch("app.workers.mail_poller.worker_error_handler") as mock_error_handler,
    ):
        mock_search.return_value = ["20", "21"]
        mock_get_new.return_value = ["20", "21"]
        mock_envelopes.return_value = {"20": (None, None, None), "21": (None, None, None)}
        mock_timed.return_value.__aenter__ = AsyncMock()
        mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_error_handler.return_value.__aenter__ = AsyncMock()
        mock_error_handler.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_single_account(mock_db, account)

        # Should mark initial_scan_done immediately and poll INBOX UNSEEN
        assert account.initial_scan_done is True
        mock_search.assert_called_once_with(mock_conn, folder="INBOX", criteria="UNSEEN")


@pytest.mark.asyncio
async def test_initial_scan_iterates_all_folders():
    """When scan_existing_emails=True, initial scan should list folders, skip excluded, and poll each."""
    account = _make_account(
        initial_scan_done=False,
        scan_existing_emails=True,
        excluded_folders=["Trash", "Spam"],
    )
    mock_conn = _make_mock_conn()
    mock_db = AsyncMock()

    with (
        patch("app.workers.mail_poller.connect_imap", new_callable=AsyncMock, return_value=mock_conn),
        patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
        patch("app.workers.mail_poller.list_folders", new_callable=AsyncMock) as mock_list,
        patch("app.workers.mail_poller.search_uids", new_callable=AsyncMock) as mock_search,
        patch("app.workers.mail_poller._get_new_uids", new_callable=AsyncMock) as mock_get_new,
        patch("app.workers.mail_poller.fetch_envelopes", new_callable=AsyncMock) as mock_envelopes,
        patch("app.workers.mail_poller._insert_tracked_batch", return_value=1) as mock_insert,
        patch("app.workers.mail_poller.timed_operation") as mock_timed,
        patch("app.workers.mail_poller.worker_error_handler") as mock_error_handler,
    ):
        mock_list.return_value = ["INBOX", "Sent", "Archive", "Trash", "Spam"]
        mock_search.return_value = ["100"]
        mock_get_new.return_value = ["100"]
        mock_envelopes.return_value = {"100": (None, None, None)}
        mock_timed.return_value.__aenter__ = AsyncMock()
        mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_error_handler.return_value.__aenter__ = AsyncMock()
        mock_error_handler.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_single_account(mock_db, account)

        # list_folders should be called once
        mock_list.assert_called_once_with(mock_conn)

        # search_uids should be called for INBOX, Sent, Archive (not Trash, Spam)
        assert mock_search.call_count == 3
        search_folders = [c[1]["folder"] for c in mock_search.call_args_list]
        assert search_folders == ["INBOX", "Sent", "Archive"]

        # SEARCH ALL should be used for every folder during initial scan
        for call in mock_search.call_args_list:
            assert call[1]["criteria"] == "ALL"

        # _insert_tracked_batch should be called 3 times (one per folder)
        assert mock_insert.call_count == 3

        # Verify current_folder kwarg is set correctly for each call
        insert_folders = [c[1].get("current_folder") for c in mock_insert.call_args_list]
        assert insert_folders == ["INBOX", "Sent", "Archive"]

        # initial_scan_done should be set
        assert account.initial_scan_done is True


@pytest.mark.asyncio
async def test_initial_scan_excludes_all_folders():
    """Initial scan with all folders excluded should skip gracefully."""
    account = _make_account(
        initial_scan_done=False,
        scan_existing_emails=True,
        excluded_folders=["INBOX", "Sent"],
    )
    mock_conn = _make_mock_conn()
    mock_db = AsyncMock()

    with (
        patch("app.workers.mail_poller.connect_imap", new_callable=AsyncMock, return_value=mock_conn),
        patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
        patch("app.workers.mail_poller.list_folders", new_callable=AsyncMock) as mock_list,
        patch("app.workers.mail_poller._insert_tracked_batch") as mock_insert,
        patch("app.workers.mail_poller.timed_operation") as mock_timed,
        patch("app.workers.mail_poller.worker_error_handler") as mock_error_handler,
    ):
        mock_list.return_value = ["INBOX", "Sent"]
        mock_timed.return_value.__aenter__ = AsyncMock()
        mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_error_handler.return_value.__aenter__ = AsyncMock()
        mock_error_handler.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_single_account(mock_db, account)

        # No folders to scan after exclusion — no inserts
        mock_insert.assert_not_called()
        # But initial_scan_done should still be set
        assert account.initial_scan_done is True


@pytest.mark.asyncio
async def test_initial_scan_sets_correct_current_folder():
    """Initial scan should pass the correct folder name to _insert_tracked_batch."""
    account = _make_account(initial_scan_done=False, scan_existing_emails=True)
    mock_conn = _make_mock_conn()
    mock_db = AsyncMock()

    with (
        patch("app.workers.mail_poller.connect_imap", new_callable=AsyncMock, return_value=mock_conn),
        patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
        patch("app.workers.mail_poller.list_folders", new_callable=AsyncMock) as mock_list,
        patch("app.workers.mail_poller.search_uids", new_callable=AsyncMock) as mock_search,
        patch("app.workers.mail_poller._get_new_uids", new_callable=AsyncMock) as mock_get_new,
        patch("app.workers.mail_poller.fetch_envelopes", new_callable=AsyncMock) as mock_envelopes,
        patch("app.workers.mail_poller._insert_tracked_batch", return_value=1) as mock_insert,
        patch("app.workers.mail_poller.timed_operation") as mock_timed,
        patch("app.workers.mail_poller.worker_error_handler") as mock_error_handler,
    ):
        mock_list.return_value = ["Archive"]
        mock_search.return_value = ["50"]
        mock_get_new.return_value = ["50"]
        mock_envelopes.return_value = {"50": (None, None, None)}
        mock_timed.return_value.__aenter__ = AsyncMock()
        mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_error_handler.return_value.__aenter__ = AsyncMock()
        mock_error_handler.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_single_account(mock_db, account)

        mock_insert.assert_called_once()
        assert mock_insert.call_args[1]["current_folder"] == "Archive"


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestScanExistingEmailsSchema:
    """Verify Pydantic schemas handle scan_existing_emails correctly."""

    def test_create_schema_default(self):
        from app.schemas.mail_account import MailAccountCreate

        data = MailAccountCreate(
            name="Test",
            email_address="a@b.com",
            imap_host="imap.b.com",
            username="user",
            password="pass",
        )
        assert data.scan_existing_emails is False

    def test_create_schema_explicit_true(self):
        from app.schemas.mail_account import MailAccountCreate

        data = MailAccountCreate(
            name="Test",
            email_address="a@b.com",
            imap_host="imap.b.com",
            username="user",
            password="pass",
            scan_existing_emails=True,
        )
        assert data.scan_existing_emails is True

    def test_update_schema_accepts_scan_existing_emails(self):
        from app.schemas.mail_account import MailAccountUpdate

        data = MailAccountUpdate(scan_existing_emails=True)
        assert data.scan_existing_emails is True

    def test_update_schema_scan_existing_emails_optional(self):
        from app.schemas.mail_account import MailAccountUpdate

        data = MailAccountUpdate(name="New Name")
        assert data.scan_existing_emails is None

    def test_response_schema_includes_scan_existing_emails(self):
        from app.schemas.mail_account import MailAccountResponse
        from datetime import datetime, UTC

        resp = MailAccountResponse(
            id="00000000-0000-0000-0000-000000000001",
            name="Test",
            email_address="a@b.com",
            imap_host="imap.b.com",
            imap_port=993,
            imap_use_ssl=True,
            polling_enabled=True,
            polling_interval_minutes=5,
            idle_enabled=True,
            is_paused=False,
            initial_scan_done=True,
            scan_existing_emails=False,
            excluded_folders=None,
            last_sync_at=None,
            last_error=None,
            last_error_at=None,
            consecutive_errors=0,
            manually_paused=False,
            paused_reason=None,
            paused_at=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert resp.scan_existing_emails is False


# ---------------------------------------------------------------------------
# Folder-aware UID deduplication tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_new_uids_passes_folder_to_query():
    """_get_new_uids should include current_folder in the SQL filter."""
    from app.workers.mail_poller import _get_new_uids

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [("42",)]
    mock_db.execute = AsyncMock(return_value=mock_result)

    result = await _get_new_uids(mock_db, str(uuid4()), ["42"], folder="Sent")

    assert result == ["42"]
    # Verify the folder was passed in the query parameters
    call_args = mock_db.execute.call_args
    params = call_args[0][1]
    assert params["folder"] == "Sent"


@pytest.mark.asyncio
async def test_initial_scan_passes_folder_to_get_new_uids():
    """Initial scan should pass the folder name to _get_new_uids."""
    account = _make_account(initial_scan_done=False, scan_existing_emails=True)
    mock_conn = _make_mock_conn()
    mock_db = AsyncMock()

    with (
        patch("app.workers.mail_poller.connect_imap", new_callable=AsyncMock, return_value=mock_conn),
        patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
        patch("app.workers.mail_poller.list_folders", new_callable=AsyncMock) as mock_list,
        patch("app.workers.mail_poller.search_uids", new_callable=AsyncMock) as mock_search,
        patch("app.workers.mail_poller._get_new_uids", new_callable=AsyncMock) as mock_get_new,
        patch("app.workers.mail_poller.fetch_envelopes", new_callable=AsyncMock) as mock_envelopes,
        patch("app.workers.mail_poller._insert_tracked_batch", return_value=1),
        patch("app.workers.mail_poller.timed_operation") as mock_timed,
        patch("app.workers.mail_poller.worker_error_handler") as mock_error_handler,
    ):
        mock_list.return_value = ["INBOX", "Sent"]
        mock_search.return_value = ["77"]
        mock_get_new.return_value = ["77"]
        mock_envelopes.return_value = {"77": (None, None, None)}
        mock_timed.return_value.__aenter__ = AsyncMock()
        mock_timed.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_error_handler.return_value.__aenter__ = AsyncMock()
        mock_error_handler.return_value.__aexit__ = AsyncMock(return_value=False)

        await _poll_single_account(mock_db, account)

        # _get_new_uids should be called once per folder with the folder kwarg
        assert mock_get_new.call_count == 2
        folders_passed = [c[1]["folder"] for c in mock_get_new.call_args_list]
        assert folders_passed == ["INBOX", "Sent"]


# ---------------------------------------------------------------------------
# list_folders Noselect filtering tests
# ---------------------------------------------------------------------------


class TestListFoldersNoselect:
    """Verify list_folders filters out \\Noselect container folders.

    Note: list_folders now uses imap-tools' folder.list() which returns
    FolderInfo objects. These tests mock at the imap-tools level.
    """

    @pytest.mark.asyncio
    async def test_filters_noselect_folders(self):
        from app.services.mail import list_folders, ImapConnection
        import asyncio

        # Create mock FolderInfo objects as returned by imap-tools
        def _make_folder(name, flags=""):
            f = MagicMock()
            f.name = name
            f.flags = flags
            return f

        mock_mailbox = MagicMock()
        folders = [
            _make_folder("INBOX", "\\HasChildren"),
            _make_folder("Sent", "\\HasNoChildren"),
            _make_folder("[Gmail]", "\\Noselect \\HasChildren"),
            _make_folder("[Gmail].All Mail", "\\HasNoChildren"),
            _make_folder("Container", "\\Noselect"),
            _make_folder("Archive", "\\HasNoChildren"),
        ]
        mock_mailbox.folder.list.return_value = folders

        conn = ImapConnection(mailbox=mock_mailbox, account_id=uuid4(), host="test")

        # Patch to_thread to run synchronously
        with patch("app.services.mail.asyncio.to_thread", side_effect=lambda fn, *a, **kw: fn(*a, **kw)):
            result = await list_folders(conn)

        assert "INBOX" in result
        assert "Sent" in result
        assert "[Gmail].All Mail" in result
        assert "Archive" in result
        # Noselect folders should be excluded
        assert "[Gmail]" not in result
        assert "Container" not in result
