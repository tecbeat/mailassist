"""Tests for detached account handling in IDLE monitor.

Verifies that MailAccount objects are expunged from the session before
use outside the session context, preventing DetachedInstanceError.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_account():
    account = MagicMock()
    account.id = uuid4()
    account.user_id = uuid4()
    account.imap_host = "imap.example.com"
    return account


def _mock_session(account):
    """Return an async-generator mock that yields a session with the account."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = account
    db.execute = AsyncMock(return_value=result)
    db.expunge = MagicMock()

    async def _gen():
        yield db

    return _gen, db


@pytest.mark.asyncio
async def test_idle_loop_expunges_account_before_session_close():
    """_idle_loop must call db.expunge(account) after loading from DB."""
    account = _make_account()
    gen_fn, db = _mock_session(account)

    # Patch connect_imap to raise so the loop exits after the first reload
    with (
        patch("app.workers.idle_monitor.get_session", gen_fn),
        patch("app.workers.idle_monitor.connect_imap", side_effect=StopIteration),
        patch("app.workers.idle_monitor.update_account_sync_status"),
        patch("app.workers.idle_monitor.check_circuit_breaker", return_value=True),
    ):
        from app.workers.idle_monitor import _idle_loop

        await _idle_loop(account)

    db.expunge.assert_called_once_with(account)


@pytest.mark.asyncio
async def test_start_idle_manager_expunges_accounts():
    """start_idle_manager must expunge all loaded accounts."""
    accounts = [_make_account(), _make_account()]

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = accounts
    db.execute = AsyncMock(return_value=result)
    db.expunge = MagicMock()

    async def _gen():
        yield db

    with (
        patch("app.workers.idle_monitor.get_session", _gen),
        patch("app.workers.idle_monitor.start_idle_for_account", new_callable=AsyncMock),
    ):
        from app.workers.idle_monitor import start_idle_manager

        await start_idle_manager()

    assert db.expunge.call_count == len(accounts)
    for acct in accounts:
        db.expunge.assert_any_call(acct)
