"""Tests for app.services.draft_upload — compose, append, and upload flow.

Covers: _compose_reply (subject prefixing, threading headers, addresses),
_append_to_drafts (APPENDUID parsing, failure), upload_draft_to_imap
(empty body, connect failure, no drafts folder, successful upload with
DB tracking, tracking failure, no message_id skips tracking).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

MODULE = "app.services.draft_upload"


# ---------------------------------------------------------------------------
# _compose_reply
# ---------------------------------------------------------------------------


def test_compose_reply_adds_re_prefix_when_missing() -> None:
    from app.services.draft_upload import _compose_reply

    msg, msg_id = _compose_reply(
        draft_body="Hello",
        original_subject="Meeting tomorrow",
        original_from="bob@example.com",
        original_message_id=None,
        original_references=None,
        account_email="me@example.com",
    )
    assert msg["Subject"] == "Re: Meeting tomorrow"
    assert msg["From"] == "me@example.com"
    assert msg["To"] == "bob@example.com"
    assert msg_id  # non-empty


def test_compose_reply_keeps_existing_re_prefix() -> None:
    from app.services.draft_upload import _compose_reply

    msg, _ = _compose_reply(
        draft_body="Hi",
        original_subject="Re: Meeting",
        original_from=None,
        original_message_id=None,
        original_references=None,
        account_email="me@example.com",
    )
    assert msg["Subject"] == "Re: Meeting"
    assert msg["To"] is None


def test_compose_reply_none_subject_becomes_re_empty() -> None:
    from app.services.draft_upload import _compose_reply

    msg, _ = _compose_reply(
        draft_body="Hi",
        original_subject=None,
        original_from=None,
        original_message_id=None,
        original_references=None,
        account_email="me@example.com",
    )
    assert msg["Subject"] == "Re: "


def test_compose_reply_threading_headers() -> None:
    from app.services.draft_upload import _compose_reply

    msg, _ = _compose_reply(
        draft_body="reply",
        original_subject="Test",
        original_from="a@b.com",
        original_message_id="<orig-123>",
        original_references=["<ref-1>", "<ref-2>"],
        account_email="me@example.com",
    )
    assert msg["In-Reply-To"] == "<orig-123>"
    assert "<ref-1>" in msg["References"]
    assert "<ref-2>" in msg["References"]
    assert "<orig-123>" in msg["References"]
    assert msg["X-Mailer"] == "mailassist-ai-draft"


# ---------------------------------------------------------------------------
# _append_to_drafts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_append_to_drafts_extracts_uid_from_appenduid() -> None:
    from app.services.draft_upload import _append_to_drafts

    conn = MagicMock()
    conn.mailbox.client.append.return_value = (
        "OK",
        [b"[APPENDUID 1234 5678] APPEND completed"],
    )

    uid = await _append_to_drafts(conn, "Drafts", b"message")
    assert uid == "5678"


@pytest.mark.asyncio
async def test_append_to_drafts_returns_none_when_no_appenduid() -> None:
    from app.services.draft_upload import _append_to_drafts

    conn = MagicMock()
    conn.mailbox.client.append.return_value = ("OK", [b"APPEND completed"])

    uid = await _append_to_drafts(conn, "Drafts", b"message")
    assert uid is None


@pytest.mark.asyncio
async def test_append_to_drafts_raises_on_failure() -> None:
    from app.services.draft_upload import _append_to_drafts

    conn = MagicMock()
    conn.mailbox.client.append.return_value = ("NO", [b"error"])

    with pytest.raises(RuntimeError, match="IMAP APPEND failed"):
        await _append_to_drafts(conn, "Drafts", b"message")


# ---------------------------------------------------------------------------
# upload_draft_to_imap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(f"{MODULE}.get_settings")
async def test_upload_draft_empty_body_returns_none(mock_settings: MagicMock) -> None:
    from app.services.draft_upload import upload_draft_to_imap

    account = MagicMock()
    account.id = uuid4()
    result = await upload_draft_to_imap(
        account=account,
        user_id=uuid4(),
        mail_uid="100",
        draft_body="",
    )
    assert result is None


@pytest.mark.asyncio
@patch(f"{MODULE}.connect_imap", new_callable=AsyncMock, side_effect=ConnectionError("fail"))
@patch(f"{MODULE}.get_settings")
async def test_upload_draft_connect_failure_returns_none(
    mock_settings: MagicMock,
    mock_connect: AsyncMock,
) -> None:
    from app.services.draft_upload import upload_draft_to_imap

    mock_settings.return_value.draft_folder_names = "Drafts,Entwürfe"
    account = MagicMock()
    account.id = uuid4()
    account.email_address = "me@example.com"

    result = await upload_draft_to_imap(
        account=account,
        user_id=uuid4(),
        mail_uid="100",
        draft_body="Hello",
    )
    assert result is None


@pytest.mark.asyncio
@patch(f"{MODULE}.safe_imap_logout", new_callable=AsyncMock)
@patch(f"{MODULE}.resolve_folder", new_callable=AsyncMock, return_value=None)
@patch(f"{MODULE}.connect_imap", new_callable=AsyncMock)
@patch(f"{MODULE}.get_settings")
async def test_upload_draft_no_drafts_folder_returns_none(
    mock_settings: MagicMock,
    mock_connect: AsyncMock,
    mock_resolve: AsyncMock,
    mock_logout: AsyncMock,
) -> None:
    from app.services.draft_upload import upload_draft_to_imap

    mock_settings.return_value.draft_folder_names = "Drafts"
    account = MagicMock()
    account.id = uuid4()
    account.email_address = "me@example.com"

    result = await upload_draft_to_imap(
        account=account,
        user_id=uuid4(),
        mail_uid="100",
        draft_body="Hello",
    )
    assert result is None
    mock_logout.assert_awaited_once()


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
@patch(f"{MODULE}.safe_imap_logout", new_callable=AsyncMock)
@patch(f"{MODULE}._append_to_drafts", new_callable=AsyncMock, return_value="999")
@patch(f"{MODULE}.resolve_folder", new_callable=AsyncMock, return_value="Drafts")
@patch(f"{MODULE}.connect_imap", new_callable=AsyncMock)
@patch(f"{MODULE}.get_settings")
async def test_upload_draft_success_tracks_in_db(
    mock_settings: MagicMock,
    mock_connect: AsyncMock,
    mock_resolve: AsyncMock,
    mock_append: AsyncMock,
    mock_logout: AsyncMock,
    mock_session_ctx: MagicMock,
) -> None:
    from app.services.draft_upload import upload_draft_to_imap

    mock_settings.return_value.draft_folder_names = "Drafts"
    account = MagicMock()
    account.id = uuid4()
    account.email_address = "me@example.com"

    # Mock DB session for tracking
    db = AsyncMock()
    te_result = MagicMock()
    te_scalars = MagicMock()
    te_scalars.first.return_value = uuid4()  # tracked_email_id
    te_result.scalars.return_value = te_scalars
    db.execute.return_value = te_result

    ctx = AsyncMock()
    ctx.__aenter__.return_value = db
    ctx.__aexit__.return_value = False
    mock_session_ctx.return_value = ctx

    result = await upload_draft_to_imap(
        account=account,
        user_id=uuid4(),
        mail_uid="100",
        draft_body="Hello",
        original_message_id="<orig@example.com>",
    )
    assert result == "999"
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
@patch(f"{MODULE}.safe_imap_logout", new_callable=AsyncMock)
@patch(f"{MODULE}._append_to_drafts", new_callable=AsyncMock, return_value="999")
@patch(f"{MODULE}.resolve_folder", new_callable=AsyncMock, return_value="Drafts")
@patch(f"{MODULE}.connect_imap", new_callable=AsyncMock)
@patch(f"{MODULE}.get_settings")
async def test_upload_draft_tracking_no_tracked_email_skips(
    mock_settings: MagicMock,
    mock_connect: AsyncMock,
    mock_resolve: AsyncMock,
    mock_append: AsyncMock,
    mock_logout: AsyncMock,
    mock_session_ctx: MagicMock,
) -> None:
    from app.services.draft_upload import upload_draft_to_imap

    mock_settings.return_value.draft_folder_names = "Drafts"
    account = MagicMock()
    account.id = uuid4()
    account.email_address = "me@example.com"

    db = AsyncMock()
    te_result = MagicMock()
    te_scalars = MagicMock()
    te_scalars.first.return_value = None  # no tracked email
    te_result.scalars.return_value = te_scalars
    db.execute.return_value = te_result

    ctx = AsyncMock()
    ctx.__aenter__.return_value = db
    ctx.__aexit__.return_value = False
    mock_session_ctx.return_value = ctx

    result = await upload_draft_to_imap(
        account=account,
        user_id=uuid4(),
        mail_uid="100",
        draft_body="Hello",
        original_message_id="<orig@example.com>",
    )
    assert result == "999"
    db.add.assert_not_called()


@pytest.mark.asyncio
@patch(f"{MODULE}.safe_imap_logout", new_callable=AsyncMock)
@patch(f"{MODULE}._append_to_drafts", new_callable=AsyncMock, return_value="999")
@patch(f"{MODULE}.resolve_folder", new_callable=AsyncMock, return_value="Drafts")
@patch(f"{MODULE}.connect_imap", new_callable=AsyncMock)
@patch(f"{MODULE}.get_settings")
async def test_upload_draft_no_message_id_skips_tracking(
    mock_settings: MagicMock,
    mock_connect: AsyncMock,
    mock_resolve: AsyncMock,
    mock_append: AsyncMock,
    mock_logout: AsyncMock,
) -> None:
    from app.services.draft_upload import upload_draft_to_imap

    mock_settings.return_value.draft_folder_names = "Drafts"
    account = MagicMock()
    account.id = uuid4()
    account.email_address = "me@example.com"

    result = await upload_draft_to_imap(
        account=account,
        user_id=uuid4(),
        mail_uid="100",
        draft_body="Hello",
        original_message_id=None,
    )
    assert result == "999"


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx", side_effect=RuntimeError("db down"))
@patch(f"{MODULE}.safe_imap_logout", new_callable=AsyncMock)
@patch(f"{MODULE}._append_to_drafts", new_callable=AsyncMock, return_value="999")
@patch(f"{MODULE}.resolve_folder", new_callable=AsyncMock, return_value="Drafts")
@patch(f"{MODULE}.connect_imap", new_callable=AsyncMock)
@patch(f"{MODULE}.get_settings")
async def test_upload_draft_tracking_db_error_still_returns_uid(
    mock_settings: MagicMock,
    mock_connect: AsyncMock,
    mock_resolve: AsyncMock,
    mock_append: AsyncMock,
    mock_logout: AsyncMock,
    mock_session_ctx: MagicMock,
) -> None:
    """Tracking failure is non-fatal — draft UID is still returned."""
    from app.services.draft_upload import upload_draft_to_imap

    mock_settings.return_value.draft_folder_names = "Drafts"
    account = MagicMock()
    account.id = uuid4()
    account.email_address = "me@example.com"

    result = await upload_draft_to_imap(
        account=account,
        user_id=uuid4(),
        mail_uid="100",
        draft_body="Hello",
        original_message_id="<orig@example.com>",
    )
    assert result == "999"
