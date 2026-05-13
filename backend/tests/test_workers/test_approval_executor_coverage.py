"""Comprehensive tests for approval_executor: _rebuild_actions, execute_approved_actions,
handle_spam_rejection, and remaining _persist_plugin_data branches.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import ApprovalStatus
from app.workers.approval_executor import (
    _persist_plugin_data,
    _rebuild_actions,
    execute_approved_actions,
    handle_spam_rejection,
)

MODULE = "app.workers.approval_executor"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_approval(
    *,
    function_type: str,
    ai_response_data: dict | None = None,
    edited_actions: dict | None = None,
    status: ApprovalStatus = ApprovalStatus.APPROVED,
) -> MagicMock:
    a = MagicMock()
    a.id = uuid4()
    a.user_id = uuid4()
    a.mail_id = uuid4()
    a.mail_from = "sender@example.com"
    a.mail_subject = "Test Subject"
    a.function_type = function_type
    a.ai_response_data = ai_response_data
    a.edited_actions = edited_actions
    a.status = status
    return a


def _make_tracked_email(*, mail_uid: str = "123", current_folder: str = "INBOX") -> MagicMock:
    t = MagicMock()
    t.id = uuid4()
    t.mail_uid = mail_uid
    t.mail_account_id = uuid4()
    t.current_folder = current_folder
    return t


def _fake_session_ctx(db: AsyncMock):
    @asynccontextmanager
    async def _ctx():
        yield db

    return _ctx


# ---------------------------------------------------------------------------
# _rebuild_actions
# ---------------------------------------------------------------------------


class TestRebuildActions:
    def test_smart_folder_with_folder(self) -> None:
        result = _rebuild_actions("smart_folder", {"folder": "Projects/Alpha"})
        assert result == [
            "create_folder:Projects/Alpha",
            "log_new_folder:Projects/Alpha",
            "move_to:Projects/Alpha",
        ]

    def test_smart_folder_with_destination(self) -> None:
        result = _rebuild_actions("smart_folder", {"destination": "Archive"})
        assert "move_to:Archive" in result

    def test_smart_folder_no_folder_returns_empty(self) -> None:
        assert _rebuild_actions("smart_folder", {}) == []

    def test_labeling_multiple_labels(self) -> None:
        result = _rebuild_actions("labeling", {"labels": ["urgent", "work"]})
        assert result == ["apply_label:urgent", "apply_label:work"]

    def test_labeling_single_label_fallback(self) -> None:
        result = _rebuild_actions("labeling", {"label_name": "important"})
        assert result == ["apply_label:important"]

    def test_labeling_label_key_fallback(self) -> None:
        result = _rebuild_actions("labeling", {"label": "misc"})
        assert result == ["apply_label:misc"]

    def test_labeling_no_labels_returns_empty(self) -> None:
        assert _rebuild_actions("labeling", {}) == []

    def test_spam_detection_is_spam(self) -> None:
        result = _rebuild_actions("spam_detection", {"is_spam": True})
        assert result == ["move_to_spam", "mark_as_read"]

    def test_spam_detection_not_spam(self) -> None:
        assert _rebuild_actions("spam_detection", {"is_spam": False}) == []

    def test_contacts_returns_empty(self) -> None:
        assert _rebuild_actions("contacts", {"contact_id": "x"}) == []

    def test_unknown_type_returns_empty(self) -> None:
        assert _rebuild_actions("unknown_plugin", {"foo": "bar"}) == []


# ---------------------------------------------------------------------------
# execute_approved_actions
# ---------------------------------------------------------------------------


class TestExecuteApprovedActions:
    @pytest.mark.asyncio
    async def test_approval_not_found_returns_early(self) -> None:
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        with patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db)):
            await execute_approved_actions({}, str(uuid4()))

        # Only one execute call (the approval lookup)
        assert db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_approval_not_approved_returns_early(self) -> None:
        approval = _make_approval(function_type="labeling", status=ApprovalStatus.PENDING)
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = approval
        db.execute.return_value = result_mock

        with patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db)):
            await execute_approved_actions({}, str(uuid4()))

        # Only one execute (approval lookup), no tracked email lookup
        assert db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_tracked_email_not_found_returns_early(self) -> None:
        approval = _make_approval(function_type="labeling")
        approval.proposed_action = {"actions": ["apply_label:x"]}
        approval.edited_actions = None

        db = AsyncMock()
        approval_result = MagicMock()
        approval_result.scalar_one_or_none.return_value = approval
        tracked_result = MagicMock()
        tracked_result.scalar_one_or_none.return_value = None

        db.execute.side_effect = [approval_result, tracked_result]

        with patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db)):
            await execute_approved_actions({}, str(uuid4()))

        assert db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_no_imap_actions_persists_data_only(self) -> None:
        """Data-only plugins (e.g. email_summary) skip IMAP and persist directly."""
        approval = _make_approval(
            function_type="email_summary",
            ai_response_data={"summary": "s", "key_points": []},
        )
        approval.proposed_action = {"actions": []}
        approval.edited_actions = None

        tracked = _make_tracked_email()
        db = AsyncMock()
        approval_result = MagicMock()
        approval_result.scalar_one_or_none.return_value = approval
        tracked_result = MagicMock()
        tracked_result.scalar_one_or_none.return_value = tracked
        db.execute.side_effect = [approval_result, tracked_result]

        with (
            patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db)),
            patch(f"{MODULE}._persist_plugin_data", new_callable=AsyncMock) as mock_persist,
        ):
            await execute_approved_actions({}, str(uuid4()))
            mock_persist.assert_awaited_once_with(approval)

    @pytest.mark.asyncio
    async def test_full_flow_with_move(self) -> None:
        """Full happy path: IMAP actions executed, folder updated, data persisted."""
        approval = _make_approval(function_type="smart_folder")
        approval.proposed_action = {"actions": [], "folder": "Work"}
        approval.edited_actions = None

        tracked = _make_tracked_email(mail_uid="42", current_folder="INBOX")
        account = MagicMock()

        db = AsyncMock()
        approval_result = MagicMock()
        approval_result.scalar_one_or_none.return_value = approval
        tracked_result = MagicMock()
        tracked_result.scalar_one_or_none.return_value = tracked
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        # After move: re-fetch tracked email for folder update
        tracked_update_result = MagicMock()
        tracked_update_obj = MagicMock()
        tracked_update_result.scalar_one_or_none.return_value = tracked_update_obj

        db.execute.side_effect = [
            approval_result,    # approval lookup
            tracked_result,     # tracked email lookup
            account_result,     # account lookup
            tracked_update_result,  # tracked email update lookup
        ]

        @dataclass
        class _MoveOutcome:
            folder: str | None = "Work"
            new_uid: str | None = "99"

        with (
            patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db)),
            patch(f"{MODULE}.execute_imap_actions", new_callable=AsyncMock, return_value=_MoveOutcome()) as mock_imap,
            patch(f"{MODULE}.save_new_labels", new_callable=AsyncMock),
            patch(f"{MODULE}.save_new_folders", new_callable=AsyncMock),
            patch(f"{MODULE}._persist_plugin_data", new_callable=AsyncMock) as mock_persist,
        ):
            await execute_approved_actions({}, str(approval.id))

            mock_imap.assert_awaited_once()
            # Folder and UID updated on tracked object
            assert tracked_update_obj.current_folder == "Work"
            assert tracked_update_obj.mail_uid == "99"
            mock_persist.assert_awaited_once_with(approval)

    @pytest.mark.asyncio
    async def test_edited_actions_triggers_rebuild(self) -> None:
        """When edited_actions is set, _rebuild_actions is called with edited source."""
        approval = _make_approval(function_type="labeling")
        approval.proposed_action = {"actions": ["apply_label:old"]}
        approval.edited_actions = {"labels": ["new_label"]}

        tracked = _make_tracked_email()
        account = MagicMock()

        db = AsyncMock()
        approval_result = MagicMock()
        approval_result.scalar_one_or_none.return_value = approval
        tracked_result = MagicMock()
        tracked_result.scalar_one_or_none.return_value = tracked
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account

        db.execute.side_effect = [approval_result, tracked_result, account_result]

        @dataclass
        class _MoveOutcome:
            folder: str | None = None
            new_uid: str | None = None

        with (
            patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db)),
            patch(f"{MODULE}.execute_imap_actions", new_callable=AsyncMock, return_value=_MoveOutcome()) as mock_imap,
            patch(f"{MODULE}.save_new_labels", new_callable=AsyncMock),
            patch(f"{MODULE}.save_new_folders", new_callable=AsyncMock),
            patch(f"{MODULE}._persist_plugin_data", new_callable=AsyncMock),
        ):
            await execute_approved_actions({}, str(approval.id))

            # Should have rebuilt actions from edited_actions
            call_actions = mock_imap.call_args[0][2]
            assert call_actions == ["apply_label:new_label"]

    @pytest.mark.asyncio
    async def test_account_not_found_returns_early(self) -> None:
        approval = _make_approval(function_type="labeling")
        approval.proposed_action = {"actions": ["apply_label:x"]}
        approval.edited_actions = None

        tracked = _make_tracked_email()
        db = AsyncMock()
        approval_result = MagicMock()
        approval_result.scalar_one_or_none.return_value = approval
        tracked_result = MagicMock()
        tracked_result.scalar_one_or_none.return_value = tracked
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = None  # no account

        db.execute.side_effect = [approval_result, tracked_result, account_result]

        with (
            patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db)),
            patch(f"{MODULE}.execute_imap_actions", new_callable=AsyncMock) as mock_imap,
        ):
            await execute_approved_actions({}, str(uuid4()))
            mock_imap.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_move_outcome_no_folder_skips_update(self) -> None:
        """When move_outcome.folder is None, tracked email is not updated."""
        approval = _make_approval(function_type="labeling")
        approval.proposed_action = {"actions": ["apply_label:x"]}
        approval.edited_actions = None

        tracked = _make_tracked_email()
        account = MagicMock()

        db = AsyncMock()
        approval_result = MagicMock()
        approval_result.scalar_one_or_none.return_value = approval
        tracked_result = MagicMock()
        tracked_result.scalar_one_or_none.return_value = tracked
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account

        db.execute.side_effect = [approval_result, tracked_result, account_result]

        @dataclass
        class _MoveOutcome:
            folder: str | None = None
            new_uid: str | None = None

        with (
            patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db)),
            patch(f"{MODULE}.execute_imap_actions", new_callable=AsyncMock, return_value=_MoveOutcome()),
            patch(f"{MODULE}.save_new_labels", new_callable=AsyncMock),
            patch(f"{MODULE}.save_new_folders", new_callable=AsyncMock),
            patch(f"{MODULE}._persist_plugin_data", new_callable=AsyncMock),
        ):
            await execute_approved_actions({}, str(approval.id))

            # Only 3 execute calls: approval, tracked, account — no update query
            assert db.execute.call_count == 3


# ---------------------------------------------------------------------------
# handle_spam_rejection
# ---------------------------------------------------------------------------


class TestHandleSpamRejection:
    @pytest.mark.asyncio
    async def test_reprocesses_with_skip_spam(self) -> None:
        user_id = str(uuid4())
        account_id = str(uuid4())
        mail_uid = "55"

        db = AsyncMock()
        folder_result = MagicMock()
        folder_result.scalars.return_value.first.return_value = "Archive"
        db.execute.return_value = folder_result

        with (
            patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db)),
            patch(f"{MODULE}.process_mail", new_callable=AsyncMock) as mock_process,
        ):
            # process_mail is imported inside the function, so we patch at module level
            # Actually it's a lazy import — patch where it'll be looked up
            with patch("app.workers.mail_processor.process_mail", new_callable=AsyncMock) as mock_pm:
                # Re-patch at module level after import
                pass

            # The function does a lazy import, so let's patch it properly
            await handle_spam_rejection({}, user_id, account_id, mail_uid)

            mock_process.assert_awaited_once_with(
                {},
                user_id,
                account_id,
                mail_uid,
                current_folder="Archive",
                skip_plugins=["spam_detection"],
            )

    @pytest.mark.asyncio
    async def test_defaults_to_inbox_when_no_tracked(self) -> None:
        user_id = str(uuid4())
        account_id = str(uuid4())

        db = AsyncMock()
        folder_result = MagicMock()
        folder_result.scalars.return_value.first.return_value = None
        db.execute.return_value = folder_result

        with (
            patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db)),
            patch(f"{MODULE}.process_mail", new_callable=AsyncMock) as mock_process,
        ):
            await handle_spam_rejection({}, user_id, account_id, "77")

            assert mock_process.call_args.kwargs["current_folder"] == "INBOX"


# ---------------------------------------------------------------------------
# _persist_plugin_data — branches not covered by existing tests
# ---------------------------------------------------------------------------


class TestPersistPluginDataCoverage:
    @pytest.mark.asyncio
    async def test_coupons_persists(self) -> None:
        approval = _make_approval(
            function_type="coupon_extraction",
            ai_response_data={"has_coupons": True, "coupons": [{"code": "SAVE10"}]},
        )

        with patch(f"{MODULE}.save_coupons", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_data(approval)
            mock_save.assert_awaited_once()
            kw = mock_save.call_args.kwargs
            assert kw["has_coupons"] is True
            assert kw["coupons"] == [{"code": "SAVE10"}]
            assert kw["own_session"] is True

    @pytest.mark.asyncio
    async def test_labeling_persists(self) -> None:
        approval = _make_approval(
            function_type="labeling",
            ai_response_data={"labels": ["urgent", "finance"]},
        )

        with patch(f"{MODULE}.save_applied_labels", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_data(approval)
            kw = mock_save.call_args.kwargs
            assert kw["labels"] == ["urgent", "finance"]
            assert kw["own_session"] is True

    @pytest.mark.asyncio
    async def test_contacts_persists(self) -> None:
        approval = _make_approval(
            function_type="contacts",
            ai_response_data={
                "contact_id": str(uuid4()),
                "contact_name": "John Doe",
                "confidence": 0.95,
                "reasoning": "exact match",
                "is_new_contact_suggestion": False,
            },
        )

        with patch(f"{MODULE}.save_contact_assignment", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_data(approval)
            kw = mock_save.call_args.kwargs
            assert kw["contact_name"] == "John Doe"
            assert kw["sender_email"] == "sender@example.com"
            assert kw["auto_writeback"] is True
            assert kw["own_session"] is True

    @pytest.mark.asyncio
    async def test_auto_reply_with_draft_upload(self) -> None:
        """When should_reply=True and draft_body is set, upload_draft_to_imap is called."""
        approval = _make_approval(
            function_type="auto_reply",
            ai_response_data={
                "should_reply": True,
                "draft_body": "Thanks for reaching out!",
                "tone": "professional",
                "reasoning": "needs reply",
            },
        )

        tracked = _make_tracked_email(mail_uid="88")
        account = MagicMock()

        db2 = AsyncMock()
        tracked_result = MagicMock()
        tracked_result.scalar_one_or_none.return_value = tracked
        account_result = MagicMock()
        account_result.scalar_one_or_none.return_value = account
        db2.execute.side_effect = [tracked_result, account_result]

        with (
            patch(f"{MODULE}.save_auto_reply", new_callable=AsyncMock) as mock_save,
            patch(f"{MODULE}.get_session_ctx", _fake_session_ctx(db2)),
            patch(f"{MODULE}.upload_draft_to_imap", new_callable=AsyncMock) as mock_upload,
        ):
            await _persist_plugin_data(approval)
            mock_save.assert_awaited_once()
            mock_upload.assert_awaited_once()
            kw = mock_upload.call_args.kwargs
            assert kw["draft_body"] == "Thanks for reaching out!"
            assert kw["original_subject"] == "Test Subject"
            assert kw["original_from"] == "sender@example.com"

    @pytest.mark.asyncio
    async def test_auto_reply_no_draft_skips_upload(self) -> None:
        """When should_reply=True but draft_body is None, no upload."""
        approval = _make_approval(
            function_type="auto_reply",
            ai_response_data={"should_reply": True, "draft_body": None},
        )

        with patch(f"{MODULE}.save_auto_reply", new_callable=AsyncMock):
            # Should not error — no draft upload attempted
            await _persist_plugin_data(approval)

    @pytest.mark.asyncio
    async def test_smart_folder_persists(self) -> None:
        approval = _make_approval(
            function_type="smart_folder",
            ai_response_data={"folder": "Finance", "confidence": 0.85, "reason": "invoice"},
        )

        with patch(f"{MODULE}.save_assigned_folder", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_data(approval)
            kw = mock_save.call_args.kwargs
            assert kw["folder"] == "Finance"
            assert kw["confidence"] == 0.85
