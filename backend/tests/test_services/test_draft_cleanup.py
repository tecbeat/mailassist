"""Tests for draft cleanup service (test area 12).

Covers all state transitions: active -> superseded, active -> deleted,
active -> expired, and error handling.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from app.models import AIDraft, DraftStatus
from app.services.draft_cleanup import (
    cleanup_drafts_for_account,
    _get_sent_message_ids,
    _draft_exists_in_imap,
    _delete_draft_from_imap,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_draft(
    status=DraftStatus.ACTIVE,
    created_at=None,
    original_message_id="msg-123@example.com",
    draft_uid="42",
    **kwargs,
):
    """Create a mock AIDraft ORM object."""
    d = MagicMock(spec=AIDraft)
    d.id = uuid4()
    d.status = status
    d.created_at = created_at or datetime.now(UTC)
    d.original_message_id = original_message_id
    d.draft_uid = draft_uid
    d.mail_account_id = uuid4()
    d.cleaned_at = None
    for k, v in kwargs.items():
        setattr(d, k, v)
    return d


def _make_account():
    """Create a mock MailAccount."""
    account = MagicMock()
    account.id = uuid4()
    account.imap_host = "imap.example.com"
    account.imap_port = 993
    account.encrypted_credentials = b'{"username": "u", "password": "p"}'
    return account


def _make_imap_response(result="OK", lines=None):
    resp = MagicMock()
    resp.result = result
    resp.lines = lines or []
    return resp


@asynccontextmanager
async def _async_ctx(value):
    """Trivial async context manager that yields *value*."""
    yield value


def _mock_settings():
    """Return a mock settings object with draft-related attributes."""
    s = MagicMock()
    s.draft_sent_folder_names = "Sent,INBOX.Sent"
    s.draft_folder_names = "Drafts,INBOX.Drafts"
    s.draft_lookback_days = 7
    s.draft_max_sent_scan = 200
    return s


# ---------------------------------------------------------------------------
# Test Area 12: Draft Cleanup State Transitions
# ---------------------------------------------------------------------------


class TestDraftCleanupTransitions:
    """Tests for cleanup_drafts_for_account."""

    @pytest.mark.asyncio
    async def test_no_active_drafts(self, mock_encryption):
        """No active drafts produces zero-stats with no IMAP connection."""
        account = _make_account()
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        stats = await cleanup_drafts_for_account(db, account)
        assert stats == {"superseded": 0, "deleted": 0, "expired": 0, "errors": 0}

    @pytest.mark.asyncio
    async def test_draft_superseded_by_user_reply(self, mock_encryption):
        """Draft is marked superseded when user sent a reply with matching In-Reply-To."""
        account = _make_account()
        draft = _make_draft(original_message_id="orig-msg-1")

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [draft]
        db.execute = AsyncMock(return_value=result)

        mock_conn = MagicMock()
        mock_conn.mailbox = AsyncMock()

        with (
            patch(
                "app.services.draft_cleanup.imap_connection",
                return_value=_async_ctx(mock_conn),
            ),
            patch(
                "app.services.draft_cleanup.resolve_folder",
                new_callable=AsyncMock,
                return_value="Drafts",
            ),
            patch("app.services.draft_cleanup.get_settings", return_value=_mock_settings()),
            patch(
                "app.services.draft_cleanup._get_sent_message_ids",
                new_callable=AsyncMock,
                return_value={"orig-msg-1", "other-msg"},
            ),
            patch(
                "app.services.draft_cleanup._delete_draft_from_imap",
                new_callable=AsyncMock,
            ),
        ):
            stats = await cleanup_drafts_for_account(db, account)

        assert draft.status == DraftStatus.SUPERSEDED
        assert draft.cleaned_at is not None
        assert stats["superseded"] == 1

    @pytest.mark.asyncio
    async def test_draft_deleted_manually(self, mock_encryption):
        """Draft is marked deleted when it no longer exists in IMAP Drafts."""
        account = _make_account()
        draft = _make_draft(original_message_id="orig-msg-2")

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [draft]
        db.execute = AsyncMock(return_value=result)

        mock_conn = MagicMock()
        mock_conn.mailbox = AsyncMock()

        with (
            patch(
                "app.services.draft_cleanup.imap_connection",
                return_value=_async_ctx(mock_conn),
            ),
            patch(
                "app.services.draft_cleanup.resolve_folder",
                new_callable=AsyncMock,
                return_value="Drafts",
            ),
            patch("app.services.draft_cleanup.get_settings", return_value=_mock_settings()),
            patch(
                "app.services.draft_cleanup._get_sent_message_ids",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "app.services.draft_cleanup._draft_exists_in_imap",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            stats = await cleanup_drafts_for_account(db, account)

        assert draft.status == DraftStatus.DELETED
        assert draft.cleaned_at is not None
        assert stats["deleted"] == 1

    @pytest.mark.asyncio
    async def test_draft_expired_by_age(self, mock_encryption):
        """Draft older than expiry threshold is deleted and marked expired."""
        account = _make_account()
        old_date = datetime.now(UTC) - timedelta(days=10)
        draft = _make_draft(original_message_id="orig-msg-3", created_at=old_date)

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [draft]
        db.execute = AsyncMock(return_value=result)

        mock_conn = MagicMock()
        mock_conn.mailbox = AsyncMock()

        with (
            patch(
                "app.services.draft_cleanup.imap_connection",
                return_value=_async_ctx(mock_conn),
            ),
            patch(
                "app.services.draft_cleanup.resolve_folder",
                new_callable=AsyncMock,
                return_value="Drafts",
            ),
            patch("app.services.draft_cleanup.get_settings", return_value=_mock_settings()),
            patch(
                "app.services.draft_cleanup._get_sent_message_ids",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "app.services.draft_cleanup._draft_exists_in_imap",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.services.draft_cleanup._delete_draft_from_imap",
                new_callable=AsyncMock,
            ),
        ):
            stats = await cleanup_drafts_for_account(db, account, expiry_days=7)

        assert draft.status == DraftStatus.EXPIRED
        assert draft.cleaned_at is not None
        assert stats["expired"] == 1

    @pytest.mark.asyncio
    async def test_recent_draft_not_expired(self, mock_encryption):
        """Draft younger than expiry threshold is left active."""
        account = _make_account()
        recent_date = datetime.now(UTC) - timedelta(days=1)
        draft = _make_draft(original_message_id="orig-msg-4", created_at=recent_date)

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [draft]
        db.execute = AsyncMock(return_value=result)

        mock_conn = MagicMock()
        mock_conn.mailbox = AsyncMock()

        with (
            patch(
                "app.services.draft_cleanup.imap_connection",
                return_value=_async_ctx(mock_conn),
            ),
            patch(
                "app.services.draft_cleanup.resolve_folder",
                new_callable=AsyncMock,
                return_value="Drafts",
            ),
            patch("app.services.draft_cleanup.get_settings", return_value=_mock_settings()),
            patch(
                "app.services.draft_cleanup._get_sent_message_ids",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch(
                "app.services.draft_cleanup._draft_exists_in_imap",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            stats = await cleanup_drafts_for_account(db, account, expiry_days=7)

        assert draft.status == DraftStatus.ACTIVE  # unchanged
        assert stats == {"superseded": 0, "deleted": 0, "expired": 0, "errors": 0}

    @pytest.mark.asyncio
    async def test_imap_connection_failure_counts_error(self, mock_encryption):
        """IMAP connection error is counted as an error, not a crash."""
        account = _make_account()
        draft = _make_draft()

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [draft]
        db.execute = AsyncMock(return_value=result)

        @asynccontextmanager
        async def _failing_ctx(_account):
            raise Exception("Connection refused")
            yield  # pragma: no cover

        with (
            patch(
                "app.services.draft_cleanup.imap_connection",
                side_effect=lambda a: _failing_ctx(a),
            ),
            patch("app.services.draft_cleanup.get_settings", return_value=_mock_settings()),
        ):
            stats = await cleanup_drafts_for_account(db, account)

        assert stats["errors"] == 1
        assert draft.status == DraftStatus.ACTIVE  # unchanged


# ---------------------------------------------------------------------------
# Test Area 12 supplement: helper functions
# ---------------------------------------------------------------------------


class TestDraftExistsInImap:

    @pytest.mark.asyncio
    async def test_draft_exists(self):
        """Returns True when UID is found in Drafts folder."""
        from app.services.mail import ImapConnection

        mb = MagicMock()
        mb.folder.set = MagicMock()
        mb.uids = MagicMock(return_value=["42"])
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test")

        result = await _draft_exists_in_imap(conn, "42", "Drafts")
        assert result is True
        mb.folder.set.assert_called_with("Drafts")

    @pytest.mark.asyncio
    async def test_draft_not_found(self):
        """Returns False when UID is not in Drafts folder."""
        from app.services.mail import ImapConnection

        mb = MagicMock()
        mb.folder.set = MagicMock(side_effect=Exception("folder not found"))
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test")

        result = await _draft_exists_in_imap(conn, "99", "Drafts")
        assert result is False


class TestDeleteDraftFromImap:

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Draft is deleted via mailbox.delete()."""
        from app.services.mail import ImapConnection

        mb = MagicMock()
        mb.folder.set = MagicMock()
        mb.delete = MagicMock()
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test")

        await _delete_draft_from_imap(conn, "42", "Drafts")
        mb.folder.set.assert_called_with("Drafts")
        mb.delete.assert_called_with("42")

    @pytest.mark.asyncio
    async def test_delete_no_drafts_folder(self):
        """Gracefully handles None drafts folder."""
        from app.services.mail import ImapConnection

        mb = MagicMock()
        conn = ImapConnection(mailbox=mb, account_id=uuid4(), host="test")

        # Should not raise — None folder means no-op
        await _delete_draft_from_imap(conn, "42", None)
