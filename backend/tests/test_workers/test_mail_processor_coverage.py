"""Tests for app.workers.mail_processor — uncovered helper functions and error paths.

Covers: _update_tracked_email (updater callback, not_found, exception),
_update_tracked_status (_apply logic: retry_count, all fields),
_update_current_folder, _fail_queued_mails_for_folder,
_pause_entity / _pause_account / _pause_provider,
_mark_completed (all completion reason branches),
process_mail timeout handling.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import structlog

from app.models.mail import CompletionReason, ErrorType

MODULE = "app.workers.mail_processor"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log() -> structlog.stdlib.BoundLogger:
    return structlog.get_logger().bind()


def _make_tracked(
    *,
    status: str = "QUEUED",
    retry_count: int = 0,
    mail_uid: str = "100",
    current_folder: str = "INBOX",
) -> MagicMock:
    t = MagicMock()
    t.status = MagicMock()
    t.status.value = status
    t.retry_count = retry_count
    t.mail_uid = mail_uid
    t.current_folder = current_folder
    t.first_seen_uid = None
    t.first_seen_folder = None
    return t


def _session_ctx(tracked: MagicMock | None) -> MagicMock:
    """Create a mock get_session_ctx that yields a session returning tracked."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = tracked
    db.execute.return_value = result

    ctx = AsyncMock()
    ctx.__aenter__.return_value = db
    ctx.__aexit__.return_value = False
    return ctx


# ---------------------------------------------------------------------------
# _update_tracked_email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
async def test_update_tracked_email_calls_updater(mock_ctx: MagicMock) -> None:
    from app.workers.mail_processor import _update_tracked_email

    tracked = _make_tracked()
    mock_ctx.return_value = _session_ctx(tracked)

    updater = MagicMock()
    await _update_tracked_email("acc", "100", "INBOX", _log(), updater=updater)
    updater.assert_called_once_with(tracked)


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
async def test_update_tracked_email_not_found_logs_event(mock_ctx: MagicMock) -> None:
    from app.workers.mail_processor import _update_tracked_email

    mock_ctx.return_value = _session_ctx(None)

    updater = MagicMock()
    await _update_tracked_email(
        "acc",
        "100",
        "INBOX",
        _log(),
        updater=updater,
        not_found_event="test_not_found",
    )
    updater.assert_not_called()


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx", side_effect=RuntimeError("db"))
async def test_update_tracked_email_exception_non_fatal(mock_ctx: MagicMock) -> None:
    from app.workers.mail_processor import _update_tracked_email

    # Should not raise
    await _update_tracked_email("acc", "100", "INBOX", _log(), updater=MagicMock())


# ---------------------------------------------------------------------------
# _update_tracked_status — _apply logic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
async def test_update_tracked_status_sets_all_fields(mock_ctx: MagicMock) -> None:
    from app.models import TrackedEmailStatus
    from app.workers.mail_processor import _update_tracked_status

    tracked = _make_tracked(status="PROCESSING")
    mock_ctx.return_value = _session_ctx(tracked)

    await _update_tracked_status(
        "acc",
        "100",
        TrackedEmailStatus.COMPLETED,
        _log(),
        current_folder="INBOX",
        error="some error",
        error_type=ErrorType.MAIL,
        plugins_completed=["summary"],
        plugins_failed=["spam"],
        plugins_skipped=["calendar"],
        plugin_results={"summary": {"status": "ok"}},
        completion_reason=CompletionReason.FULL_PIPELINE,
    )

    assert tracked.status == TrackedEmailStatus.COMPLETED
    assert tracked.last_error == "some error"
    assert tracked.error_type == ErrorType.MAIL
    assert tracked.plugins_completed == ["summary"]
    assert tracked.plugins_failed == ["spam"]
    assert tracked.plugins_skipped == ["calendar"]
    assert tracked.plugin_results == {"summary": {"status": "ok"}}
    assert tracked.completion_reason == CompletionReason.FULL_PIPELINE


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
async def test_update_tracked_status_increments_retry_on_requeue(mock_ctx: MagicMock) -> None:
    from app.models import TrackedEmailStatus
    from app.workers.mail_processor import _update_tracked_status

    tracked = _make_tracked(status="PROCESSING", retry_count=2)
    # Override status to be an enum-like for comparison
    tracked.status = TrackedEmailStatus.PROCESSING
    mock_ctx.return_value = _session_ctx(tracked)

    await _update_tracked_status(
        "acc",
        "100",
        TrackedEmailStatus.QUEUED,
        _log(),
    )
    assert tracked.retry_count == 3


# ---------------------------------------------------------------------------
# _update_current_folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
async def test_update_current_folder_sets_folder_and_uid(mock_ctx: MagicMock) -> None:
    from app.workers.mail_processor import _update_current_folder

    tracked = _make_tracked()
    mock_ctx.return_value = _session_ctx(tracked)

    await _update_current_folder("acc", "100", "INBOX", "Archive", _log(), new_mail_uid="200")

    assert tracked.current_folder == "Archive"
    assert tracked.mail_uid == "200"


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
async def test_update_current_folder_no_new_uid(mock_ctx: MagicMock) -> None:
    from app.workers.mail_processor import _update_current_folder

    tracked = _make_tracked()
    mock_ctx.return_value = _session_ctx(tracked)

    await _update_current_folder("acc", "100", "INBOX", "Trash", _log())
    assert tracked.current_folder == "Trash"


