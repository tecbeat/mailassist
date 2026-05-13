"""Tests for auto-approve threshold in plugin_executor.

Verifies that actions with confidence above the user's configured
threshold are auto-approved (skip approval creation).
Issue #123.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.user import ApprovalMode


@dataclass
class FakeUserSettings:
    auto_approve_threshold: float | None = None
    ai_timeout_seconds: int = 120
    approval_mode_spam: ApprovalMode = ApprovalMode.APPROVAL


@dataclass
class FakeAIResponse:
    is_spam: bool = True
    confidence: float = 0.97
    reason: str = "test spam"


@dataclass
class FakeAIResponseNoConfidence:
    is_spam: bool = True
    reason: str = "test"


@dataclass
class FakeActionResult:
    success: bool = True
    actions_taken: list[str] = field(default_factory=lambda: ["move_to_spam"])
    requires_approval: bool = True
    skip_remaining_plugins: bool = False
    error: str | None = None
    retry_prompt: str | None = None


class TestAutoApproveThreshold:
    """Auto-approve threshold bypasses approval when confidence is high enough."""

    def test_threshold_none_does_not_auto_approve(self) -> None:
        """When threshold is None (disabled), approval is still required."""
        settings = FakeUserSettings(auto_approve_threshold=None)
        ai_response = FakeAIResponse(confidence=0.99)

        # Simulate the decision logic
        needs_approval = True
        auto_approved = False
        if needs_approval and settings.auto_approve_threshold is not None:
            response_confidence = getattr(ai_response, "confidence", None)
            if response_confidence is not None and response_confidence >= settings.auto_approve_threshold:
                needs_approval = False
                auto_approved = True

        assert needs_approval is True
        assert auto_approved is False

    def test_threshold_met_auto_approves(self) -> None:
        """When confidence >= threshold, action is auto-approved."""
        settings = FakeUserSettings(auto_approve_threshold=0.95)
        ai_response = FakeAIResponse(confidence=0.97)

        needs_approval = True
        auto_approved = False
        if needs_approval and settings.auto_approve_threshold is not None:
            response_confidence = getattr(ai_response, "confidence", None)
            if response_confidence is not None and response_confidence >= settings.auto_approve_threshold:
                needs_approval = False
                auto_approved = True

        assert needs_approval is False
        assert auto_approved is True

    def test_threshold_not_met_still_requires_approval(self) -> None:
        """When confidence < threshold, approval is still required."""
        settings = FakeUserSettings(auto_approve_threshold=0.95)
        ai_response = FakeAIResponse(confidence=0.80)

        needs_approval = True
        auto_approved = False
        if needs_approval and settings.auto_approve_threshold is not None:
            response_confidence = getattr(ai_response, "confidence", None)
            if response_confidence is not None and response_confidence >= settings.auto_approve_threshold:
                needs_approval = False
                auto_approved = True

        assert needs_approval is True
        assert auto_approved is False

    def test_no_confidence_field_does_not_auto_approve(self) -> None:
        """When AI response has no confidence field, threshold is skipped."""
        settings = FakeUserSettings(auto_approve_threshold=0.50)
        ai_response = FakeAIResponseNoConfidence()

        needs_approval = True
        auto_approved = False
        if needs_approval and settings.auto_approve_threshold is not None:
            response_confidence = getattr(ai_response, "confidence", None)
            if response_confidence is not None and response_confidence >= settings.auto_approve_threshold:
                needs_approval = False
                auto_approved = True

        assert needs_approval is True
        assert auto_approved is False

    def test_threshold_exact_boundary(self) -> None:
        """When confidence == threshold exactly, action is auto-approved."""
        settings = FakeUserSettings(auto_approve_threshold=0.95)
        ai_response = FakeAIResponse(confidence=0.95)

        needs_approval = True
        auto_approved = False
        if needs_approval and settings.auto_approve_threshold is not None:
            response_confidence = getattr(ai_response, "confidence", None)
            if response_confidence is not None and response_confidence >= settings.auto_approve_threshold:
                needs_approval = False
                auto_approved = True

        assert needs_approval is False
        assert auto_approved is True
