"""Tests for folder-aware IMAP operations (Issue #23).

Verifies that execute_imap_actions correctly uses the source_folder
parameter and returns the move destination.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.services.imap_actions import (
    ActionKind,
    execute_imap_actions,
    parse_action,
)
from app.services.mail import MoveResult


class TestParseAction:
    """parse_action handles move actions correctly."""

    def test_move_to(self):
        pa = parse_action("move_to:Work/Projects")
        assert pa.kind is ActionKind.MOVE_TO
        assert pa.value == "Work/Projects"

    def test_move_to_spam(self):
        pa = parse_action("move_to_spam")
        assert pa.kind is ActionKind.MOVE_TO_SPAM
        assert pa.value is None

    def test_mark_as_read(self):
        pa = parse_action("mark_as_read")
        assert pa.kind is ActionKind.MARK_AS_READ

    def test_apply_label(self):
        pa = parse_action("apply_label:important")
        assert pa.kind is ActionKind.APPLY_LABEL
        assert pa.value == "important"


class TestExecuteImapActionsSourceFolder:
    """execute_imap_actions uses source_folder correctly."""

    @pytest.mark.asyncio
    async def test_source_folder_used_for_select(self):
        """source_folder is passed to store_flags as folder parameter."""
        mock_conn = MagicMock()
        mock_conn.mailbox = MagicMock()
        mock_conn.capabilities = ["MOVE"]

        account = MagicMock()
        account.id = "test-account-id"

        with (
            patch("app.services.imap_actions.connect_imap", return_value=mock_conn),
            patch("app.services.imap_actions.store_flags", return_value=True) as mock_store,
        ):
            result = await execute_imap_actions(
                account,
                "123",
                ["mark_as_read"],
                source_folder="Work/Projects",
            )

        # store_flags should be called with folder="Work/Projects"
        mock_store.assert_called_once_with(mock_conn, "123", ["\\Seen"], folder="Work/Projects")
        # No move happened
        assert result.folder is None

    @pytest.mark.asyncio
    async def test_returns_destination_on_move(self):
        """Returns the destination folder after a successful move."""
        mock_conn = MagicMock()
        mock_conn.mailbox = MagicMock()
        mock_conn.capabilities = ["MOVE"]

        account = MagicMock()
        account.id = "test-account-id"

        with (
            patch("app.services.imap_actions.connect_imap", return_value=mock_conn),
            patch(
                "app.services.imap_actions.move_message", return_value=MoveResult(success=True, new_uid="456")
            ) as mock_move,
            patch("app.services.imap_actions.store_flags", return_value=True),
        ):
            result = await execute_imap_actions(
                account,
                "123",
                ["mark_as_read", "move_to:Archive"],
                source_folder="INBOX",
            )

        assert result.folder == "Archive"
        assert result.new_uid == "456"
        mock_move.assert_called_once_with(mock_conn, "123", "Archive", source="INBOX")

    @pytest.mark.asyncio
    async def test_returns_none_on_failed_move(self):
        """Returns None when the move fails."""
        mock_conn = MagicMock()
        mock_conn.mailbox = MagicMock()
        mock_conn.capabilities = ["MOVE"]

        account = MagicMock()
        account.id = "test-account-id"

        with (
            patch("app.services.imap_actions.connect_imap", return_value=mock_conn),
            patch("app.services.imap_actions.move_message", return_value=MoveResult(success=False)),
        ):
            result = await execute_imap_actions(
                account,
                "123",
                ["move_to:Archive"],
                source_folder="INBOX",
            )

        assert result.folder is None

    @pytest.mark.asyncio
    async def test_select_inbox_overrides_source_folder(self):
        """select_inbox=True overrides source_folder for backward compat."""
        mock_conn = MagicMock()
        mock_conn.mailbox = MagicMock()
        mock_conn.capabilities = []

        account = MagicMock()
        account.id = "test-account-id"

        with (
            patch("app.services.imap_actions.connect_imap", return_value=mock_conn),
            patch("app.services.imap_actions.store_flags", return_value=True) as mock_store,
        ):
            await execute_imap_actions(
                account,
                "123",
                ["mark_as_read"],
                source_folder="Work/Projects",
                select_inbox=True,
            )

        # select_inbox=True should override source_folder to "INBOX"
        mock_store.assert_called_once_with(mock_conn, "123", ["\\Seen"], folder="INBOX")

    @pytest.mark.asyncio
    async def test_returns_none_for_non_imap_actions(self):
        """Returns None when there are no IMAP actions."""
        account = MagicMock()
        account.id = "test-account-id"

        result = await execute_imap_actions(
            account,
            "123",
            ["store_summary"],
            source_folder="INBOX",
        )

        assert result.folder is None
