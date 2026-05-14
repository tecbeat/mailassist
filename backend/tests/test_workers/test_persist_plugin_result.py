"""Tests for _persist_plugin_result in plugin_executor.

Verifies that each plugin branch dispatches to the correct save_* function
with the right arguments, and that missing mail_id causes early return.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.plugins.base import MailContext
from app.workers.plugin_executor import _persist_plugin_result

_PERSIST = "app.workers.plugin_executor"

USER_ID = str(uuid4())
ACCOUNT_ID = str(uuid4())
MAIL_ID = str(uuid4())


def _make_context(*, mail_id: str | None = MAIL_ID) -> MailContext:
    return MailContext(
        user_id=USER_ID,
        account_id=ACCOUNT_ID,
        mail_id=mail_id,
        sender="alice@example.com",
        sender_name="Alice",
        recipient="me@example.com",
        subject="Test",
        body="body",
        body_plain="body",
        body_html="<p>body</p>",
        headers={},
        date="2026-01-01T00:00:00Z",
        has_attachments=False,
        attachment_names=[],
        account_name="Test",
        account_email="me@example.com",
        mail_uid="123",
        existing_labels=["inbox"],
        existing_folders=["INBOX"],
        excluded_folders=[],
        folder_separator="/",
        mail_size=1024,
        thread_length=1,
        is_reply=False,
        is_forwarded=False,
    )


def _plugin(name: str) -> MagicMock:
    p = MagicMock()
    p.name = name
    return p


# ---- no mail_id ----


@pytest.mark.asyncio
async def test_no_mail_id_none_returns_early() -> None:
    """When mail_id is None, log error and do not call any save function."""
    ctx = _make_context(mail_id=None)
    log = MagicMock()

    with patch(f"{_PERSIST}.save_email_summary", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("email_summary"),
            context=ctx,
            ai_response=MagicMock(),
            log=log,
        )
        mock_save.assert_not_called()

    log.error.assert_called_once()


@pytest.mark.asyncio
async def test_no_mail_id_empty_string_returns_early() -> None:
    """Empty string mail_id is also treated as missing."""
    ctx = _make_context(mail_id="")
    log = MagicMock()

    with patch(f"{_PERSIST}.save_spam_detection", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("spam_detection"),
            context=ctx,
            ai_response=MagicMock(),
            log=log,
        )
        mock_save.assert_not_called()


# ---- email_summary ----


@pytest.mark.asyncio
async def test_email_summary_calls_save_email_summary() -> None:
    ctx = _make_context()
    resp = MagicMock()
    resp.summary = "short summary"
    resp.key_points = ["a", "b"]
    resp.urgency = "low"
    resp.action_required = False
    resp.action_description = None

    with patch(f"{_PERSIST}.save_email_summary", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("email_summary"),
            context=ctx,
            ai_response=resp,
            log=MagicMock(),
        )
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["user_id"] == UUID(USER_ID)
        assert kw["mail_id"] == UUID(MAIL_ID)
        assert kw["summary"] == "short summary"
        assert kw["key_points"] == ["a", "b"]
        assert kw["urgency"] == "low"
        assert kw["action_required"] is False
        assert kw["action_description"] is None


# ---- spam_detection ----


@pytest.mark.asyncio
async def test_spam_detection_calls_save_spam_detection() -> None:
    ctx = _make_context()
    resp = MagicMock()
    resp.is_spam = True
    resp.confidence = 0.95
    resp.reason = "known spam pattern"

    with patch(f"{_PERSIST}.save_spam_detection", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("spam_detection"),
            context=ctx,
            ai_response=resp,
            log=MagicMock(),
        )
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["user_id"] == UUID(USER_ID)
        assert kw["mail_id"] == UUID(MAIL_ID)
        assert kw["is_spam"] is True
        assert kw["confidence"] == 0.95
        assert kw["source"] == "ai"


# ---- newsletter_detection ----


@pytest.mark.asyncio
async def test_newsletter_not_newsletter_still_calls_save() -> None:
    """Even when is_newsletter=False the save function is still called."""
    ctx = _make_context()
    resp = MagicMock()
    resp.is_newsletter = False
    resp.newsletter_name = None
    resp.unsubscribe_url = None
    resp.has_unsubscribe = False

    with patch(f"{_PERSIST}.save_newsletter", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("newsletter_detection"),
            context=ctx,
            ai_response=resp,
            log=MagicMock(),
        )
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["is_newsletter"] is False
        assert kw["newsletter_name"] == "Unknown"
        assert kw["sender_address"] == "alice@example.com"


# ---- coupon_extraction ----


@pytest.mark.asyncio
async def test_coupon_extraction_calls_save_coupons() -> None:
    ctx = _make_context()
    coupon = MagicMock()
    coupon.model_dump.return_value = {"code": "SAVE10"}
    resp = MagicMock()
    resp.has_coupons = True
    resp.coupons = [coupon]

    with patch(f"{_PERSIST}.save_coupons", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("coupon_extraction"),
            context=ctx,
            ai_response=resp,
            log=MagicMock(),
        )
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["has_coupons"] is True
        assert kw["coupons"] == [{"code": "SAVE10"}]


# ---- labeling ----


@pytest.mark.asyncio
async def test_labeling_calls_save_applied_labels() -> None:
    ctx = _make_context()
    resp = MagicMock()
    resp.labels = ["important", "work"]

    with patch(f"{_PERSIST}.save_applied_labels", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("labeling"),
            context=ctx,
            ai_response=resp,
            log=MagicMock(),
        )
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["labels"] == ["important", "work"]
        assert kw["existing_labels"] == {"inbox"}


# ---- smart_folder ----


@pytest.mark.asyncio
async def test_smart_folder_calls_save_assigned_folder() -> None:
    ctx = _make_context()
    resp = MagicMock()
    resp.folder = "Receipts"
    resp.confidence = 0.88
    resp.reason = "contains receipt"

    with patch(f"{_PERSIST}.save_assigned_folder", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("smart_folder"),
            context=ctx,
            ai_response=resp,
            log=MagicMock(),
        )
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["folder"] == "Receipts"
        assert kw["existing_folders"] == {"INBOX"}


# ---- calendar_extraction ----


@pytest.mark.asyncio
async def test_calendar_extraction_calls_save_calendar_event() -> None:
    ctx = _make_context()
    resp = MagicMock()
    resp.has_event = True
    resp.title = "Meeting"
    resp.start = "2025-01-01T10:00"
    resp.end = "2025-01-01T11:00"
    resp.location = "Office"
    resp.description = "Sync"
    resp.is_all_day = False

    with patch(f"{_PERSIST}.save_calendar_event", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("calendar_extraction"),
            context=ctx,
            ai_response=resp,
            log=MagicMock(),
        )
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["has_event"] is True
        assert kw["title"] == "Meeting"


# ---- contacts ----


@pytest.mark.asyncio
async def test_contacts_calls_save_contact_assignment() -> None:
    ctx = _make_context()
    resp = MagicMock()
    resp.contact_id = str(uuid4())
    resp.contact_name = "Alice"
    resp.confidence = 0.9
    resp.reasoning = "exact match"
    resp.is_new_contact_suggestion = False

    with patch(f"{_PERSIST}.save_contact_assignment", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("contacts"),
            context=ctx,
            ai_response=resp,
            log=MagicMock(),
        )
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["sender_email"] == "alice@example.com"
        assert kw["auto_writeback"] is True


# ---- auto_reply ----


@pytest.mark.asyncio
async def test_auto_reply_calls_save_auto_reply() -> None:
    ctx = _make_context()
    resp = MagicMock()
    resp.should_reply = False
    resp.draft_body = None
    resp.tone = "professional"
    resp.reasoning = "no reply needed"

    with patch(f"{_PERSIST}.save_auto_reply", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("auto_reply"),
            context=ctx,
            ai_response=resp,
            log=MagicMock(),
        )
        mock_save.assert_awaited_once()
        kw = mock_save.call_args.kwargs
        assert kw["should_reply"] is False
        assert kw["tone"] == "professional"


# ---- mail_id UUID conversion ----


@pytest.mark.asyncio
async def test_mail_id_converted_to_uuid() -> None:
    """mail_id string from context is always converted to UUID before passing to save."""
    raw_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    ctx = _make_context(mail_id=raw_id)
    resp = MagicMock()
    resp.is_spam = False
    resp.confidence = 0.1
    resp.reason = "legit"

    with patch(f"{_PERSIST}.save_spam_detection", new_callable=AsyncMock) as mock_save:
        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=_plugin("spam_detection"),
            context=ctx,
            ai_response=resp,
            log=MagicMock(),
        )
        kw = mock_save.call_args.kwargs
        assert isinstance(kw["mail_id"], UUID)
        assert kw["mail_id"] == UUID(raw_id)
