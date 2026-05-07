"""Tests for CalendarExtractionPlugin past-event filtering."""

from datetime import UTC, datetime, timedelta

import pytest

from app.plugins.base import MailContext
from app.plugins.calendar_extraction import CalendarEventResponse, CalendarExtractionPlugin


def _make_context(*, include_past: bool = False) -> MailContext:
    return MailContext(
        user_id="user-1",
        account_id="acc-1",
        mail_uid="test-uid-123",
        sender="alice@example.com",
        sender_name="Alice",
        recipient="bob@example.com",
        subject="Meeting invite",
        body="Let's meet",
        body_plain="Let's meet",
        body_html="",
        headers={},
        date=datetime.now(UTC).isoformat(),
        has_attachments=False,
        attachment_names=[],
        account_name="Test",
        account_email="bob@example.com",
        existing_labels=[],
        existing_folders=["INBOX"],
        excluded_folders=[],
        folder_separator="/",
        mail_size=100,
        thread_length=1,
        is_reply=False,
        is_forwarded=False,
        calendar_include_past_events=include_past,
    )


def _future_iso() -> str:
    return (datetime.now(UTC) + timedelta(days=7)).isoformat()


def _past_iso() -> str:
    return (datetime.now(UTC) - timedelta(days=7)).isoformat()


@pytest.mark.anyio
async def test_past_event_skipped_by_default():
    plugin = CalendarExtractionPlugin()
    ctx = _make_context(include_past=False)
    response = CalendarEventResponse(
        has_event=True,
        title="Old meeting",
        start=_past_iso(),
        end=_past_iso(),
    )
    result = await plugin.execute(ctx, response)
    assert "calendar_event_in_past" in result.actions_taken
    assert not result.requires_approval


@pytest.mark.anyio
async def test_past_event_allowed_when_opted_in():
    plugin = CalendarExtractionPlugin()
    ctx = _make_context(include_past=True)
    response = CalendarEventResponse(
        has_event=True,
        title="Old meeting",
        start=_past_iso(),
        end=_past_iso(),
    )
    result = await plugin.execute(ctx, response)
    assert "calendar_event_in_past" not in result.actions_taken
    assert result.requires_approval


@pytest.mark.anyio
async def test_future_event_always_processed():
    plugin = CalendarExtractionPlugin()
    ctx = _make_context(include_past=False)
    response = CalendarEventResponse(
        has_event=True,
        title="Future meeting",
        start=_future_iso(),
        end=_future_iso(),
    )
    result = await plugin.execute(ctx, response)
    assert any("create_calendar_event" in a for a in result.actions_taken)
    assert result.requires_approval
