"""Tests for UID-not-found detection and mail relocation.

Covers:
- fetch_raw_message raising uid_not_found_in_folder vs no_message_body_in_response
- relocate_mail_across_folders searching other folders by subject
- FetchResult dataclass and fetch_raw_mail relocation flow
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.mail import (
    ImapConnection,
    RelocatedMail,
    fetch_raw_message,
    relocate_mail_across_folders,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(folders: list[str] | None = None) -> ImapConnection:
    """Build a mock ImapConnection."""
    mb = MagicMock()
    conn = ImapConnection(
        mailbox=mb,
        account_id=uuid4(),
        host="imap.example.com",
        separator="/",
    )
    return conn


# ---------------------------------------------------------------------------
# fetch_raw_message: uid_not_found_in_folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_raw_message_uid_not_found() -> None:
    """When IMAP returns [None], raise uid_not_found_in_folder."""
    conn = _make_conn()
    conn.mailbox.client.uid.return_value = ("OK", [None])

    with pytest.raises(ValueError, match="uid_not_found_in_folder"):
        await fetch_raw_message(conn, "449", folder="INBOX")


@pytest.mark.asyncio
async def test_fetch_raw_message_no_body() -> None:
    """When IMAP returns OK but no tuple data, raise no_message_body_in_response."""
    conn = _make_conn()
    # Return non-None data that doesn't contain a tuple with 2 elements
    conn.mailbox.client.uid.return_value = ("OK", [b"some garbage"])

    with pytest.raises(ValueError, match="no_message_body_in_response"):
        await fetch_raw_message(conn, "449", folder="INBOX")


@pytest.mark.asyncio
async def test_fetch_raw_message_success() -> None:
    """Normal fetch returns raw bytes."""
    conn = _make_conn()
    raw = b"From: test@example.com\r\nSubject: Hello\r\n\r\nBody"
    conn.mailbox.client.uid.return_value = ("OK", [(b"1 FETCH (RFC822 {123})", raw), b")"])

    result = await fetch_raw_message(conn, "449", folder="INBOX")
    assert result == raw


# ---------------------------------------------------------------------------
# relocate_mail_across_folders
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relocate_mail_found() -> None:
    """Relocation finds the mail in another folder."""
    conn = _make_conn()
    raw = b"From: test@example.com\r\nSubject: Backup\r\n\r\nBody"

    # Mock list_folders
    folder_infos = [MagicMock(name=f, flags=("\\HasNoChildren",)) for f in ["INBOX", "Server/Backups", "Trash"]]
    for fi, name in zip(folder_infos, ["INBOX", "Server/Backups", "Trash"], strict=True):
        fi.name = name
    conn.mailbox.folder.list.return_value = iter(folder_infos)

    # Mock uids() — returns results only for Server/Backups
    def mock_uids(criteria: object) -> list[str]:
        # Check which folder was set
        last_set_call = conn.mailbox.folder.set.call_args
        if last_set_call and last_set_call[0][0] == "Server/Backups":
            return ["7"]
        return []

    conn.mailbox.uids = mock_uids

    # Mock fetch_raw_message success for the relocated UID
    conn.mailbox.client.uid.return_value = ("OK", [(b"7 FETCH (RFC822 {45})", raw), b")"])

    result = await relocate_mail_across_folders(
        conn,
        "Backup",
        "INBOX",
    )

    assert result is not None
    assert result.folder == "Server/Backups"
    assert result.uid == "7"
    assert result.raw_bytes == raw


@pytest.mark.asyncio
async def test_relocate_mail_not_found() -> None:
    """Relocation returns None when mail is not in any folder."""
    conn = _make_conn()

    folder_infos = [MagicMock(name="Trash", flags=("\\HasNoChildren",))]
    folder_infos[0].name = "Trash"
    conn.mailbox.folder.list.return_value = iter(folder_infos)
    conn.mailbox.uids = lambda _criteria: []

    result = await relocate_mail_across_folders(
        conn,
        "Backup",
        "INBOX",
    )

    assert result is None


@pytest.mark.asyncio
async def test_relocate_mail_empty_subject() -> None:
    """Relocation returns None immediately with empty subject."""
    conn = _make_conn()

    result = await relocate_mail_across_folders(
        conn,
        "",
        "INBOX",
    )

    assert result is None


# ---------------------------------------------------------------------------
# FetchResult / fetch_raw_mail integration (pipeline_orchestrator)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_raw_mail_uid_not_found_with_relocation() -> None:
    """fetch_raw_mail relocates mail when UID vanishes and subject_hint given."""
    from app.workers.pipeline_orchestrator import FetchResult, fetch_raw_mail

    raw = b"From: test@example.com\r\nSubject: Hello\r\n\r\nBody"
    mock_account = MagicMock()
    mock_account.id = uuid4()
    mock_account.imap_host = "imap.example.com"
    mock_account.imap_port = 993
    mock_account.imap_use_ssl = True
    mock_account.encrypted_credentials = b"fake"

    relocated = RelocatedMail(folder="Server/Backups", uid="7", raw_bytes=raw)

    log = MagicMock()
    log.info = MagicMock()
    log.warning = MagicMock()

    with (
        patch("app.workers.pipeline_orchestrator.imap_connection") as mock_ctx,
        patch("app.workers.pipeline_orchestrator.fetch_raw_message") as mock_fetch,
        patch("app.workers.pipeline_orchestrator.relocate_mail_across_folders") as mock_relocate,
        patch("app.workers.pipeline_orchestrator.get_cached_folders", return_value=["INBOX", "Server/Backups"]),
    ):
        mock_fetch.side_effect = ValueError("uid_not_found_in_folder")
        mock_relocate.return_value = relocated

        mock_conn = MagicMock()
        mock_conn.separator = "/"
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await fetch_raw_mail(
            mock_account,
            "449",
            "INBOX",
            log,
            subject_hint="Hello",
        )

    assert isinstance(result, FetchResult)
    assert result.relocated is True
    assert result.new_folder == "Server/Backups"
    assert result.new_uid == "7"
    assert result.raw_bytes == raw


@pytest.mark.asyncio
async def test_fetch_raw_mail_uid_not_found_no_relocation() -> None:
    """fetch_raw_mail raises UIDNotFoundError when relocation fails."""
    from app.workers.pipeline_orchestrator import UIDNotFoundError, fetch_raw_mail

    mock_account = MagicMock()
    mock_account.id = uuid4()
    mock_account.imap_host = "imap.example.com"
    mock_account.imap_port = 993
    mock_account.imap_use_ssl = True
    mock_account.encrypted_credentials = b"fake"

    log = MagicMock()
    log.info = MagicMock()
    log.warning = MagicMock()

    with (
        patch("app.workers.pipeline_orchestrator.imap_connection") as mock_ctx,
        patch("app.workers.pipeline_orchestrator.fetch_raw_message") as mock_fetch,
        patch("app.workers.pipeline_orchestrator.relocate_mail_across_folders") as mock_relocate,
    ):
        mock_fetch.side_effect = ValueError("uid_not_found_in_folder")
        mock_relocate.return_value = None

        mock_conn = MagicMock()
        mock_conn.separator = "/"
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(UIDNotFoundError):
            await fetch_raw_mail(
                mock_account,
                "449",
                "INBOX",
                log,
                subject_hint="Hello",
            )
