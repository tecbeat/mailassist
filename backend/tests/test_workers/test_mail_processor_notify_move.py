"""Integration tests for notify-before-move flow in mail_processor.

Verifies that the event notification is emitted BEFORE Phase 4 IMAP actions,
and that Phase 4 failure does not prevent the notification from having fired.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


MODULE = "app.workers.mail_processor"


@pytest.mark.asyncio
@patch(f"{MODULE}._clear_pipeline_progress", new_callable=AsyncMock)
@patch(f"{MODULE}._update_tracked_status", new_callable=AsyncMock)
@patch(f"{MODULE}._pause_account", new_callable=AsyncMock)
@patch(f"{MODULE}.execute_post_pipeline", new_callable=AsyncMock)
@patch(f"{MODULE}.get_event_bus")
@patch(f"{MODULE}._set_pipeline_progress", new_callable=AsyncMock)
@patch(f"{MODULE}.run_ai_pipeline", new_callable=AsyncMock)
@patch(f"{MODULE}._update_tracked_metadata", new_callable=AsyncMock)
@patch(f"{MODULE}.parse_raw_mail")
@patch(f"{MODULE}.fetch_raw_mail", new_callable=AsyncMock)
@patch(f"{MODULE}.get_session_ctx")
@patch(f"{MODULE}.fetch_account", new_callable=AsyncMock)
async def test_notify_fires_before_move(
    mock_fetch_account: AsyncMock,
    mock_session_ctx: MagicMock,
    mock_fetch_raw: AsyncMock,
    mock_parse: MagicMock,
    mock_update_meta: AsyncMock,
    mock_run_pipeline: AsyncMock,
    mock_set_progress: AsyncMock,
    mock_get_event_bus: MagicMock,
    mock_execute_post: AsyncMock,
    mock_pause: AsyncMock,
    mock_update_status: AsyncMock,
    mock_clear_progress: AsyncMock,
) -> None:
    """Event bus emit is called before execute_post_pipeline."""
    from app.workers.mail_processor import _process_mail_inner

    # Setup account
    account = MagicMock()
    account.id = uuid4()
    mock_fetch_account.return_value = account

    # DB session for subject_hint lookup
    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_ctx.return_value = ctx

    # Phase 2: fetch + parse
    fetch_result = MagicMock()
    fetch_result.relocated = False
    fetch_result.raw_bytes = b"raw"
    fetch_result.imap_folders = ["INBOX"]
    fetch_result.folder_separator = "/"
    mock_fetch_raw.return_value = fetch_result

    parsed = MagicMock()
    parsed.subject = "Test"
    parsed.sender = "a@b.com"
    parsed.date = None
    parsed.message_id = None
    mock_parse.return_value = parsed

    # Phase 3: pipeline result
    pipeline_result = MagicMock()
    pipeline_result.provider_error = False
    pipeline_result.plugins_executed = ["spam"]
    pipeline_result.approvals_created = []
    pipeline_result.mail_id = str(uuid4())
    pipeline_result.auto_actions = [{"action": "move", "folder": "Spam"}]
    pipeline_result.plugin_results = {
        "spam": MagicMock(display_name="Spam", to_dict=MagicMock(return_value={})),
    }
    mock_run_pipeline.return_value = pipeline_result

    # Event bus
    event_bus = AsyncMock()
    mock_get_event_bus.return_value = event_bus

    # Track call order
    call_order: list[str] = []
    event_bus.emit = AsyncMock(side_effect=lambda *a, **kw: call_order.append("emit"))
    mock_execute_post.side_effect = lambda *a, **kw: (call_order.append("move"), ("Spam", "999"))[1]

    import structlog

    log = structlog.get_logger()

    await _process_mail_inner(
        user_id=str(uuid4()),
        account_id=str(account.id),
        mail_uid="42",
        current_folder="INBOX",
        skip_plugins=None,
        log=log,
    )

    assert call_order.index("emit") < call_order.index("move")


@pytest.mark.asyncio
@patch(f"{MODULE}._clear_pipeline_progress", new_callable=AsyncMock)
@patch(f"{MODULE}._update_tracked_status", new_callable=AsyncMock)
@patch(f"{MODULE}._pause_account", new_callable=AsyncMock)
@patch(f"{MODULE}.execute_post_pipeline", new_callable=AsyncMock)
@patch(f"{MODULE}.get_event_bus")
@patch(f"{MODULE}._set_pipeline_progress", new_callable=AsyncMock)
@patch(f"{MODULE}.run_ai_pipeline", new_callable=AsyncMock)
@patch(f"{MODULE}._update_tracked_metadata", new_callable=AsyncMock)
@patch(f"{MODULE}.parse_raw_mail")
@patch(f"{MODULE}.fetch_raw_mail", new_callable=AsyncMock)
@patch(f"{MODULE}.get_session_ctx")
@patch(f"{MODULE}.fetch_account", new_callable=AsyncMock)
async def test_notify_still_fired_when_phase4_fails(
    mock_fetch_account: AsyncMock,
    mock_session_ctx: MagicMock,
    mock_fetch_raw: AsyncMock,
    mock_parse: MagicMock,
    mock_update_meta: AsyncMock,
    mock_run_pipeline: AsyncMock,
    mock_set_progress: AsyncMock,
    mock_get_event_bus: MagicMock,
    mock_execute_post: AsyncMock,
    mock_pause: AsyncMock,
    mock_update_status: AsyncMock,
    mock_clear_progress: AsyncMock,
) -> None:
    """Notification is emitted even when Phase 4 raises an exception."""
    from app.workers.mail_processor import _process_mail_inner

    account = MagicMock()
    account.id = uuid4()
    mock_fetch_account.return_value = account

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_ctx.return_value = ctx

    fetch_result = MagicMock()
    fetch_result.relocated = False
    fetch_result.raw_bytes = b"raw"
    fetch_result.imap_folders = ["INBOX"]
    fetch_result.folder_separator = "/"
    mock_fetch_raw.return_value = fetch_result

    parsed = MagicMock()
    parsed.subject = "Test"
    parsed.sender = "a@b.com"
    parsed.date = None
    parsed.message_id = None
    mock_parse.return_value = parsed

    pipeline_result = MagicMock()
    pipeline_result.provider_error = False
    pipeline_result.plugins_executed = ["spam"]
    pipeline_result.approvals_created = []
    pipeline_result.mail_id = str(uuid4())
    pipeline_result.auto_actions = [{"action": "move", "folder": "Spam"}]
    pipeline_result.plugin_results = {
        "spam": MagicMock(display_name="Spam", to_dict=MagicMock(return_value={})),
    }
    mock_run_pipeline.return_value = pipeline_result

    event_bus = AsyncMock()
    mock_get_event_bus.return_value = event_bus

    # Phase 4 fails
    mock_execute_post.side_effect = ConnectionError("IMAP server unavailable")

    import structlog

    log = structlog.get_logger()

    await _process_mail_inner(
        user_id=str(uuid4()),
        account_id=str(account.id),
        mail_uid="42",
        current_folder="INBOX",
        skip_plugins=None,
        log=log,
    )

    # Notification was still emitted
    event_bus.emit.assert_awaited_once()
    # Account was paused due to Phase 4 failure
    mock_pause.assert_awaited_once()