# ---------------------------------------------------------------------------
# _fail_queued_mails_for_folder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
async def test_fail_queued_mails_executes_bulk_update(mock_ctx: MagicMock) -> None:
    from app.workers.mail_processor import _fail_queued_mails_for_folder

    db = AsyncMock()
    result = MagicMock()
    result.rowcount = 3
    db.execute.return_value = result

    ctx = AsyncMock()
    ctx.__aenter__.return_value = db
    ctx.__aexit__.return_value = False
    mock_ctx.return_value = ctx

    await _fail_queued_mails_for_folder("acc", "INBOX", "folder gone", _log())
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx", side_effect=RuntimeError("db"))
async def test_fail_queued_mails_exception_non_fatal(mock_ctx: MagicMock) -> None:
    from app.workers.mail_processor import _fail_queued_mails_for_folder

    # Should not raise
    await _fail_queued_mails_for_folder("acc", "INBOX", "err", _log())


# ---------------------------------------------------------------------------
# _pause_account / _pause_provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
async def test_pause_account_sets_pause_fields(mock_ctx: MagicMock) -> None:
    from app.workers.mail_processor import _pause_account

    db = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = db
    ctx.__aexit__.return_value = False
    mock_ctx.return_value = ctx

    await _pause_account(str(uuid4()), "imap down", _log())
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx")
async def test_pause_provider_sets_pause_fields(mock_ctx: MagicMock) -> None:
    from app.workers.mail_processor import _pause_provider

    db = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = db
    ctx.__aexit__.return_value = False
    mock_ctx.return_value = ctx

    await _pause_provider(str(uuid4()), "llm down", _log())
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@patch(f"{MODULE}.get_session_ctx", side_effect=RuntimeError("db"))
async def test_pause_entity_exception_non_fatal(mock_ctx: MagicMock) -> None:
    from app.workers.mail_processor import _pause_account

    # Should not raise
    await _pause_account(str(uuid4()), "err", _log())


# ---------------------------------------------------------------------------
# _mark_completed
# ---------------------------------------------------------------------------


def test_mark_completed_already_set_noop() -> None:
    from app.workers.mail_processor import _mark_completed

    result = MagicMock()
    result.completion_reason = CompletionReason.FULL_PIPELINE
    _mark_completed(result, _log())
    assert result.completion_reason == CompletionReason.FULL_PIPELINE


def test_mark_completed_pipeline_did_not_run() -> None:
    from app.workers.mail_processor import _mark_completed

    result = MagicMock()
    result.completion_reason = None
    result.plugins_executed = []
    result.approvals_created = 0
    result.auto_actions = []
    result.plugins_skipped = []
    result.plugins_failed = []
    result.plugins_completed = []
    _mark_completed(result, _log())
    assert result.completion_reason == CompletionReason.PIPELINE_DID_NOT_RUN


def test_mark_completed_all_plugins_failed() -> None:
    from app.workers.mail_processor import _mark_completed

    result = MagicMock()
    result.completion_reason = None
    result.plugins_executed = ["spam"]
    result.approvals_created = 0
    result.auto_actions = []
    result.plugins_skipped = []
    result.plugins_failed = ["spam"]
    result.plugins_completed = []
    _mark_completed(result, _log())
    assert result.completion_reason == CompletionReason.ALL_PLUGINS_FAILED


def test_mark_completed_partial_with_errors() -> None:
    from app.workers.mail_processor import _mark_completed

    result = MagicMock()
    result.completion_reason = None
    result.plugins_executed = ["spam", "summary"]
    result.approvals_created = 0
    result.auto_actions = []
    result.plugins_skipped = []
    result.plugins_failed = ["spam"]
    result.plugins_completed = ["summary"]
    _mark_completed(result, _log())
    assert result.completion_reason == CompletionReason.PARTIAL_WITH_ERRORS


def test_mark_completed_full_pipeline() -> None:
    from app.workers.mail_processor import _mark_completed

    result = MagicMock()
    result.completion_reason = None
    result.plugins_executed = ["summary"]
    result.approvals_created = 0
    result.auto_actions = []
    result.plugins_skipped = []
    result.plugins_failed = []
    result.plugins_completed = ["summary"]
    _mark_completed(result, _log())
    assert result.completion_reason == CompletionReason.FULL_PIPELINE


# ---------------------------------------------------------------------------
# process_mail — timeout path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(f"{MODULE}._clear_pipeline_progress", new_callable=AsyncMock)
@patch(f"{MODULE}._update_tracked_status", new_callable=AsyncMock)
@patch(f"{MODULE}._process_mail_inner", new_callable=AsyncMock, side_effect=TimeoutError)
async def test_process_mail_timeout_requeues(
    mock_inner: AsyncMock,
    mock_status: AsyncMock,
    mock_clear: AsyncMock,
) -> None:
    from app.workers.mail_processor import process_mail

    await process_mail({}, str(uuid4()), str(uuid4()), "100", "INBOX")

    mock_status.assert_awaited_once()
    args = mock_status.call_args
    from app.models import TrackedEmailStatus

    assert args[0][2] == TrackedEmailStatus.QUEUED
    assert args[1]["error_type"] == ErrorType.TIMEOUT
    mock_clear.assert_awaited_once()


@pytest.mark.asyncio
@patch(f"{MODULE}._clear_pipeline_progress", new_callable=AsyncMock)
@patch(f"{MODULE}._update_tracked_status", new_callable=AsyncMock)
@patch(f"{MODULE}._process_mail_inner", new_callable=AsyncMock, side_effect=asyncio.CancelledError)
async def test_process_mail_cancelled_requeues(
    mock_inner: AsyncMock,
    mock_status: AsyncMock,
    mock_clear: AsyncMock,
) -> None:

    from app.workers.mail_processor import process_mail

    await process_mail({}, str(uuid4()), str(uuid4()), "100")
    mock_status.assert_awaited_once()
    mock_clear.assert_awaited_once()
