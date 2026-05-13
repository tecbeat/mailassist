"""Tests for API Pydantic schema validation.

Verifies that response schemas correctly handle subject/sender fields,
required fields, and filter configurations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.mail import CompletionReason, ErrorType, TrackedEmailStatus
from app.schemas.queue import PipelineProgress, PluginResultEntry, TrackedEmailResponse
from app.schemas.summary import (
    EmailSummaryResponse,
    MissingSummaryItem,
    SummaryFilterRules,
)


# ---------------------------------------------------------------------------
# EmailSummaryResponse
# ---------------------------------------------------------------------------


class TestEmailSummaryResponse:
    def test_valid_with_all_fields(self) -> None:
        data = EmailSummaryResponse(
            id=uuid4(),
            subject="Test Subject",
            sender="alice@example.com",
            received_at=datetime.now(UTC),
            summary="A brief summary",
            key_points=["point 1", "point 2"],
            urgency="high",
            action_required=True,
            action_description="Reply needed",
            notified=False,
            created_at=datetime.now(UTC),
        )
        assert data.subject == "Test Subject"
        assert data.sender == "alice@example.com"

    def test_subject_and_sender_nullable(self) -> None:
        data = EmailSummaryResponse(
            id=uuid4(),
            subject=None,
            sender=None,
            received_at=None,
            summary="Summary",
            key_points=[],
            urgency="low",
            action_required=False,
            action_description=None,
            notified=False,
            created_at=datetime.now(UTC),
        )
        assert data.subject is None
        assert data.sender is None

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(ValidationError):
            EmailSummaryResponse(
                id=uuid4(),
                # missing summary, key_points, urgency, action_required, etc.
                created_at=datetime.now(UTC),
            )  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# TrackedEmailResponse
# ---------------------------------------------------------------------------


class TestTrackedEmailResponse:
    def test_valid_minimal(self) -> None:
        data = TrackedEmailResponse(
            id=uuid4(),
            mail_uid="123",
            subject=None,
            sender=None,
            received_at=None,
            status=TrackedEmailStatus.QUEUED,
            error_type=None,
            last_error=None,
            plugins_completed=None,
            plugins_failed=None,
            plugins_skipped=None,
            completion_reason=None,
            current_folder="INBOX",
            mail_account_id=uuid4(),
            retry_count=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert data.status == TrackedEmailStatus.QUEUED
        assert data.subject is None

    def test_with_plugin_results(self) -> None:
        data = TrackedEmailResponse(
            id=uuid4(),
            mail_uid="456",
            subject="Important",
            sender="bob@x.com",
            received_at=datetime.now(UTC),
            status=TrackedEmailStatus.COMPLETED,
            error_type=None,
            last_error=None,
            plugins_completed=["spam", "summary"],
            plugins_failed=[],
            plugins_skipped=None,
            plugin_results={
                "spam": PluginResultEntry(
                    status="completed",
                    display_name="Spam Detection",
                    summary="Not spam",
                )
            },
            completion_reason=CompletionReason.FULL_PIPELINE,
            current_folder="INBOX",
            mail_account_id=uuid4(),
            retry_count=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert data.plugin_results is not None
        assert data.plugin_results["spam"].display_name == "Spam Detection"

    def test_pipeline_progress_optional(self) -> None:
        data = TrackedEmailResponse(
            id=uuid4(),
            mail_uid="789",
            subject=None,
            sender=None,
            received_at=None,
            status=TrackedEmailStatus.PROCESSING,
            error_type=None,
            last_error=None,
            plugins_completed=None,
            plugins_failed=None,
            plugins_skipped=None,
            pipeline_progress=PipelineProgress(
                phase="imap_fetch",
                plugins_total=3,
                plugin_index=1,
            ),
            completion_reason=None,
            current_folder="INBOX",
            mail_account_id=uuid4(),
            retry_count=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert data.pipeline_progress is not None
        assert data.pipeline_progress.phase == "imap_fetch"


# ---------------------------------------------------------------------------
# SummaryFilterRules
# ---------------------------------------------------------------------------


class TestSummaryFilterRules:
    def test_defaults(self) -> None:
        rules = SummaryFilterRules()
        assert rules.min_urgency == "low"
        assert rules.from_contacts_only is False
        assert rules.exclude_spam is True

    def test_invalid_urgency_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SummaryFilterRules(min_urgency="invalid")

    def test_valid_urgency_values(self) -> None:
        for urgency in ("low", "medium", "high", "critical"):
            rules = SummaryFilterRules(min_urgency=urgency)
            assert rules.min_urgency == urgency


# ---------------------------------------------------------------------------
# MissingSummaryItem
# ---------------------------------------------------------------------------


class TestMissingSummaryItem:
    def test_subject_sender_nullable(self) -> None:
        item = MissingSummaryItem(
            id=uuid4(),
            mail_account_id=uuid4(),
            mail_uid="55",
            subject=None,
            sender=None,
            completion_reason=None,
            plugins_failed=None,
            plugins_skipped=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        assert item.subject is None
        assert item.current_folder == "INBOX"  # default
