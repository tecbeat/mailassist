from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.plugins.auto_reply import AutoReplyPlugin, AutoReplyResponse
from app.plugins.base import MailContext
from app.plugins.coupon_extraction import (
    Coupon,
    CouponExtractionPlugin,
    CouponExtractionResponse,
)
from app.plugins.email_summary import EmailSummaryPlugin, EmailSummaryResponse
from app.plugins.labeling import LabelingPlugin, LabelingResponse
from app.plugins.newsletter_detection import (
    NewsletterDetectionPlugin,
    NewsletterDetectionResponse,
)
from app.plugins.otp_extraction import (
    OtpCode,
    OtpExtractionPlugin,
    OtpExtractionResponse,
)
from app.plugins.rules import RulesPlugin, _NoOpResponse
from app.plugins.spam_detection import SpamDetectionPlugin, SpamDetectionResponse


def _make_context(**overrides: object) -> MailContext:
    """Create a minimal MailContext for testing."""
    defaults = {
        "user_id": "user-1",
        "account_id": "acc-1",
        "mail_uid": "uid-1",
        "sender": "sender@example.com",
        "sender_name": "Sender",
        "recipient": "recipient@example.com",
        "subject": "Test",
        "body": "body",
        "body_plain": "plain",
        "body_html": "<p>html</p>",
        "headers": {},
        "date": "2026-01-01",
        "has_attachments": False,
        "attachment_names": [],
        "account_name": "Test Account",
        "account_email": "test@example.com",
        "existing_labels": [],
        "existing_folders": [],
        "excluded_folders": [],
        "folder_separator": "/",
        "mail_size": 1024,
        "thread_length": 1,
        "is_reply": False,
        "is_forwarded": False,
    }
    defaults.update(overrides)
    return MailContext(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Spam Detection
# ---------------------------------------------------------------------------


class TestSpamDetectionPlugin:
    def test_class_attributes(self) -> None:
        plugin = SpamDetectionPlugin()
        assert plugin.name == "spam_detection"
        assert plugin.execution_order == 10
        assert plugin.display_name == "Spam Detection"

    def test_response_model(self) -> None:
        plugin = SpamDetectionPlugin()
        assert plugin.get_response_schema() is SpamDetectionResponse

    @pytest.mark.asyncio
    async def test_execute_not_spam(self) -> None:
        plugin = SpamDetectionPlugin()
        response = SpamDetectionResponse(is_spam=False, confidence=0.1, reason="clean")
        result = await plugin.execute(_make_context(), response)
        assert result.success is True
        assert "spam_check_passed" in result.actions_taken

    @pytest.mark.asyncio
    async def test_execute_spam_high_confidence(self) -> None:
        plugin = SpamDetectionPlugin()
        response = SpamDetectionResponse(is_spam=True, confidence=0.95, reason="phishing")
        result = await plugin.execute(_make_context(), response)
        assert result.success is True
        assert result.skip_remaining_plugins is True
        assert any("move_to_spam" in a for a in result.actions_taken)

    @pytest.mark.asyncio
    async def test_execute_spam_low_confidence(self) -> None:
        plugin = SpamDetectionPlugin()
        response = SpamDetectionResponse(is_spam=True, confidence=0.5, reason="suspicious")
        result = await plugin.execute(_make_context(), response)
        assert result.success is True
        assert result.requires_approval is True
        assert result.skip_remaining_plugins is False

    def test_get_approval_summary(self) -> None:
        plugin = SpamDetectionPlugin()
        response = SpamDetectionResponse(is_spam=True, confidence=0.9, reason="phish")
        summary = plugin.get_approval_summary(response)
        assert "90%" in summary
        assert "phish" in summary

    @pytest.mark.asyncio
    async def test_load_notification_context_no_mail_id(self) -> None:
        db = AsyncMock()
        result = await SpamDetectionPlugin.load_notification_context(db, "acc-1", "uid-1", mail_id=None)
        assert result == {}

    @pytest.mark.asyncio
    async def test_load_notification_context_with_result(self) -> None:
        mock_spam = MagicMock()
        mock_spam.is_spam = True
        mock_spam.confidence = 0.92
        mock_spam.reason = "phishing link"
        mock_spam.source = "ai"

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_spam
        db.execute.return_value = mock_result

        result = await SpamDetectionPlugin.load_notification_context(db, "acc-1", "uid-1", mail_id="mail-1")
        assert result["is_spam"] is True
        assert result["spam_confidence"] == 0.92

    @pytest.mark.asyncio
    async def test_load_notification_context_no_result(self) -> None:
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        result = await SpamDetectionPlugin.load_notification_context(db, "acc-1", "uid-1", mail_id="mail-1")
        assert result == {}


# ---------------------------------------------------------------------------
# Email Summary
# ---------------------------------------------------------------------------


class TestEmailSummaryPlugin:
    def test_class_attributes(self) -> None:
        plugin = EmailSummaryPlugin()
        assert plugin.name == "email_summary"
        assert plugin.execution_order == 75
        assert plugin.display_name == "Email Summary"

    def test_response_model(self) -> None:
        plugin = EmailSummaryPlugin()
        assert plugin.get_response_schema() is EmailSummaryResponse

    @pytest.mark.asyncio
    async def test_execute_no_action_required(self) -> None:
        plugin = EmailSummaryPlugin()
        response = EmailSummaryResponse(
            summary="A brief summary",
            urgency="low",
            action_required=False,
        )
        result = await plugin.execute(_make_context(), response)
        assert result.success is True
        assert any("store_summary" in a for a in result.actions_taken)

    @pytest.mark.asyncio
    async def test_execute_action_required(self) -> None:
        plugin = EmailSummaryPlugin()
        response = EmailSummaryResponse(
            summary="Urgent meeting",
            urgency="high",
            action_required=True,
            action_description="Reply by Friday",
        )
        result = await plugin.execute(_make_context(), response)
        assert any("action_required" in a for a in result.actions_taken)

    def test_get_approval_summary(self) -> None:
        plugin = EmailSummaryPlugin()
        response = EmailSummaryResponse(summary="A test summary", urgency="medium", action_required=False)
        summary = plugin.get_approval_summary(response)
        assert "medium" in summary


# ---------------------------------------------------------------------------
# Labeling
# ---------------------------------------------------------------------------


class TestLabelingPlugin:
    def test_class_attributes(self) -> None:
        plugin = LabelingPlugin()
        assert plugin.name == "labeling"
        assert plugin.execution_order == 30

    def test_response_model(self) -> None:
        plugin = LabelingPlugin()
        assert plugin.get_response_schema() is LabelingResponse

    @pytest.mark.asyncio
    async def test_execute_reused_labels(self) -> None:
        plugin = LabelingPlugin()
        ctx = _make_context(existing_labels=["work", "urgent"])
        response = LabelingResponse(labels=["Work", "urgent"])
        result = await plugin.execute(ctx, response)
        assert result.success is True
        assert any("apply_label:work" in a for a in result.actions_taken)

    @pytest.mark.asyncio
    async def test_execute_new_labels(self) -> None:
        plugin = LabelingPlugin()
        ctx = _make_context(existing_labels=[])
        response = LabelingResponse(labels=["finance"])
        result = await plugin.execute(ctx, response)
        assert result.success is True
        assert any("create_and_apply_label:finance" in a for a in result.actions_taken)

    @pytest.mark.asyncio
    async def test_label_normalization(self) -> None:
        plugin = LabelingPlugin()
        ctx = _make_context(existing_labels=[])
        response = LabelingResponse(labels=["Hello World", "under_score", "special!@#"])
        result = await plugin.execute(ctx, response)
        action_str = " ".join(result.actions_taken)
        assert "hello-world" in action_str
        assert "under-score" in action_str
        assert "special" in action_str

    @pytest.mark.asyncio
    async def test_empty_labels_after_normalization(self) -> None:
        plugin = LabelingPlugin()
        ctx = _make_context(existing_labels=[])
        response = LabelingResponse(labels=["!!!", "@@@"])
        result = await plugin.execute(ctx, response)
        assert "all_labels_empty_after_normalization" in result.actions_taken

    def test_get_approval_summary(self) -> None:
        plugin = LabelingPlugin()
        response = LabelingResponse(labels=["work", "urgent"])
        summary = plugin.get_approval_summary(response)
        assert "work" in summary
        assert "urgent" in summary


# ---------------------------------------------------------------------------
# Newsletter Detection
# ---------------------------------------------------------------------------


class TestNewsletterDetectionPlugin:
    def test_class_attributes(self) -> None:
        plugin = NewsletterDetectionPlugin()
        assert plugin.name == "newsletter_detection"
        assert plugin.execution_order == 20

    def test_response_model(self) -> None:
        plugin = NewsletterDetectionPlugin()
        assert plugin.get_response_schema() is NewsletterDetectionResponse

    @pytest.mark.asyncio
    async def test_execute_not_newsletter(self) -> None:
        plugin = NewsletterDetectionPlugin()
        response = NewsletterDetectionResponse(is_newsletter=False, has_unsubscribe=False)
        result = await plugin.execute(_make_context(), response)
        assert "newsletter_check_passed" in result.actions_taken

    @pytest.mark.asyncio
    async def test_execute_newsletter_with_unsubscribe(self) -> None:
        plugin = NewsletterDetectionPlugin()
        response = NewsletterDetectionResponse(
            is_newsletter=True,
            newsletter_name="Weekly Digest",
            has_unsubscribe=True,
            unsubscribe_url="https://example.com/unsub",
        )
        result = await plugin.execute(_make_context(), response)
        assert result.success is True
        assert any("store_unsubscribe_url" in a for a in result.actions_taken)

    def test_validate_unsubscribe_url_valid(self) -> None:
        response = NewsletterDetectionResponse(
            is_newsletter=True,
            has_unsubscribe=True,
            unsubscribe_url="https://example.com/unsub",
        )
        assert response.unsubscribe_url == "https://example.com/unsub"

    def test_validate_unsubscribe_url_http(self) -> None:
        response = NewsletterDetectionResponse(
            is_newsletter=True,
            has_unsubscribe=True,
            unsubscribe_url="http://example.com/unsub",
        )
        assert response.unsubscribe_url == "http://example.com/unsub"

    def test_validate_unsubscribe_url_invalid(self) -> None:
        response = NewsletterDetectionResponse(
            is_newsletter=True,
            has_unsubscribe=True,
            unsubscribe_url="javascript:alert(1)",
        )
        assert response.unsubscribe_url is None

    def test_validate_unsubscribe_url_none(self) -> None:
        response = NewsletterDetectionResponse(is_newsletter=True, has_unsubscribe=False, unsubscribe_url=None)
        assert response.unsubscribe_url is None

    def test_get_approval_summary(self) -> None:
        plugin = NewsletterDetectionPlugin()
        response = NewsletterDetectionResponse(
            is_newsletter=True,
            newsletter_name="Tech Weekly",
            has_unsubscribe=False,
        )
        summary = plugin.get_approval_summary(response)
        assert "Tech Weekly" in summary


# ---------------------------------------------------------------------------
# OTP Extraction
# ---------------------------------------------------------------------------


class TestOtpExtractionPlugin:
    def test_class_attributes(self) -> None:
        plugin = OtpExtractionPlugin()
        assert plugin.name == "otp_extraction"
        assert plugin.execution_order == 45

    def test_response_model(self) -> None:
        plugin = OtpExtractionPlugin()
        assert plugin.get_response_schema() is OtpExtractionResponse

    @pytest.mark.asyncio
    async def test_execute_no_codes(self) -> None:
        plugin = OtpExtractionPlugin()
        response = OtpExtractionResponse(has_codes=False)
        result = await plugin.execute(_make_context(), response)
        assert "no_otp_found" in result.actions_taken

    @pytest.mark.asyncio
    async def test_execute_with_codes(self) -> None:
        plugin = OtpExtractionPlugin()
        code = OtpCode(code="123456", code_type="otp", service="GitHub")
        response = OtpExtractionResponse(has_codes=True, codes=[code])
        result = await plugin.execute(_make_context(), response)
        assert result.success is True
        assert any("store_otp" in a for a in result.actions_taken)

    def test_validate_code_type_valid(self) -> None:
        code = OtpCode(code="123", code_type="2fa")
        assert code.code_type == "2fa"

    def test_validate_code_type_invalid(self) -> None:
        code = OtpCode(code="123", code_type="INVALID_TYPE")
        assert code.code_type == "other"

    def test_clamp_expiry_none(self) -> None:
        code = OtpCode(code="123", code_type="otp", expires_in_minutes=None)
        assert code.expires_in_minutes is None

    def test_clamp_expiry_zero(self) -> None:
        code = OtpCode(code="123", code_type="otp", expires_in_minutes=0)
        assert code.expires_in_minutes is None

    def test_clamp_expiry_negative(self) -> None:
        code = OtpCode(code="123", code_type="otp", expires_in_minutes=-5)
        assert code.expires_in_minutes is None

    def test_clamp_expiry_large(self) -> None:
        code = OtpCode(code="123", code_type="otp", expires_in_minutes=9999)
        assert code.expires_in_minutes == 1440

    def test_clamp_expiry_normal(self) -> None:
        code = OtpCode(code="123", code_type="otp", expires_in_minutes=10)
        assert code.expires_in_minutes == 10

    def test_get_approval_summary(self) -> None:
        plugin = OtpExtractionPlugin()
        code = OtpCode(code="123456", code_type="2fa", service="GitHub")
        response = OtpExtractionResponse(has_codes=True, codes=[code])
        summary = plugin.get_approval_summary(response)
        assert "1" in summary
        assert "GitHub" in summary


# ---------------------------------------------------------------------------
# Coupon Extraction
# ---------------------------------------------------------------------------


class TestCouponExtractionPlugin:
    def test_class_attributes(self) -> None:
        plugin = CouponExtractionPlugin()
        assert plugin.name == "coupon_extraction"
        assert plugin.execution_order == 50

    def test_response_model(self) -> None:
        plugin = CouponExtractionPlugin()
        assert plugin.get_response_schema() is CouponExtractionResponse

    @pytest.mark.asyncio
    async def test_execute_no_coupons(self) -> None:
        plugin = CouponExtractionPlugin()
        response = CouponExtractionResponse(has_coupons=False)
        result = await plugin.execute(_make_context(), response)
        assert "no_coupons_found" in result.actions_taken

    @pytest.mark.asyncio
    async def test_execute_with_coupons(self) -> None:
        plugin = CouponExtractionPlugin()
        coupon = Coupon(code="SAVE20", store="Amazon")
        response = CouponExtractionResponse(has_coupons=True, coupons=[coupon])
        result = await plugin.execute(_make_context(), response)
        assert result.success is True
        assert any("store_coupon" in a for a in result.actions_taken)

    def test_coupon_date_validation_valid(self) -> None:
        coupon = Coupon(code="X", expires_at="2026-12-31")
        assert coupon.expires_at == "2026-12-31"

    def test_coupon_date_validation_invalid(self) -> None:
        coupon = Coupon(code="X", expires_at="Dec 31, 2026")
        assert coupon.expires_at is None

    def test_get_approval_summary(self) -> None:
        plugin = CouponExtractionPlugin()
        coupon = Coupon(code="SAVE20", store="Amazon")
        response = CouponExtractionResponse(has_coupons=True, coupons=[coupon])
        summary = plugin.get_approval_summary(response)
        assert "SAVE20" in summary


# ---------------------------------------------------------------------------
# Auto Reply
# ---------------------------------------------------------------------------


class TestAutoReplyPlugin:
    def test_class_attributes(self) -> None:
        plugin = AutoReplyPlugin()
        assert plugin.name == "auto_reply"
        assert plugin.execution_order == 70
        assert plugin.display_name == "Auto-Reply Draft"

    def test_response_model(self) -> None:
        plugin = AutoReplyPlugin()
        assert plugin.get_response_schema() is AutoReplyResponse

    @pytest.mark.asyncio
    async def test_execute_no_reply(self) -> None:
        plugin = AutoReplyPlugin()
        response = AutoReplyResponse(should_reply=False, reasoning="Not needed")
        result = await plugin.execute(_make_context(), response)
        assert result.success is True
        assert any("no_reply_needed" in a for a in result.actions_taken)

    @pytest.mark.asyncio
    async def test_execute_reply_no_body(self) -> None:
        plugin = AutoReplyPlugin()
        response = AutoReplyResponse(should_reply=True, draft_body=None, reasoning="Question asked")
        result = await plugin.execute(_make_context(), response)
        assert "reply_suggested_but_no_body" in result.actions_taken

    @pytest.mark.asyncio
    async def test_execute_reply_with_body_requires_approval(self) -> None:
        plugin = AutoReplyPlugin()
        response = AutoReplyResponse(
            should_reply=True,
            draft_body="Thank you for your email.",
            tone="professional",
            reasoning="Direct question",
        )
        result = await plugin.execute(_make_context(), response)
        assert result.success is True
        assert result.requires_approval is True
        assert any("create_draft_reply" in a for a in result.actions_taken)

    def test_get_approval_summary(self) -> None:
        plugin = AutoReplyPlugin()
        response = AutoReplyResponse(
            should_reply=True,
            draft_body="Thanks",
            tone="friendly",
            reasoning="Question asked",
        )
        summary = plugin.get_approval_summary(response)
        assert "friendly" in summary


# ---------------------------------------------------------------------------
# Rules (pseudo-plugin)
# ---------------------------------------------------------------------------


class TestRulesPlugin:
    def test_class_attributes(self) -> None:
        plugin = RulesPlugin()
        assert plugin.name == "rules"
        assert plugin.runs_in_pipeline is False
        assert plugin.display_name == "Rules Engine"

    @pytest.mark.asyncio
    async def test_execute_raises(self) -> None:
        plugin = RulesPlugin()
        response = _NoOpResponse()
        with pytest.raises(NotImplementedError):
            await plugin.execute(_make_context(), response)

    def test_get_approval_summary_raises(self) -> None:
        plugin = RulesPlugin()
        response = _NoOpResponse()
        with pytest.raises(NotImplementedError):
            plugin.get_approval_summary(response)
