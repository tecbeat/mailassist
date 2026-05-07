"""Tests for smart folder excluded-folder reprompt logic.

Verifies that the SmartFolderPlugin requests a reprompt when the AI
suggests an excluded folder, and raises an error on repeated violation.
"""

from __future__ import annotations

import pytest

from app.plugins.base import MailContext
from app.plugins.smart_folder import ExcludedFolderError, SmartFolderPlugin, SmartFolderResponse


def _make_context(**overrides: object) -> MailContext:
    """Create a minimal MailContext for testing."""
    defaults: dict[str, object] = {
        "user_id": "user-1",
        "account_id": "acc-1",
        "mail_uid": "uid-1",
        "sender": "test@example.com",
        "sender_name": "Test",
        "recipient": "me@example.com",
        "subject": "Hello",
        "body": "Body text",
        "body_plain": "Body text",
        "body_html": "",
        "headers": {},
        "date": "2026-01-01",
        "has_attachments": False,
        "attachment_names": [],
        "account_name": "Test Account",
        "account_email": "me@example.com",
        "existing_labels": [],
        "existing_folders": ["INBOX", "Work", "Finance"],
        "excluded_folders": ["Spam", "Trash"],
        "folder_separator": "/",
        "mail_size": 1000,
        "thread_length": 1,
        "is_reply": False,
        "is_forwarded": False,
    }
    defaults.update(overrides)
    return MailContext(**defaults)  # type: ignore[arg-type]


class TestSmartFolderExcludedReprompt:
    """Excluded folder suggestions trigger reprompt, then error."""

    @pytest.mark.asyncio
    async def test_excluded_folder_triggers_reprompt(self) -> None:
        """First excluded folder suggestion returns retry_prompt."""
        plugin = SmartFolderPlugin()
        context = _make_context()
        response = SmartFolderResponse(folder="Spam", confidence=0.9, reason="Looks like spam")

        result = await plugin.execute(context, response)

        assert result.retry_prompt is not None
        assert "Spam" in result.retry_prompt
        assert result.actions_taken == []
        assert not result.requires_approval

    @pytest.mark.asyncio
    async def test_excluded_folder_reprompt_contains_existing_folders(self) -> None:
        """Retry prompt lists existing folders for the LLM."""
        plugin = SmartFolderPlugin()
        context = _make_context()
        response = SmartFolderResponse(folder="Trash", confidence=0.95, reason="Delete")

        result = await plugin.execute(context, response)

        assert result.retry_prompt is not None
        assert "Work" in result.retry_prompt
        assert "Finance" in result.retry_prompt

    @pytest.mark.asyncio
    async def test_excluded_folder_repeated_raises_error(self) -> None:
        """Second excluded folder suggestion raises ExcludedFolderError."""
        plugin = SmartFolderPlugin()
        context = _make_context()
        response = SmartFolderResponse(folder="Spam", confidence=0.9, reason="Spam again")

        # First call: reprompt
        result = await plugin.execute(context, response)
        assert result.retry_prompt is not None

        # Second call: error
        with pytest.raises(ExcludedFolderError, match="twice"):
            await plugin.execute(context, response)

    @pytest.mark.asyncio
    async def test_excluded_folder_case_insensitive(self) -> None:
        """Excluded folder matching is case-insensitive."""
        plugin = SmartFolderPlugin()
        context = _make_context()
        response = SmartFolderResponse(folder="SPAM", confidence=0.9, reason="Spam")

        result = await plugin.execute(context, response)
        assert result.retry_prompt is not None

    @pytest.mark.asyncio
    async def test_valid_folder_resets_retry_flag(self) -> None:
        """A valid folder suggestion resets the retry flag."""
        plugin = SmartFolderPlugin()
        context = _make_context()

        # First: trigger reprompt
        excluded_response = SmartFolderResponse(folder="Spam", confidence=0.9, reason="Spam")
        result = await plugin.execute(context, excluded_response)
        assert result.retry_prompt is not None

        # Second: valid folder (simulating reprompt success)
        valid_response = SmartFolderResponse(folder="Work", confidence=0.9, reason="Work email")
        result = await plugin.execute(context, valid_response)
        assert result.retry_prompt is None
        assert "move_to:Work" in result.actions_taken

        # Third: excluded again should trigger reprompt (not error)
        result = await plugin.execute(context, excluded_response)
        assert result.retry_prompt is not None

    @pytest.mark.asyncio
    async def test_non_excluded_folder_works_normally(self) -> None:
        """Non-excluded folder is processed normally."""
        plugin = SmartFolderPlugin()
        context = _make_context()
        response = SmartFolderResponse(folder="Work", confidence=0.9, reason="Work email")

        result = await plugin.execute(context, response)

        assert result.retry_prompt is None
        assert result.success
        assert "move_to:Work" in result.actions_taken
