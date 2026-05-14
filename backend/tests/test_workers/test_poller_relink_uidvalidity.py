"""Integration tests for UIDVALIDITY reset with Message-ID deduplication.

Verifies that _relink_uids_by_message_id correctly updates stale UIDs
and that _poll_folder triggers relinking when uidvalidity changes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.mail_poller import _relink_uids_by_message_id


def _make_tracked(mail_uid: str, message_id: str | None, uidvalidity: int) -> MagicMock:
    t = MagicMock()
    t.mail_uid = mail_uid
    t.message_id = message_id
    t.current_folder = "INBOX"
    t.uidvalidity = uidvalidity
    return t


# ---------------------------------------------------------------------------
# _relink_uids_by_message_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.workers.mail_poller.get_session_ctx")
@patch("app.services.mail.fetch_message_ids", new_callable=AsyncMock)
async def test_relink_updates_uid_and_uidvalidity(
    mock_fetch_mids: AsyncMock,
    mock_session_ctx: MagicMock,
) -> None:
    """Relink updates mail_uid, current_folder, and uidvalidity for matched rows."""
    conn = AsyncMock()
    account_id = uuid4()

    # Old tracked row: UID "100", message_id "<abc@x>", uidvalidity 1
    tracked = _make_tracked("100", "<abc@x>", 1)

    # IMAP now reports UID "200" has message_id "<abc@x>"
    mock_fetch_mids.return_value = {"200": "<abc@x>", "201": "<other@x>"}

    # Mock DB session
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [tracked]
    db.execute = AsyncMock(return_value=result_mock)
    db.flush = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_ctx.return_value = ctx

    relinked = await _relink_uids_by_message_id(conn, account_id, "INBOX", ["200", "201"], new_uidvalidity=2)

    assert relinked == 1
    assert tracked.mail_uid == "200"
    assert tracked.current_folder == "INBOX"
    assert tracked.uidvalidity == 2
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.workers.mail_poller.get_session_ctx")
@patch("app.services.mail.fetch_message_ids", new_callable=AsyncMock)
async def test_relink_skips_when_uid_unchanged(
    mock_fetch_mids: AsyncMock,
    mock_session_ctx: MagicMock,
) -> None:
    """No relinking when tracked row already has the correct UID."""
    conn = AsyncMock()
    tracked = _make_tracked("200", "<abc@x>", 2)

    mock_fetch_mids.return_value = {"200": "<abc@x>"}

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [tracked]
    db.execute = AsyncMock(return_value=result_mock)
    db.flush = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_ctx.return_value = ctx

    relinked = await _relink_uids_by_message_id(conn, uuid4(), "INBOX", ["200"], new_uidvalidity=2)

    assert relinked == 0
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
@patch("app.workers.mail_poller.get_session_ctx")
@patch("app.services.mail.fetch_message_ids", new_callable=AsyncMock)
async def test_relink_returns_zero_when_no_message_ids(
    mock_fetch_mids: AsyncMock,
    mock_session_ctx: MagicMock,
) -> None:
    """Returns 0 immediately when IMAP returns no Message-IDs."""
    conn = AsyncMock()
    mock_fetch_mids.return_value = {"200": None, "201": None}

    relinked = await _relink_uids_by_message_id(conn, uuid4(), "INBOX", ["200", "201"], new_uidvalidity=5)

    assert relinked == 0
    # DB session should never be opened
    mock_session_ctx.assert_not_called()


@pytest.mark.asyncio
@patch("app.workers.mail_poller.get_session_ctx")
@patch("app.services.mail.fetch_message_ids", new_callable=AsyncMock)
async def test_relink_skips_tracked_with_none_message_id(
    mock_fetch_mids: AsyncMock,
    mock_session_ctx: MagicMock,
) -> None:
    """Tracked rows with message_id=None are skipped even if returned by query."""
    conn = AsyncMock()
    tracked = _make_tracked("100", None, 1)

    mock_fetch_mids.return_value = {"200": "<abc@x>"}

    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalars.return_value.all.return_value = [tracked]
    db.execute = AsyncMock(return_value=result_mock)
    db.flush = AsyncMock()

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_ctx.return_value = ctx

    relinked = await _relink_uids_by_message_id(conn, uuid4(), "INBOX", ["200"], new_uidvalidity=2)

    assert relinked == 0
    db.flush.assert_not_awaited()
