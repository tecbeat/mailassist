"""Comprehensive tests for app.services.spam — report_as_spam and report_contact_as_spam.

Covers the uncovered branches: IMAP move, folder update, contact deletion,
and error paths. Existing tests in test_spam_service.py already cover
_extract_domain, is_blocked, and get_blocklist_context.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.spam import report_as_spam, report_contact_as_spam

MODULE = "app.services.spam"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _upsert_side_effect(*created_flags: bool):
    """Return an async side_effect that yields True/False per call."""
    it = iter(created_flags)

    async def _inner(*_args, **_kwargs):
        return next(it)

    return _inner


# ---------------------------------------------------------------------------
# report_as_spam
# ---------------------------------------------------------------------------


class TestReportAsSpam:
    @pytest.mark.asyncio
    async def test_blocks_sender_and_domain_moves_mail(self) -> None:
        user_id = uuid4()
        account_id = uuid4()

        account = MagicMock()

        # DB execute calls:
        # 1. flush (auto)
        # 2. account lookup
        # 3. tracked folder lookup
        # 4. execute_imap_actions (patched separately)
        # 5. tracked email update lookup
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account

        tracked_folder_result = MagicMock()
        tracked_folder_result.scalars.return_value.first.return_value = "INBOX"

        tracked_update_result = MagicMock()
        tracked_obj = MagicMock()
        tracked_update_result.scalar_one_or_none.return_value = tracked_obj

        db = AsyncMock()
        db.execute.side_effect = [account_result, tracked_folder_result, tracked_update_result]

        @dataclass
        class _MoveOutcome:
            folder: str | None = "Spam"
            new_uid: str | None = "200"

        with (
            patch(
                f"{MODULE}._upsert_blocklist_entry", new_callable=AsyncMock, side_effect=[True, True]
            ) as _mock_upsert,
            patch(f"{MODULE}.execute_imap_actions", new_callable=AsyncMock, return_value=_MoveOutcome()) as mock_imap,
        ):
            result = await report_as_spam(db, user_id, account_id, "uid1", "spam@evil.com")

        assert result["blocked_entries_created"] == 2
        assert result["mail_moved"] is True
        assert "blocked" in result["message"]
        mock_imap.assert_awaited_once()
        # Folder and UID updated
        assert tracked_obj.current_folder == "Spam"
        assert tracked_obj.mail_uid == "200"
        db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_account_skips_imap_move(self) -> None:
        db = AsyncMock()
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = None
        db.execute.return_value = account_result

        with patch(f"{MODULE}._upsert_blocklist_entry", new_callable=AsyncMock, side_effect=[True, True]):
            result = await report_as_spam(db, uuid4(), uuid4(), "uid1", "x@y.com")

        assert result["mail_moved"] is False
        assert "could not be moved" in result["message"]

    @pytest.mark.asyncio
    async def test_imap_failure_still_blocks(self) -> None:
        account = MagicMock()
        db = AsyncMock()
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        tracked_folder_result = MagicMock()
        tracked_folder_result.scalars.return_value.first.return_value = None

        db.execute.side_effect = [account_result, tracked_folder_result]

        with (
            patch(f"{MODULE}._upsert_blocklist_entry", new_callable=AsyncMock, side_effect=[True, False]),
            patch(f"{MODULE}.execute_imap_actions", new_callable=AsyncMock, side_effect=ConnectionError("IMAP down")),
        ):
            result = await report_as_spam(db, uuid4(), uuid4(), "uid1", "a@b.com")

        assert result["blocked_entries_created"] == 1
        assert result["mail_moved"] is False

    @pytest.mark.asyncio
    async def test_move_outcome_no_folder_skips_tracked_update(self) -> None:
        account = MagicMock()
        db = AsyncMock()
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        tracked_folder_result = MagicMock()
        tracked_folder_result.scalars.return_value.first.return_value = "INBOX"
        db.execute.side_effect = [account_result, tracked_folder_result]

        @dataclass
        class _MoveOutcome:
            folder: str | None = None
            new_uid: str | None = None

        with (
            patch(f"{MODULE}._upsert_blocklist_entry", new_callable=AsyncMock, side_effect=[True, True]),
            patch(f"{MODULE}.execute_imap_actions", new_callable=AsyncMock, return_value=_MoveOutcome()),
        ):
            result = await report_as_spam(db, uuid4(), uuid4(), "uid1", "x@y.com")

        assert result["mail_moved"] is True
        # Only 2 execute calls (account + tracked folder), no update query
        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_no_domain_extracted(self) -> None:
        """Sender without @ only creates email blocklist entry."""
        db = AsyncMock()
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = None
        db.execute.return_value = account_result

        with patch(f"{MODULE}._upsert_blocklist_entry", new_callable=AsyncMock, return_value=True) as mock_upsert:
            result = await report_as_spam(db, uuid4(), uuid4(), "uid1", "nodomain")

        assert result["blocked_entries_created"] == 1
        # Only one upsert call (email), no domain
        assert mock_upsert.await_count == 1


# ---------------------------------------------------------------------------
# report_contact_as_spam
# ---------------------------------------------------------------------------


class TestReportContactAsSpam:
    @pytest.mark.asyncio
    async def test_contact_not_found_returns_message(self) -> None:
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        result = await report_contact_as_spam(db, uuid4(), uuid4())
        assert result["blocked_entries_created"] == 0
        assert "not found" in result["message"]

    @pytest.mark.asyncio
    async def test_blocks_all_emails_and_deletes_contact(self) -> None:
        contact = MagicMock()
        contact.emails = ["a@example.com", "b@example.com"]
        contact.display_name = "Spammer"

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = contact
        db.execute.return_value = result_mock

        # 4 upsert calls: email+domain for each of the 2 addresses
        with patch(f"{MODULE}._upsert_blocklist_entry", new_callable=AsyncMock, side_effect=[True, True, True, True]):
            result = await report_contact_as_spam(db, uuid4(), uuid4())

        assert result["blocked_entries_created"] == 4
        assert result["mail_moved"] is False
        assert "2 email(s) blocked" in result["message"]
        db.delete.assert_awaited_once_with(contact)
        db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_contact_with_no_emails(self) -> None:
        contact = MagicMock()
        contact.emails = []
        contact.display_name = "Empty"

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = contact
        db.execute.return_value = result_mock

        result = await report_contact_as_spam(db, uuid4(), uuid4())
        assert result["blocked_entries_created"] == 0
        assert "0 email(s) blocked" in result["message"]
        db.delete.assert_awaited_once_with(contact)

    @pytest.mark.asyncio
    async def test_duplicate_entries_not_counted(self) -> None:
        """When upsert returns False (already exists), created count stays 0."""
        contact = MagicMock()
        contact.emails = ["dup@evil.com"]
        contact.display_name = "Dup"

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = contact
        db.execute.return_value = result_mock

        with patch(f"{MODULE}._upsert_blocklist_entry", new_callable=AsyncMock, return_value=False):
            result = await report_contact_as_spam(db, uuid4(), uuid4())

        assert result["blocked_entries_created"] == 0
