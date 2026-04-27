"""Tests for move_all_to_inbox batch move logic.

Verifies that move_all_to_inbox uses batch MOVE (or COPY+DELETE+EXPUNGE)
instead of per-message operations, avoiding UID invalidation issues.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.mail import ImapConnection, move_all_to_inbox


def _make_conn(*, uids: list[str], capabilities: list[str] | None = None) -> ImapConnection:
    """Build a mock ImapConnection with a fake mailbox client."""
    mb = MagicMock()
    mb.uids.return_value = uids
    mb.folder.set = MagicMock()
    mb.client.uid = MagicMock(return_value=("OK", [b"1 2 3"]))
    mb.client.expunge = MagicMock()

    conn = ImapConnection(
        mailbox=mb,
        account_id=uuid4(),
        user_id=uuid4(),
        capabilities=capabilities or ["IMAP4rev1", "MOVE", "UIDPLUS"],
    )
    return conn


class TestMoveAllToInbox:
    """Verify batch move semantics."""

    @pytest.mark.asyncio
    async def test_empty_folder_returns_empty(self) -> None:
        conn = _make_conn(uids=[])
        result = await move_all_to_inbox(conn, "Spam")
        assert result == []

    @pytest.mark.asyncio
    async def test_batch_move_with_move_capability(self) -> None:
        conn = _make_conn(uids=["1", "2", "3"])
        result = await move_all_to_inbox(conn, "Spam")

        assert result == ["1", "2", "3"]
        # Should use a single UID MOVE with comma-joined UIDs
        conn.mailbox.client.uid.assert_called_with("MOVE", "1,2,3", "INBOX")
        # EXPUNGE should NOT be called (MOVE is atomic)
        conn.mailbox.client.expunge.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_to_copy_delete_expunge(self) -> None:
        """Without MOVE capability, falls back to COPY+DELETE+EXPUNGE."""
        conn = _make_conn(uids=["10", "20"], capabilities=["IMAP4rev1", "UIDPLUS"])

        result = await move_all_to_inbox(conn, "Junk")

        assert result == ["10", "20"]
        calls = conn.mailbox.client.uid.call_args_list
        # Should be: COPY, STORE (delete flags) — both batched
        assert calls[0].args == ("COPY", "10,20", "INBOX")
        assert calls[1].args == ("STORE", "10,20", "+FLAGS", "(\\Deleted)")
        # Single expunge at the end
        conn.mailbox.client.expunge.assert_called_once()

    @pytest.mark.asyncio
    async def test_copy_failure_returns_empty(self) -> None:
        conn = _make_conn(uids=["1"], capabilities=["IMAP4rev1"])
        conn.mailbox.client.uid.return_value = ("NO", [b""])

        result = await move_all_to_inbox(conn, "Spam")
        assert result == []
