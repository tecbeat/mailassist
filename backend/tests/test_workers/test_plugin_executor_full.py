from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.plugin_executor import (
    PluginOutcome,
    _extract_result_details,
    _extract_result_summary,
    _handle_blocklist,
)

# ---------------------------------------------------------------------------
# PluginOutcome dataclass
# ---------------------------------------------------------------------------


class TestPluginOutcome:
    def test_defaults(self) -> None:
        o = PluginOutcome(plugin_name="spam_detection")
        assert o.plugin_name == "spam_detection"
        assert o.plugin_display_name == ""
        assert o.executed is False
        assert o.completed is False
        assert o.failed is False
        assert o.skipped is False
        assert o.skip_reason is None
        assert o.actions_taken == []
        assert o.approval_created is False
        assert o.needs_approval is False
        assert o.transient_error is False
        assert o.transient_error_reason is None
        assert o.failed_provider_id is None
        assert o.break_pipeline is False
        assert o.auto_approved is False
        assert o.result_summary is None
        assert o.result_details is None

    def test_independent_lists(self) -> None:
        o1 = PluginOutcome(plugin_name="a")
        o2 = PluginOutcome(plugin_name="b")
        o1.actions_taken.append("move")
        assert o2.actions_taken == []


# ---------------------------------------------------------------------------
# _extract_result_summary
# ---------------------------------------------------------------------------


class TestExtractResultSummary:
    def test_email_summary(self) -> None:
        resp = MagicMock()
        resp.summary = "This is a test email summary"
        result = _extract_result_summary("email_summary", resp)
        assert result == "This is a test email summary"

    def test_email_summary_none(self) -> None:
        resp = MagicMock(spec=[])
        result = _extract_result_summary("email_summary", resp)
        assert result is None

    def test_spam_detection_is_spam_with_reason(self) -> None:
        resp = MagicMock()
        resp.is_spam = True
        resp.reason = "Known phishing pattern"
        result = _extract_result_summary("spam_detection", resp)
        assert result == "Spam: Known phishing pattern"

    def test_spam_detection_not_spam_with_reason(self) -> None:
        resp = MagicMock()
        resp.is_spam = False
        resp.reason = "Legitimate sender"
        result = _extract_result_summary("spam_detection", resp)
        assert result == "Not spam: Legitimate sender"

    def test_spam_detection_is_spam_no_reason(self) -> None:
        resp = MagicMock()
        resp.is_spam = True
        resp.reason = ""
        result = _extract_result_summary("spam_detection", resp)
        assert result == "Spam"

    def test_spam_detection_not_spam_no_reason(self) -> None:
        resp = MagicMock()
        resp.is_spam = False
        resp.reason = ""
        result = _extract_result_summary("spam_detection", resp)
        assert result == "Not spam"

    def test_smart_folder(self) -> None:
        resp = MagicMock()
        resp.folder = "Archive/2024"
        result = _extract_result_summary("smart_folder", resp)
        assert result == "Folder: Archive/2024"

    def test_smart_folder_none(self) -> None:
        resp = MagicMock()
        resp.folder = None
        result = _extract_result_summary("smart_folder", resp)
        assert result is None

    def test_labeling_with_labels(self) -> None:
        resp = MagicMock()
        resp.labels = ["important", "work", "urgent"]
        result = _extract_result_summary("labeling", resp)
        assert result == "Labels: important, work, urgent"

    def test_labeling_empty(self) -> None:
        resp = MagicMock()
        resp.labels = []
        result = _extract_result_summary("labeling", resp)
        assert result == "No labels"

    def test_newsletter_detected(self) -> None:
        resp = MagicMock()
        resp.is_newsletter = True
        resp.newsletter_name = "TechCrunch Daily"
        result = _extract_result_summary("newsletter_detection", resp)
        assert result == "Newsletter: TechCrunch Daily"

    def test_newsletter_not_detected(self) -> None:
        resp = MagicMock()
        resp.is_newsletter = False
        resp.newsletter_name = ""
        result = _extract_result_summary("newsletter_detection", resp)
        assert result == "Not a newsletter"

    def test_coupon_extraction_found(self) -> None:
        resp = MagicMock()
        resp.has_coupons = True
        resp.coupons = [MagicMock(), MagicMock(), MagicMock()]
        result = _extract_result_summary("coupon_extraction", resp)
        assert result == "3 coupon(s) found"

    def test_coupon_extraction_none(self) -> None:
        resp = MagicMock()
        resp.has_coupons = False
        resp.coupons = []
        result = _extract_result_summary("coupon_extraction", resp)
        assert result == "No coupons"

    def test_coupon_extraction_has_but_empty_list(self) -> None:
        resp = MagicMock()
        resp.has_coupons = True
        resp.coupons = []
        result = _extract_result_summary("coupon_extraction", resp)
        assert result == "No coupons"

    def test_otp_extraction_found(self) -> None:
        resp = MagicMock()
        resp.has_codes = True
        resp.codes = [MagicMock()]
        result = _extract_result_summary("otp_extraction", resp)
        assert result == "1 OTP code(s) found"

    def test_otp_extraction_none(self) -> None:
        resp = MagicMock()
        resp.has_codes = False
        resp.codes = []
        result = _extract_result_summary("otp_extraction", resp)
        assert result == "No OTP codes"

    def test_calendar_extraction_has_event(self) -> None:
        resp = MagicMock()
        resp.has_event = True
        resp.title = "Team standup"
        result = _extract_result_summary("calendar_extraction", resp)
        assert result == "Event: Team standup"

    def test_calendar_extraction_no_event(self) -> None:
        resp = MagicMock()
        resp.has_event = False
        resp.title = ""
        result = _extract_result_summary("calendar_extraction", resp)
        assert result == "No event"

    def test_calendar_extraction_has_event_no_title(self) -> None:
        resp = MagicMock()
        resp.has_event = True
        resp.title = ""
        result = _extract_result_summary("calendar_extraction", resp)
        assert result == "No event"

    def test_auto_reply_should_reply(self) -> None:
        resp = MagicMock()
        resp.should_reply = True
        result = _extract_result_summary("auto_reply", resp)
        assert result == "Reply drafted"

    def test_auto_reply_no_reply(self) -> None:
        resp = MagicMock()
        resp.should_reply = False
        result = _extract_result_summary("auto_reply", resp)
        assert result == "No reply needed"

    def test_contacts_with_name(self) -> None:
        resp = MagicMock()
        resp.contact_name = "Jane Doe"
        result = _extract_result_summary("contacts", resp)
        assert result == "Contact: Jane Doe"

    def test_contacts_no_name(self) -> None:
        resp = MagicMock()
        resp.contact_name = ""
        result = _extract_result_summary("contacts", resp)
        assert result == "No contact match"

    def test_unknown_plugin(self) -> None:
        resp = MagicMock()
        result = _extract_result_summary("unknown_plugin_xyz", resp)
        assert result is None

    def test_exception_returns_none(self) -> None:
        resp = MagicMock()
        resp.summary = property(lambda self: (_ for _ in ()).throw(RuntimeError))
        # Force attribute access to raise
        type(resp).summary = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
        result = _extract_result_summary("email_summary", resp)
        assert result is None


