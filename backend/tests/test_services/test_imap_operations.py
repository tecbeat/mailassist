"""Tests for IMAP operations (test areas 7, 8, 9).

Area 7: IMAP compatibility -- folder separators, encoding edge cases.
Area 8: IMAP folder creation -- nested folders, separator handling.
Area 9: IMAP label creation -- PERMANENTFLAGS check.

All tests mock imap-tools MailBox objects. The ImapConnection dataclass
holds a ``mailbox: MailBox`` field (not the old ``imap`` field).
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.mail import (
    ImapConnection,
    connect_imap,
    create_folder,
    get_permanent_flags,
    list_folders,
)

# ---------------------------------------------------------------------------
# imap-tools mock helpers
# ---------------------------------------------------------------------------


def _make_folder_info(name: str, delim: str = "/", flags: tuple = ("\\HasNoChildren",)):
    """Build a mock imap-tools FolderInfo object."""
    fi = MagicMock()
    fi.name = name
    fi.delim = delim
    fi.flags = flags
    return fi


def _make_mock_mailbox(
    *,
    folders: list | None = None,
    capabilities: list[bytes] | None = None,
    login_ok: bool = True,
):
    """Build a fully mocked imap-tools MailBox.

    Parameters:
        folders: List of FolderInfo mocks returned by ``folder.list()``.
        capabilities: Raw capability response for ``client.capability()``.
        login_ok: If False, ``login()`` raises an exception.
    """
    mb = MagicMock()

    # login
    if not login_ok:
        mb.login.side_effect = Exception("LOGIN failed: authentication error")

    # folder.list() returns FolderInfo objects
    if folders is None:
        folders = [_make_folder_info("INBOX")]
    mb.folder.list.return_value = iter(folders)
    mb.folder.set = MagicMock()
    mb.folder.create = MagicMock()

    # client.capability() returns (status, [data])
    if capabilities is None:
        capabilities = [b"IMAP4rev1 IDLE UIDPLUS"]
    mb.client.capability.return_value = ("OK", capabilities)
    mb.client.untagged_responses = {}

    mb.logout = MagicMock()

    return mb


def _make_mock_account(**overrides):
    """Build a mock MailAccount ORM object."""
    account = MagicMock()
    account.id = overrides.get("id", uuid4())
    account.user_id = overrides.get("user_id", uuid4())
    account.imap_host = overrides.get("imap_host", "imap.example.com")
    account.imap_port = overrides.get("imap_port", 993)
    account.imap_use_ssl = overrides.get("imap_use_ssl", True)
    account.encrypted_credentials = overrides.get(
        "encrypted_credentials",
        b'{"username": "user", "password": "pass"}',
    )
    return account


# ---------------------------------------------------------------------------
# Test Area 7: IMAP Compatibility
# ---------------------------------------------------------------------------


class TestImapCompatibility:
    """Different folder separators and capability detection."""

    @pytest.mark.asyncio
    async def test_slash_separator_detected(self, mock_encryption):
        """Standard '/' separator is detected from folder list."""
        mb = _make_mock_mailbox(
            folders=[_make_folder_info("INBOX", delim="/")],
        )

        with patch("app.services.mail.MailBox", return_value=mb):
            account = _make_mock_account()
            conn = await connect_imap(account)

        assert conn.separator == "/"

    @pytest.mark.asyncio
    async def test_dot_separator_detected(self, mock_encryption):
        """Dovecot-style '.' separator is detected from folder list."""
        mb = _make_mock_mailbox(
            folders=[_make_folder_info("INBOX", delim=".")],
        )

        with patch("app.services.mail.MailBox", return_value=mb):
            account = _make_mock_account()
            conn = await connect_imap(account)

        assert conn.separator == "."

    @pytest.mark.asyncio
    async def test_fallback_separator_on_list_error(self, mock_encryption):
        """Falls back to '/' when folder.list() fails."""
        mb = _make_mock_mailbox()
        mb.folder.list.side_effect = Exception("LIST failed")

        with patch("app.services.mail.MailBox", return_value=mb):
            account = _make_mock_account()
            conn = await connect_imap(account)

        assert conn.separator == "/"

    @pytest.mark.asyncio
    async def test_capabilities_parsed(self, mock_encryption):
        """IMAP capabilities are parsed from CAPABILITY response."""
        mb = _make_mock_mailbox(
            capabilities=[b"IMAP4rev1 IDLE UIDPLUS CONDSTORE"],
        )

        with patch("app.services.mail.MailBox", return_value=mb):
            account = _make_mock_account()
            conn = await connect_imap(account)

        assert "IDLE" in conn.capabilities
        assert "UIDPLUS" in conn.capabilities

    @pytest.mark.asyncio
    async def test_capabilities_fallback_on_error(self, mock_encryption):
        """Capabilities default to empty list on error."""
        mb = _make_mock_mailbox()
        mb.client.capability.side_effect = Exception("timeout")

        with patch("app.services.mail.MailBox", return_value=mb):
            account = _make_mock_account()
            conn = await connect_imap(account)

        assert conn.capabilities == []

    @pytest.mark.asyncio
    async def test_non_ssl_rejected(self, mock_encryption):
        """Unencrypted IMAP connections are explicitly rejected."""
        account = _make_mock_account(imap_use_ssl=False)
        with pytest.raises(ValueError, match="SSL/TLS required"):
            await connect_imap(account)

    @pytest.mark.asyncio
    async def test_login_failure_raises(self, mock_encryption):
        """Failed IMAP login raises an exception."""
        mb = _make_mock_mailbox(login_ok=False)

        with patch("app.services.mail.MailBox", return_value=mb):
            account = _make_mock_account()
            with pytest.raises(Exception, match="LOGIN failed"):
                await connect_imap(account)


class TestListFolders:
    """Folder listing from imap-tools folder.list()."""

    @pytest.mark.asyncio
    async def test_list_folders_standard(self):
        """Standard folder list is parsed correctly."""
        mb = MagicMock()
        mb.folder.list.return_value = iter(
            [
                _make_folder_info("INBOX"),
                _make_folder_info("Sent"),
                _make_folder_info("Work", flags=("\\HasChildren",)),
                _make_folder_info("Work/Projects"),
            ]
        )
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test", separator="/")
        folders = await list_folders(conn)
        assert "INBOX" in folders
        assert "Sent" in folders
        assert "Work" in folders
        assert "Work/Projects" in folders

    @pytest.mark.asyncio
    async def test_list_folders_noselect_excluded(self):
        """Folders with \\Noselect flag are excluded."""
        mb = MagicMock()
        mb.folder.list.return_value = iter(
            [
                _make_folder_info("INBOX"),
                _make_folder_info("Container", flags=("\\Noselect", "\\HasChildren")),
            ]
        )
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test", separator="/")
        folders = await list_folders(conn)
        assert "INBOX" in folders
        assert "Container" not in folders

    @pytest.mark.asyncio
    async def test_list_folders_empty(self):
        """Empty folder list returns empty list."""
        mb = MagicMock()
        mb.folder.list.return_value = iter([])
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test")
        folders = await list_folders(conn)
        assert folders == []


# ---------------------------------------------------------------------------
# Test Area 8: IMAP Folder Creation
# ---------------------------------------------------------------------------


class TestImapFolderCreation:
    """Nested folder creation with separator handling."""

    @pytest.mark.asyncio
    async def test_create_single_folder(self):
        """Creating a single-level folder sends one create call."""
        mb = MagicMock()
        mb.folder.create = MagicMock()
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test", separator="/")

        result = await create_folder(conn, "Archive")
        assert result is True
        mb.folder.create.assert_called_once_with("Archive")

    @pytest.mark.asyncio
    async def test_create_nested_folder_slash_separator(self):
        """Nested folder with '/' separator creates parent first, then child."""
        mb = MagicMock()
        mb.folder.create = MagicMock()
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test", separator="/")

        result = await create_folder(conn, "Work/Projects")
        assert result is True
        calls = mb.folder.create.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == "Work"
        assert calls[1].args[0] == "Work/Projects"

    @pytest.mark.asyncio
    async def test_create_nested_folder_dot_separator(self):
        """Nested folder with '.' separator creates parent first, then child."""
        mb = MagicMock()
        mb.folder.create = MagicMock()
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test", separator=".")

        result = await create_folder(conn, "Work.Projects.Active")
        assert result is True
        calls = mb.folder.create.call_args_list
        assert len(calls) == 3
        assert calls[0].args[0] == "Work"
        assert calls[1].args[0] == "Work.Projects"
        assert calls[2].args[0] == "Work.Projects.Active"

    @pytest.mark.asyncio
    async def test_create_folder_already_exists(self):
        """Folder already existing (ALREADYEXISTS) is treated as success."""
        mb = MagicMock()
        mb.folder.create = MagicMock(
            side_effect=Exception("[ALREADYEXISTS] Folder already exists"),
        )
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test", separator="/")

        result = await create_folder(conn, "Existing")
        assert result is True

    @pytest.mark.asyncio
    async def test_create_folder_fails(self):
        """Folder creation failure (non-ALREADYEXISTS) returns False."""
        mb = MagicMock()
        mb.folder.create = MagicMock(
            side_effect=Exception("Permission denied"),
        )
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test", separator="/")

        result = await create_folder(conn, "Forbidden")
        assert result is False


# ---------------------------------------------------------------------------
# Test Area 9: IMAP Label/PERMANENTFLAGS
# ---------------------------------------------------------------------------


class TestImapLabels:
    """PERMANENTFLAGS detection for custom keyword support."""

    @pytest.mark.asyncio
    async def test_permanent_flags_extracted(self):
        """PERMANENTFLAGS are parsed from the SELECT response issued by folder.set()."""
        mb = MagicMock()
        mb.folder.set = MagicMock()
        mb.client.untagged_responses = {
            "PERMANENTFLAGS": [b"(\\Seen \\Answered \\Flagged \\Deleted \\Draft \\*)"],
        }
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test")

        flags = await get_permanent_flags(conn, "INBOX")
        assert "\\Seen" in flags
        assert "\\*" in flags  # wildcard = custom keywords allowed

    @pytest.mark.asyncio
    async def test_permanent_flags_no_custom_keywords(self):
        """Server without \\* does not support custom keywords."""
        mb = MagicMock()
        mb.folder.set = MagicMock()
        mb.client.untagged_responses = {
            "PERMANENTFLAGS": [b"(\\Seen \\Answered \\Flagged \\Deleted \\Draft)"],
        }
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test")

        flags = await get_permanent_flags(conn, "INBOX")
        assert "\\*" not in flags
        assert "\\Seen" in flags

    @pytest.mark.asyncio
    async def test_permanent_flags_empty_response(self):
        """No PERMANENTFLAGS line returns empty list."""
        mb = MagicMock()
        mb.folder.set = MagicMock()
        mb.client.untagged_responses = {}
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test")

        flags = await get_permanent_flags(conn, "INBOX")
        assert flags == []

    @pytest.mark.asyncio
    async def test_permanent_flags_select_fails(self):
        """Failed SELECT (folder.set raises) returns empty flags list."""
        mb = MagicMock()
        mb.folder.set.side_effect = Exception("Folder not found")
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test")

        flags = await get_permanent_flags(conn, "NonExistent")
        assert flags == []
