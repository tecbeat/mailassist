"""Tests for _persist_plugin_data in approval_executor.

Verifies that after user approval, plugin data is persisted using the correct
save_* function with own_session=True and approval.mail_id.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.approval_executor import _persist_plugin_data

MODULE = "app.workers.approval_executor"


def _make_approval(
    *,
    function_type: str,
    ai_response_data: dict | None = None,
    edited_actions: dict | None = None,
) -> MagicMock:
    """Create a mock Approval with the given fields."""
    a = MagicMock()
    a.id = uuid4()
    a.user_id = uuid4()
    a.mail_id = uuid4()
    a.mail_from = "sender@example.com"
    a.mail_subject = "Test Subject"
    a.function_type = function_type
    a.ai_response_data = ai_response_data
    a.edited_actions = edited_actions
    return a


# ---------------------------------------------------------------------------
# No AI response data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_ai_response_data_returns_early() -> None:
    """When ai_response_data is None, nothing is persisted."""
    approval = _make_approval(function_type="email_summary", ai_response_data=None)

    with patch(f"{MODULE}.save_email_summary", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_data(approval)
        mock_save.assert_not_awaited()


# ---------------------------------------------------------------------------
# email_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_summary_persists_with_own_session() -> None:
    approval = _make_approval(
        function_type="email_summary",
        ai_response_data={
            "summary": "Important update",
            "key_points": ["a"],
            "urgency": "high",
            "action_required": True,
            "action_description": "Reply ASAP",
        },
    )

    with patch(f"{MODULE}.save_email_summary", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_data(approval)
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["user_id"] == approval.user_id
        assert kw["mail_id"] == approval.mail_id
        assert kw["own_session"] is True
        assert kw["summary"] == "Important update"


# ---------------------------------------------------------------------------
# newsletter_detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_newsletter_uses_mail_from_as_sender() -> None:
    approval = _make_approval(
        function_type="newsletter_detection",
        ai_response_data={"is_newsletter": True, "newsletter_name": "Weekly"},
    )

    with patch(f"{MODULE}.save_newsletter", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_data(approval)
        kw = mock_save.call_args.kwargs
        assert kw["sender_address"] == "sender@example.com"
        assert kw["own_session"] is True


# ---------------------------------------------------------------------------
# edited_actions override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edited_actions_override_ai_response() -> None:
    """User edits should override original AI response fields."""
    approval = _make_approval(
        function_type="smart_folder",
        ai_response_data={"folder": "OriginalFolder", "confidence": 0.9, "reason": "AI"},
        edited_actions={"folder": "UserFolder"},
    )

    with patch(f"{MODULE}.save_assigned_folder", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_data(approval)
        kw = mock_save.call_args.kwargs
        assert kw["folder"] == "UserFolder"
        assert kw["confidence"] == 0.9  # not overridden


# ---------------------------------------------------------------------------
# spam_detection — uses save_spam_detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spam_detection_calls_save() -> None:
    approval = _make_approval(
        function_type="spam_detection",
        ai_response_data={"is_spam": True, "confidence": 0.98, "reason": "phishing"},
    )

    with patch(f"{MODULE}.save_spam_detection", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_data(approval)
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["is_spam"] is True
        assert kw["mail_id"] == approval.mail_id
        assert kw["own_session"] is True


# ---------------------------------------------------------------------------
# contacts — uses auto_writeback=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contacts_uses_auto_writeback() -> None:
    approval = _make_approval(
        function_type="contacts",
        ai_response_data={
            "contact_id": str(uuid4()),
            "contact_name": "Bob",
            "confidence": 0.85,
            "reasoning": "match",
        },
    )

    with patch(f"{MODULE}.save_contact_assignment", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_data(approval)
        kw = mock_save.call_args.kwargs
        assert kw["auto_writeback"] is True
        assert kw["sender_email"] == "sender@example.com"


# ---------------------------------------------------------------------------
# calendar_extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calendar_passes_all_fields() -> None:
    approval = _make_approval(
        function_type="calendar_extraction",
        ai_response_data={
            "has_event": True,
            "title": "Standup",
            "start": "2025-06-15T09:00",
            "end": "2025-06-15T09:30",
            "location": "Room 1",
            "description": "Daily sync",
            "is_all_day": False,
        },
    )

    with patch(f"{MODULE}.save_calendar_event", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_data(approval)
        kw = mock_save.call_args.kwargs
        assert kw["title"] == "Standup"
        assert kw["is_all_day"] is False


# ---------------------------------------------------------------------------
# Exception handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_failure_raises() -> None:
    """_persist_plugin_data should re-raise on save failure."""
    approval = _make_approval(
        function_type="email_summary",
        ai_response_data={"summary": "x", "key_points": []},
    )

    with (
        patch(f"{MODULE}.save_email_summary", new_callable=AsyncMock, side_effect=RuntimeError("DB error")),
        pytest.raises(RuntimeError, match="DB error"),
    ):
        await _persist_plugin_data(approval)