# ---------------------------------------------------------------------------
# _extract_result_details
# ---------------------------------------------------------------------------


class TestExtractResultDetails:
    def test_returns_model_dump(self) -> None:
        resp = MagicMock()
        resp.model_dump.return_value = {"summary": "hello", "confidence": 0.9}
        result = _extract_result_details("email_summary", resp)
        assert result == {"summary": "hello", "confidence": 0.9}
        resp.model_dump.assert_called_once_with(mode="json")

    def test_removes_draft_body(self) -> None:
        resp = MagicMock()
        resp.model_dump.return_value = {
            "should_reply": True,
            "draft_body": "Very long draft text...",
            "tone": "formal",
        }
        result = _extract_result_details("auto_reply", resp)
        assert result == {"should_reply": True, "tone": "formal"}
        assert "draft_body" not in result

    def test_returns_none_on_exception(self) -> None:
        resp = MagicMock()
        resp.model_dump.side_effect = RuntimeError("serialize failed")
        result = _extract_result_details("email_summary", resp)
        assert result is None


# ---------------------------------------------------------------------------
# _handle_blocklist
# ---------------------------------------------------------------------------


class TestHandleBlocklist:
    @pytest.mark.asyncio
    async def test_not_spam_plugin_not_called(self) -> None:
        """_handle_blocklist is only called for spam_detection in execute_plugin,
        but we test that it returns an outcome with break_pipeline when sender is blocked."""
        # This function is always called with spam_detection plugin,
        # so we test the two branches: blocked vs not blocked.

    @pytest.mark.asyncio
    async def test_sender_not_blocked_returns_none(self) -> None:
        mock_db = AsyncMock()
        mock_plugin = MagicMock()
        mock_plugin.name = "spam_detection"
        mock_plugin.display_name = "Spam Detection"
        mock_context = MagicMock()
        mock_context.user_id = str(uuid4())
        mock_context.sender = "safe@example.com"
        mock_context.subject = "Hello"
        mock_pipeline = MagicMock()
        mock_log = MagicMock()

        with patch(
            "app.workers.plugin_executor.check_blocklist",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await _handle_blocklist(
                db=mock_db,
                plugin=mock_plugin,
                context=mock_context,
                pipeline=mock_pipeline,
                approval_col="spam_detection_mode",
                approval_mode=MagicMock(),
                user_settings=MagicMock(),
                log=mock_log,
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_sender_blocked_auto_mode(self) -> None:
        from app.models.user import ApprovalMode

        mock_db = AsyncMock()
        mock_plugin = MagicMock()
        mock_plugin.name = "spam_detection"
        mock_plugin.display_name = "Spam Detection"
        mock_context = MagicMock()
        mock_context.user_id = str(uuid4())
        mock_context.sender = "spammer@evil.com"
        mock_context.subject = "Buy now!"
        mock_context.mail_id = str(uuid4())
        mock_pipeline = MagicMock()
        mock_log = MagicMock()
        mock_settings = MagicMock()

        with (
            patch(
                "app.workers.plugin_executor.check_blocklist",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workers.plugin_executor.save_spam_detection",
                new_callable=AsyncMock,
            ) as mock_save,
        ):
            result = await _handle_blocklist(
                db=mock_db,
                plugin=mock_plugin,
                context=mock_context,
                pipeline=mock_pipeline,
                approval_col="spam_detection_mode",
                approval_mode=ApprovalMode.AUTO,
                user_settings=mock_settings,
                log=mock_log,
            )

        assert result is not None
        assert result.break_pipeline is True
        assert result.executed is True
        assert result.completed is True
        assert "blocklist" in result.actions_taken[0]
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sender_blocked_approval_mode(self) -> None:
        from app.models.user import ApprovalMode

        mock_db = AsyncMock()
        mock_plugin = MagicMock()
        mock_plugin.name = "spam_detection"
        mock_plugin.display_name = "Spam Detection"
        mock_context = MagicMock()
        mock_context.user_id = str(uuid4())
        mock_context.account_id = str(uuid4())
        mock_context.sender = "spammer@evil.com"
        mock_context.subject = "Buy now!"
        mock_context.mail_id = str(uuid4())
        mock_context.date = ""
        mock_pipeline = MagicMock()
        mock_log = MagicMock()
        mock_settings = MagicMock()

        with (
            patch(
                "app.workers.plugin_executor.check_blocklist",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.workers.plugin_executor._create_approval",
                new_callable=AsyncMock,
            ) as mock_approval,
        ):
            result = await _handle_blocklist(
                db=mock_db,
                plugin=mock_plugin,
                context=mock_context,
                pipeline=mock_pipeline,
                approval_col="spam_detection_mode",
                approval_mode=ApprovalMode.APPROVAL,
                user_settings=mock_settings,
                log=mock_log,
            )

        assert result is not None
        assert result.break_pipeline is True
        assert result.approval_created is True
        assert result.actions_taken == []
        mock_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sender_blocked_no_approval_col(self) -> None:
        """When approval_col is None, no persistence or approval happens."""
        mock_db = AsyncMock()
        mock_plugin = MagicMock()
        mock_plugin.name = "spam_detection"
        mock_plugin.display_name = "Spam Detection"
        mock_context = MagicMock()
        mock_context.user_id = str(uuid4())
        mock_context.sender = "spammer@evil.com"
        mock_context.subject = "Buy!"
        mock_context.mail_id = str(uuid4())
        mock_pipeline = MagicMock()
        mock_log = MagicMock()

        with patch(
            "app.workers.plugin_executor.check_blocklist",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await _handle_blocklist(
                db=mock_db,
                plugin=mock_plugin,
                context=mock_context,
                pipeline=mock_pipeline,
                approval_col=None,
                approval_mode=MagicMock(),
                user_settings=None,
                log=mock_log,
            )

        assert result is not None
        assert result.break_pipeline is True
        assert result.actions_taken == []
        assert result.approval_created is False
