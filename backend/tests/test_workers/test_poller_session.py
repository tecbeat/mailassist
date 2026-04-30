"""Tests for DB session isolation during IMAP polling.

Verifies that _poll_single_account does not hold a DB session open
during IMAP I/O operations.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_account(*, initial_scan_done=True, scan_existing_emails=False):
    return SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        imap_host="imap.example.com",
        imap_port=993,
        imap_use_ssl=True,
        encrypted_credentials=b"fake",
        initial_scan_done=initial_scan_done,
        scan_existing_emails=scan_existing_emails,
        excluded_folders=None,
        is_paused=False,
        idle_enabled=False,
        polling_enabled=True,
    )


def _tracking_session_open_during_imap():
    """Return a get_session_ctx mock that tracks whether a session was open during IMAP."""
    sessions_opened = []
    sessions_closed = []

    @asynccontextmanager
    async def _gen():
        db = AsyncMock()
        db.expunge = MagicMock()
        sessions_opened.append(datetime.now(UTC))
        yield db
        sessions_closed.append(datetime.now(UTC))

    return _gen, sessions_opened, sessions_closed


@pytest.mark.asyncio
async def test_poll_single_account_does_not_hold_session_during_imap():
    """The DB session must not be held open while IMAP I/O is in progress."""
    account = _make_account()

    # Track whether get_session is called inside connect_imap
    session_held_during_imap = False
    session_stack = 0

    original_get_session = None

    @asynccontextmanager
    async def mock_get_session_ctx():
        nonlocal session_stack
        db = AsyncMock()
        db.expunge = MagicMock()
        session_stack += 1
        yield db
        session_stack -= 1

    async def mock_connect_imap(acct):
        nonlocal session_held_during_imap
        # If a session is still open when IMAP connect happens, that's the bug
        if session_stack > 0:
            session_held_during_imap = True
        conn = MagicMock()
        conn.mailbox = MagicMock()
        conn.capabilities = ["IMAP4rev1"]
        return conn

    async def mock_search_uids(conn, folder, criteria):
        if session_stack > 0:
            session_held_during_imap = True
        return []

    with (
        patch("app.workers.mail_poller.get_session_ctx", mock_get_session_ctx),
        patch("app.workers.mail_poller.connect_imap", mock_connect_imap),
        patch("app.workers.mail_poller.search_uids", mock_search_uids),
        patch("app.workers.mail_poller.safe_imap_logout", new_callable=AsyncMock),
        patch("app.workers.mail_poller.is_idle_active", return_value=False),
        patch("app.workers.mail_poller.update_account_sync_status", new_callable=AsyncMock),
    ):
        from app.workers.mail_poller import _poll_single_account

        await _poll_single_account(account)

    assert not session_held_during_imap, (
        "DB session was still open during IMAP I/O — "
        "this can exhaust the connection pool under load"
    )


def test_poll_single_account_signature_has_no_db_param():
    """_poll_single_account must not accept a db parameter (sessions are short-lived)."""
    import inspect
    from app.workers.mail_poller import _poll_single_account

    sig = inspect.signature(_poll_single_account)
    param_names = list(sig.parameters.keys())
    assert "db" not in param_names, (
        "_poll_single_account should not accept a db parameter"
    )
