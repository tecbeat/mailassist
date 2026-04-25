"""Tests for email summary error diagnostics (Issue #26).

Verifies the mails_without_summary dashboard stat and the
GET /api/summaries/missing endpoint logic.
"""

from uuid import uuid4

import pytest

from app.schemas.dashboard import DashboardStatsResponse
from app.schemas.summary import MissingSummaryItem, MissingSummaryListResponse


# ---------------------------------------------------------------------------
# DashboardStatsResponse schema tests
# ---------------------------------------------------------------------------


class TestDashboardStatsSchema:
    """DashboardStatsResponse includes the mails_without_summary field."""

    def test_default_value(self):
        stats = DashboardStatsResponse()
        assert stats.mails_without_summary == 0

    def test_custom_value(self):
        stats = DashboardStatsResponse(mails_without_summary=42)
        assert stats.mails_without_summary == 42

    def test_serialisation_includes_field(self):
        stats = DashboardStatsResponse(mails_without_summary=7)
        data = stats.model_dump()
        assert "mails_without_summary" in data
        assert data["mails_without_summary"] == 7


# ---------------------------------------------------------------------------
# MissingSummaryItem schema tests
# ---------------------------------------------------------------------------


class TestMissingSummaryItemSchema:
    """MissingSummaryItem contains expected fields for diagnostics."""

    def test_from_dict(self):
        uid = uuid4()
        account_id = uuid4()
        item = MissingSummaryItem(
            id=uid,
            mail_account_id=account_id,
            mail_uid="123",
            subject="Test Subject",
            sender="test@example.com",
            completion_reason="partial_with_errors",
            plugins_failed=["email_summary"],
            plugins_skipped=["smart_folder"],
            current_folder="INBOX",
            created_at="2026-01-15T10:00:00Z",
            updated_at="2026-01-15T10:05:00Z",
        )
        assert item.mail_uid == "123"
        assert item.completion_reason == "partial_with_errors"
        assert item.plugins_failed == ["email_summary"]

    def test_optional_fields(self):
        uid = uuid4()
        account_id = uuid4()
        item = MissingSummaryItem(
            id=uid,
            mail_account_id=account_id,
            mail_uid="456",
            created_at="2026-01-15T10:00:00Z",
            updated_at="2026-01-15T10:05:00Z",
        )
        assert item.subject is None
        assert item.sender is None
        assert item.completion_reason is None
        assert item.plugins_failed is None
        assert item.plugins_skipped is None
        assert item.current_folder == "INBOX"


# ---------------------------------------------------------------------------
# MissingSummaryListResponse schema tests
# ---------------------------------------------------------------------------


class TestMissingSummaryListResponseSchema:
    """MissingSummaryListResponse carries paginated items."""

    def test_empty_list(self):
        resp = MissingSummaryListResponse(
            items=[], total=0, page=1, per_page=20, pages=1,
        )
        assert resp.total == 0
        assert resp.items == []

    def test_with_items(self):
        item = MissingSummaryItem(
            id=uuid4(),
            mail_account_id=uuid4(),
            mail_uid="789",
            created_at="2026-01-15T10:00:00Z",
            updated_at="2026-01-15T10:05:00Z",
        )
        resp = MissingSummaryListResponse(
            items=[item], total=1, page=1, per_page=20, pages=1,
        )
        assert resp.total == 1
        assert len(resp.items) == 1
        assert resp.items[0].mail_uid == "789"
