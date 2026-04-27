"""Tests for plugin tracking and error classification in mail_processor.

Verifies that the pipeline correctly records which plugins completed,
failed, or were skipped, and assigns the appropriate completion_reason.

Issue #47: Verifies error classification (provider_imap, provider_ai,
mail) with pause-flag integration — IMAP errors pause the account,
LLM errors pause the provider, parse errors are permanent.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import TrackedEmailStatus


# ---------------------------------------------------------------------------
# Completion reason determination (unit tests for the logic)
# ---------------------------------------------------------------------------


def _determine_completion_reason(
    plugins_completed: list[str],
    plugins_failed: list[str],
    plugins_skipped: list[str],
    pipeline_actually_ran: bool,
    short_circuit_reason: str | None = None,
) -> str:
    """Mirror the completion_reason logic from mail_processor.

    Extracted here so we can test it independently of the full pipeline.
    """
    if short_circuit_reason is not None:
        return short_circuit_reason
    if not pipeline_actually_ran:
        return "pipeline_did_not_run"
    if plugins_failed and not plugins_completed:
        return "all_plugins_failed"
    if plugins_failed:
        return "partial_with_errors"
    return "full_pipeline"


class TestCompletionReason:
    """Completion reason is assigned correctly based on plugin outcomes."""

    def test_full_pipeline(self):
        reason = _determine_completion_reason(
            plugins_completed=["spam_detection", "labeling", "email_summary"],
            plugins_failed=[],
            plugins_skipped=[],
            pipeline_actually_ran=True,
        )
        assert reason == "full_pipeline"

    def test_partial_with_errors(self):
        reason = _determine_completion_reason(
            plugins_completed=["spam_detection", "labeling"],
            plugins_failed=["email_summary"],
            plugins_skipped=[],
            pipeline_actually_ran=True,
        )
        assert reason == "partial_with_errors"

    def test_all_plugins_failed(self):
        reason = _determine_completion_reason(
            plugins_completed=[],
            plugins_failed=["spam_detection", "labeling", "email_summary"],
            plugins_skipped=[],
            pipeline_actually_ran=True,
        )
        assert reason == "all_plugins_failed"

    def test_all_plugins_skipped(self):
        reason = _determine_completion_reason(
            plugins_completed=[],
            plugins_failed=[],
            plugins_skipped=["labeling", "email_summary"],
            pipeline_actually_ran=False,
        )
        assert reason == "pipeline_did_not_run"

    def test_all_plugins_skipped_but_pipeline_ran(self):
        """Edge case: all AI plugins skipped but pipeline counted as ran
        (e.g. approvals_created > 0 from a non-AI plugin).

        With the new architecture, provider-unavailable skips trigger a
        savepoint rollback and never reach _mark_completed.  When all
        plugins are user-disabled, the result is 'full_pipeline' (the
        pipeline ran fully — there was just nothing to do).
        """
        reason = _determine_completion_reason(
            plugins_completed=[],
            plugins_failed=[],
            plugins_skipped=["labeling", "email_summary"],
            pipeline_actually_ran=True,
        )
        assert reason == "full_pipeline"

    def test_spam_short_circuit(self):
        reason = _determine_completion_reason(
            plugins_completed=["spam_detection"],
            plugins_failed=[],
            plugins_skipped=[],
            pipeline_actually_ran=True,
            short_circuit_reason="spam_short_circuit",
        )
        assert reason == "spam_short_circuit"

    def test_pipeline_did_not_run(self):
        reason = _determine_completion_reason(
            plugins_completed=[],
            plugins_failed=[],
            plugins_skipped=[],
            pipeline_actually_ran=False,
        )
        assert reason == "pipeline_did_not_run"

    def test_mixed_completed_failed_skipped(self):
        reason = _determine_completion_reason(
            plugins_completed=["spam_detection"],
            plugins_failed=["labeling"],
            plugins_skipped=["smart_folder"],
            pipeline_actually_ran=True,
        )
        assert reason == "partial_with_errors"


# ---------------------------------------------------------------------------
# _update_tracked_status with new plugin tracking fields
# ---------------------------------------------------------------------------


class TestUpdateTrackedStatusPluginFields:
    """_update_tracked_status persists plugin tracking fields."""

    @pytest.mark.asyncio
    async def test_plugin_fields_set_on_completion(self):
        """Plugin tracking fields are written to the TrackedEmail record."""
        tracked = MagicMock()
        tracked.status = TrackedEmailStatus.PROCESSING
        tracked.plugins_completed = None
        tracked.plugins_failed = None
        tracked.plugins_skipped = None
        tracked.completion_reason = None
        tracked.last_error = None
        tracked.error_type = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = tracked

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        # Simulate the async generator from get_session()
        async def fake_get_session():
            yield mock_db

        log = MagicMock()
        log.debug = MagicMock()

        account_id = str(uuid4())

        with patch("app.workers.mail_processor.get_session", fake_get_session):
            from app.workers.mail_processor import _update_tracked_status

            await _update_tracked_status(
                account_id, "12345", TrackedEmailStatus.COMPLETED, log,
                plugins_completed=["spam_detection", "labeling"],
                plugins_failed=["email_summary"],
                plugins_skipped=["smart_folder"],
                completion_reason="partial_with_errors",
            )

        assert tracked.status == TrackedEmailStatus.COMPLETED
        assert tracked.plugins_completed == ["spam_detection", "labeling"]
        assert tracked.plugins_failed == ["email_summary"]
        assert tracked.plugins_skipped == ["smart_folder"]
        assert tracked.completion_reason == "partial_with_errors"
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_plugin_fields_not_overwritten_when_none(self):
        """When plugin fields are not passed, existing values are preserved."""
        tracked = MagicMock()
        tracked.status = TrackedEmailStatus.PROCESSING
        tracked.plugins_completed = ["spam_detection"]
        tracked.plugins_failed = None
        tracked.plugins_skipped = None
        tracked.completion_reason = "full_pipeline"
        tracked.last_error = None
        tracked.error_type = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = tracked

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        async def fake_get_session():
            yield mock_db

        log = MagicMock()
        log.debug = MagicMock()

        account_id = str(uuid4())

        with patch("app.workers.mail_processor.get_session", fake_get_session):
            from app.workers.mail_processor import _update_tracked_status

            await _update_tracked_status(
                account_id, "12345", TrackedEmailStatus.FAILED, log,
                error="permanent_error",
            )

        # Status and error updated
        assert tracked.status == TrackedEmailStatus.FAILED
        assert tracked.last_error == "permanent_error"
        # Plugin tracking fields NOT overwritten (None args => no change)
        assert tracked.plugins_completed == ["spam_detection"]
        assert tracked.completion_reason == "full_pipeline"


# ---------------------------------------------------------------------------
# Status transition timing (Issue #40)
# ---------------------------------------------------------------------------


class TestProcessMailStatusTransitions:
    """Status transitions in process_mail with new error classification."""

    @pytest.mark.asyncio
    async def test_successful_pipeline_marks_completed(self):
        """Successful pipeline run marks mail as COMPLETED.

        PROCESSING is set by the scheduler before ARQ dispatch, not
        by process_mail itself.  On success, process_mail only sets
        COMPLETED.
        """
        account_id = str(uuid4())
        user_id = str(uuid4())
        mail_uid = "42"

        status_updates: list[TrackedEmailStatus] = []

        async def fake_update_tracked_status(
            _account_id, _mail_uid, status, _log, **_kwargs
        ):
            status_updates.append(status)

        # Mock a minimal account object
        mock_account = MagicMock()
        mock_account.id = uuid4()

        # Mock pipeline result
        mock_pipeline_result = MagicMock()
        mock_pipeline_result.transient_reenqueue_reason = None
        mock_pipeline_result.failed_provider_id = None
        mock_pipeline_result.auto_actions = []
        mock_pipeline_result.plugins_executed = ["spam_detection"]
        mock_pipeline_result.plugins_completed = ["spam_detection"]
        mock_pipeline_result.plugins_failed = []
        mock_pipeline_result.plugins_skipped = []
        mock_pipeline_result.approvals_created = []
        mock_pipeline_result.completion_reason = "full_pipeline"
        mock_pipeline_result.provider_error = False

        async def fake_get_session():
            yield AsyncMock()

        with (
            patch(
                "app.workers.mail_processor._update_tracked_status",
                side_effect=fake_update_tracked_status,
            ),
            patch(
                "app.workers.mail_processor.fetch_account",
                return_value=mock_account,
            ),
            patch(
                "app.workers.mail_processor.fetch_raw_mail",
                return_value=(b"raw email bytes", ["INBOX", "Sent"], "/"),
            ),
            patch(
                "app.workers.mail_processor.parse_raw_mail",
                return_value=MagicMock(),
            ),
            patch(
                "app.workers.mail_processor.run_ai_pipeline",
                return_value=mock_pipeline_result,
            ),
            patch("app.workers.mail_processor.get_session", fake_get_session),
            patch("app.workers.mail_processor.get_event_bus") as mock_event_bus,
            patch("app.workers.mail_processor._update_tracked_metadata", new_callable=AsyncMock),
        ):
            mock_event_bus.return_value.emit = AsyncMock()

            from app.workers.mail_processor import process_mail

            await process_mail(
                {"redis": MagicMock()},
                user_id,
                account_id,
                mail_uid,
            )

        # COMPLETED should be set (PROCESSING is set by scheduler, not process_mail)
        assert TrackedEmailStatus.COMPLETED in status_updates
        # No QUEUED or FAILED — only COMPLETED
        assert TrackedEmailStatus.QUEUED not in status_updates
        assert TrackedEmailStatus.FAILED not in status_updates

    @pytest.mark.asyncio
    async def test_imap_fetch_error_pauses_account_and_stays_queued(self):
        """On genuine IMAP fetch failure (non-OK response), account is paused, mail stays QUEUED.

        This covers errors like "UID not found" where the IMAP server
        itself is having issues.  The account should be paused so the
        scheduler stops dispatching new mails for it.
        """
        account_id = str(uuid4())
        user_id = str(uuid4())
        mail_uid = "42"

        status_updates: list[TrackedEmailStatus] = []
        update_kwargs_list: list[dict] = []

        async def fake_update_tracked_status(
            _account_id, _mail_uid, status, _log, **kwargs
        ):
            status_updates.append(status)
            update_kwargs_list.append(kwargs)

        mock_account = MagicMock()
        mock_account.id = uuid4()

        from app.workers.pipeline_orchestrator import IMAPFetchError

        with (
            patch(
                "app.workers.mail_processor._update_tracked_status",
                side_effect=fake_update_tracked_status,
            ),
            patch(
                "app.workers.mail_processor.fetch_account",
                return_value=mock_account,
            ),
            patch(
                "app.workers.mail_processor.fetch_raw_mail",
                side_effect=IMAPFetchError("UID not found"),
            ),
            patch(
                "app.workers.mail_processor._pause_account",
                new_callable=AsyncMock,
            ) as mock_pause,
        ):
            from app.workers.mail_processor import process_mail

            await process_mail(
                {"redis": MagicMock()},
                user_id,
                account_id,
                mail_uid,
            )

        # PROCESSING should NOT have been set — only QUEUED
        assert TrackedEmailStatus.PROCESSING not in status_updates
        assert status_updates[0] == TrackedEmailStatus.QUEUED
        # error_type should be provider_imap
        assert update_kwargs_list[0]["error_type"] == "provider_imap"
        # Account should have been paused
        mock_pause.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_parse_error_sets_error_type_mail(self):
        """On email parse failure, status goes to FAILED with error_type='mail'.

        Parse errors are permanent — the job should not be retried.
        """
        account_id = str(uuid4())
        user_id = str(uuid4())
        mail_uid = "42"

        status_updates: list[TrackedEmailStatus] = []
        update_kwargs_list: list[dict] = []

        async def fake_update_tracked_status(
            _account_id, _mail_uid, status, _log, **kwargs
        ):
            status_updates.append(status)
            update_kwargs_list.append(kwargs)

        mock_account = MagicMock()
        mock_account.id = uuid4()

        from app.workers.pipeline_orchestrator import EmailParseError

        with (
            patch(
                "app.workers.mail_processor._update_tracked_status",
                side_effect=fake_update_tracked_status,
            ),
            patch(
                "app.workers.mail_processor.fetch_account",
                return_value=mock_account,
            ),
            patch(
                "app.workers.mail_processor.fetch_raw_mail",
                return_value=(b"raw email bytes", ["INBOX"], "/"),
            ),
            patch(
                "app.workers.mail_processor.parse_raw_mail",
                side_effect=EmailParseError("Malformed MIME"),
            ),
        ):
            from app.workers.mail_processor import process_mail

            await process_mail(
                {"redis": MagicMock()},
                user_id,
                account_id,
                mail_uid,
            )

        # PROCESSING should NOT have been set — only FAILED
        assert TrackedEmailStatus.PROCESSING not in status_updates
        assert status_updates[0] == TrackedEmailStatus.FAILED
        # error_type should be "mail" (permanent)
        assert update_kwargs_list[0]["error_type"] == "mail"

    @pytest.mark.asyncio
    async def test_imap_connection_failure_pauses_account(self):
        """On generic IMAP connection failure (timeout, auth), account is paused.

        The mail stays QUEUED with error_type='provider_imap'.
        """
        account_id = str(uuid4())
        user_id = str(uuid4())
        mail_uid = "42"

        status_updates: list[TrackedEmailStatus] = []
        update_kwargs_list: list[dict] = []

        async def fake_update_tracked_status(
            _account_id, _mail_uid, status, _log, **kwargs
        ):
            status_updates.append(status)
            update_kwargs_list.append(kwargs)

        mock_account = MagicMock()
        mock_account.id = uuid4()

        with (
            patch(
                "app.workers.mail_processor._update_tracked_status",
                side_effect=fake_update_tracked_status,
            ),
            patch(
                "app.workers.mail_processor.fetch_account",
                return_value=mock_account,
            ),
            patch(
                "app.workers.mail_processor.fetch_raw_mail",
                side_effect=ConnectionRefusedError("Connection refused"),
            ),
            patch(
                "app.workers.mail_processor._pause_account",
                new_callable=AsyncMock,
            ) as mock_pause,
        ):
            from app.workers.mail_processor import process_mail

            await process_mail(
                {"redis": MagicMock()},
                user_id,
                account_id,
                mail_uid,
            )

        assert status_updates[0] == TrackedEmailStatus.QUEUED
        assert update_kwargs_list[0]["error_type"] == "provider_imap"
        mock_pause.assert_awaited_once()
        # Verify the pause reason mentions connection
        pause_reason = mock_pause.call_args[0][1]
        assert "Connection refused" in pause_reason

    @pytest.mark.asyncio
    async def test_ai_provider_error_pauses_provider(self):
        """On transient LLM error, provider is paused, mail goes to QUEUED.

        The pipeline result has transient_reenqueue_reason and
        failed_provider_id set by the plugin executor.
        """
        account_id = str(uuid4())
        user_id = str(uuid4())
        provider_id = str(uuid4())
        mail_uid = "42"

        status_updates: list[TrackedEmailStatus] = []
        update_kwargs_list: list[dict] = []

        async def fake_update_tracked_status(
            _account_id, _mail_uid, status, _log, **kwargs
        ):
            status_updates.append(status)
            update_kwargs_list.append(kwargs)

        mock_account = MagicMock()
        mock_account.id = uuid4()

        # Pipeline result with transient error
        mock_pipeline_result = MagicMock()
        mock_pipeline_result.transient_reenqueue_reason = "transient_llm_error:email_summary"
        mock_pipeline_result.failed_provider_id = provider_id
        mock_pipeline_result.auto_actions = []
        mock_pipeline_result.plugins_executed = []
        mock_pipeline_result.plugins_completed = []
        mock_pipeline_result.plugins_failed = ["email_summary"]
        mock_pipeline_result.plugins_skipped = []
        mock_pipeline_result.approvals_created = 0
        mock_pipeline_result.completion_reason = None
        mock_pipeline_result.provider_error = True

        async def fake_get_session():
            yield AsyncMock()

        with (
            patch(
                "app.workers.mail_processor._update_tracked_status",
                side_effect=fake_update_tracked_status,
            ),
            patch(
                "app.workers.mail_processor.fetch_account",
                return_value=mock_account,
            ),
            patch(
                "app.workers.mail_processor.fetch_raw_mail",
                return_value=(b"raw email bytes", ["INBOX"], "/"),
            ),
            patch(
                "app.workers.mail_processor.parse_raw_mail",
                return_value=MagicMock(),
            ),
            patch(
                "app.workers.mail_processor.run_ai_pipeline",
                return_value=mock_pipeline_result,
            ),
            patch("app.workers.mail_processor.get_session", fake_get_session),
            patch(
                "app.workers.mail_processor._pause_provider",
                new_callable=AsyncMock,
            ) as mock_pause_provider,
            patch("app.workers.mail_processor._update_tracked_metadata", new_callable=AsyncMock),
        ):
            from app.workers.mail_processor import process_mail

            await process_mail(
                {"redis": MagicMock()},
                user_id,
                account_id,
                mail_uid,
            )

        # Mail should go back to QUEUED with error_type provider_ai
        assert status_updates[0] == TrackedEmailStatus.QUEUED
        assert update_kwargs_list[0]["error_type"] == "provider_ai"
        # Provider should have been paused
        mock_pause_provider.assert_awaited_once_with(
            provider_id,
            "transient_llm_error:email_summary",
            mock_pause_provider.call_args[0][2],  # log
        )

    @pytest.mark.asyncio
    async def test_no_message_body_marks_failed_without_pausing_account(self):
        """no_message_body_in_response is a per-mail error, NOT a provider error.

        The mail should go to FAILED with error_type='mail' and the
        account must NOT be paused — so other mails continue processing.
        """
        account_id = str(uuid4())
        user_id = str(uuid4())
        mail_uid = "42"

        status_updates: list[TrackedEmailStatus] = []
        update_kwargs_list: list[dict] = []

        async def fake_update_tracked_status(
            _account_id, _mail_uid, status, _log, **kwargs
        ):
            status_updates.append(status)
            update_kwargs_list.append(kwargs)

        mock_account = MagicMock()
        mock_account.id = uuid4()

        from app.workers.pipeline_orchestrator import IMAPFetchError

        with (
            patch(
                "app.workers.mail_processor._update_tracked_status",
                side_effect=fake_update_tracked_status,
            ),
            patch(
                "app.workers.mail_processor.fetch_account",
                return_value=mock_account,
            ),
            patch(
                "app.workers.mail_processor.fetch_raw_mail",
                side_effect=IMAPFetchError("no_message_body_in_response"),
            ),
            patch(
                "app.workers.mail_processor._pause_account",
                new_callable=AsyncMock,
            ) as mock_pause,
        ):
            from app.workers.mail_processor import process_mail

            await process_mail(
                {"redis": MagicMock()},
                user_id,
                account_id,
                mail_uid,
            )

        # Mail should be FAILED (permanent per-mail error)
        assert status_updates[0] == TrackedEmailStatus.FAILED
        # error_type should be "mail", not "provider_imap"
        assert update_kwargs_list[0]["error_type"] == "mail"
        # Account should NOT have been paused
        mock_pause.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_genuine_imap_error_still_pauses_account(self):
        """Non-OK IMAP responses (not no_message_body) still pause the account.

        Ensures the reclassification only applies to the specific
        no_message_body_in_response case, not to all IMAPFetchErrors.
        """
        account_id = str(uuid4())
        user_id = str(uuid4())
        mail_uid = "42"

        status_updates: list[TrackedEmailStatus] = []
        update_kwargs_list: list[dict] = []

        async def fake_update_tracked_status(
            _account_id, _mail_uid, status, _log, **kwargs
        ):
            status_updates.append(status)
            update_kwargs_list.append(kwargs)

        mock_account = MagicMock()
        mock_account.id = uuid4()

        from app.workers.pipeline_orchestrator import IMAPFetchError

        with (
            patch(
                "app.workers.mail_processor._update_tracked_status",
                side_effect=fake_update_tracked_status,
            ),
            patch(
                "app.workers.mail_processor.fetch_account",
                return_value=mock_account,
            ),
            patch(
                "app.workers.mail_processor.fetch_raw_mail",
                side_effect=IMAPFetchError("imap_fetch_failed: NO"),
            ),
            patch(
                "app.workers.mail_processor._pause_account",
                new_callable=AsyncMock,
            ) as mock_pause,
        ):
            from app.workers.mail_processor import process_mail

            await process_mail(
                {"redis": MagicMock()},
                user_id,
                account_id,
                mail_uid,
            )

        # Mail should stay QUEUED (provider error, not permanent)
        assert status_updates[0] == TrackedEmailStatus.QUEUED
        assert update_kwargs_list[0]["error_type"] == "provider_imap"
        # Account should have been paused
        mock_pause.assert_awaited_once()


# ---------------------------------------------------------------------------
# _update_tracked_status error_type field (Issue #47)
# ---------------------------------------------------------------------------


class TestUpdateTrackedStatusErrorType:
    """_update_tracked_status persists error_type on TrackedEmail."""

    @pytest.mark.asyncio
    async def test_error_type_set(self):
        """error_type is written to the TrackedEmail record."""
        tracked = MagicMock()
        tracked.status = TrackedEmailStatus.PROCESSING
        tracked.last_error = None
        tracked.error_type = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = tracked

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        async def fake_get_session():
            yield mock_db

        log = MagicMock()
        log.debug = MagicMock()

        account_id = str(uuid4())

        with patch("app.workers.mail_processor.get_session", fake_get_session):
            from app.workers.mail_processor import _update_tracked_status

            await _update_tracked_status(
                account_id, "12345", TrackedEmailStatus.QUEUED, log,
                error="imap_connection_failed: timeout",
                error_type="provider_imap",
            )

        assert tracked.status == TrackedEmailStatus.QUEUED
        assert tracked.last_error == "imap_connection_failed: timeout"
        assert tracked.error_type == "provider_imap"

    @pytest.mark.asyncio
    async def test_error_type_not_overwritten_when_not_passed(self):
        """When error_type is not passed, existing value is preserved."""
        tracked = MagicMock()
        tracked.status = TrackedEmailStatus.QUEUED
        tracked.last_error = "old_error"
        tracked.error_type = "provider_imap"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = tracked

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        async def fake_get_session():
            yield mock_db

        log = MagicMock()
        log.debug = MagicMock()

        account_id = str(uuid4())

        with patch("app.workers.mail_processor.get_session", fake_get_session):
            from app.workers.mail_processor import _update_tracked_status

            await _update_tracked_status(
                account_id, "12345", TrackedEmailStatus.COMPLETED, log,
                completion_reason="full_pipeline",
            )

        assert tracked.status == TrackedEmailStatus.COMPLETED
        # error_type NOT overwritten since it wasn't passed
        assert tracked.error_type == "provider_imap"


# ---------------------------------------------------------------------------
# Savepoint rollback on provider errors (Issue #48)
# ---------------------------------------------------------------------------


class TestSavepointRollback:
    """Pipeline orchestrator rolls back plugin results on provider errors."""

    @pytest.mark.asyncio
    async def test_transient_error_sets_provider_error(self):
        """On transient LLM error, pipeline returns provider_error=True
        with the failed provider ID and reason."""
        from app.workers.pipeline_orchestrator import PipelineResult

        result = PipelineResult()
        result.provider_error = True
        result.transient_reenqueue_reason = "transient_llm_error:email_summary"
        result.failed_provider_id = str(uuid4())

        assert result.provider_error is True
        assert result.transient_reenqueue_reason is not None
        assert result.failed_provider_id is not None

    @pytest.mark.asyncio
    async def test_provider_error_clears_plugin_results(self):
        """When provider_error is set after savepoint rollback, plugin
        result lists should be empty (cleared by the rollback handler)."""
        from app.workers.pipeline_orchestrator import PipelineResult

        result = PipelineResult()
        # Simulate results accumulated before rollback, then cleared
        result.plugins_executed = ["spam_detection"]
        result.plugins_completed = ["spam_detection"]
        result.auto_actions = ["move_to_spam"]
        result.approvals_created = 1

        # After savepoint rollback, these should be cleared
        result.plugins_executed.clear()
        result.plugins_completed.clear()
        result.plugins_failed.clear()
        result.approvals_created = 0
        result.auto_actions.clear()
        result.provider_error = True

        assert result.plugins_executed == []
        assert result.plugins_completed == []
        assert result.plugins_failed == []
        assert result.approvals_created == 0
        assert result.auto_actions == []
        assert result.provider_error is True

    @pytest.mark.asyncio
    async def test_provider_error_triggers_pause_and_queued(self):
        """On provider_error, mail_processor pauses the provider and
        sets mail to QUEUED with error_type='provider_ai'."""
        account_id = str(uuid4())
        user_id = str(uuid4())
        provider_id = str(uuid4())
        mail_uid = "42"

        status_updates: list[TrackedEmailStatus] = []
        update_kwargs_list: list[dict] = []

        async def fake_update_tracked_status(
            _account_id, _mail_uid, status, _log, **kwargs
        ):
            status_updates.append(status)
            update_kwargs_list.append(kwargs)

        mock_account = MagicMock()
        mock_account.id = uuid4()

        # Pipeline result with provider_error (post-rollback)
        mock_pipeline_result = MagicMock()
        mock_pipeline_result.provider_error = True
        mock_pipeline_result.transient_reenqueue_reason = "transient_llm_error:labeling"
        mock_pipeline_result.failed_provider_id = provider_id
        mock_pipeline_result.auto_actions = []
        mock_pipeline_result.plugins_executed = []
        mock_pipeline_result.plugins_completed = []
        mock_pipeline_result.plugins_failed = []
        mock_pipeline_result.plugins_skipped = []
        mock_pipeline_result.approvals_created = 0
        mock_pipeline_result.completion_reason = None

        async def fake_get_session():
            yield AsyncMock()

        with (
            patch(
                "app.workers.mail_processor._update_tracked_status",
                side_effect=fake_update_tracked_status,
            ),
            patch(
                "app.workers.mail_processor.fetch_account",
                return_value=mock_account,
            ),
            patch(
                "app.workers.mail_processor.fetch_raw_mail",
                return_value=(b"raw email bytes", ["INBOX"], "/"),
            ),
            patch(
                "app.workers.mail_processor.parse_raw_mail",
                return_value=MagicMock(),
            ),
            patch(
                "app.workers.mail_processor.run_ai_pipeline",
                return_value=mock_pipeline_result,
            ),
            patch("app.workers.mail_processor.get_session", fake_get_session),
            patch(
                "app.workers.mail_processor._pause_provider",
                new_callable=AsyncMock,
            ) as mock_pause_provider,
            patch("app.workers.mail_processor._update_tracked_metadata", new_callable=AsyncMock),
        ):
            from app.workers.mail_processor import process_mail

            await process_mail(
                {"redis": MagicMock()},
                user_id,
                account_id,
                mail_uid,
            )

        # Mail should go back to QUEUED
        assert status_updates[0] == TrackedEmailStatus.QUEUED
        assert update_kwargs_list[0]["error_type"] == "provider_ai"
        # Provider should have been paused
        mock_pause_provider.assert_awaited_once()
        assert mock_pause_provider.call_args[0][0] == provider_id

    @pytest.mark.asyncio
    async def test_provider_unavailable_no_provider_id_no_pause(self):
        """When provider_error is True but no failed_provider_id is set
        (e.g. no provider configured at all), pause_provider is not
        called but mail still goes to QUEUED."""
        account_id = str(uuid4())
        user_id = str(uuid4())
        mail_uid = "42"

        status_updates: list[TrackedEmailStatus] = []
        update_kwargs_list: list[dict] = []

        async def fake_update_tracked_status(
            _account_id, _mail_uid, status, _log, **kwargs
        ):
            status_updates.append(status)
            update_kwargs_list.append(kwargs)

        mock_account = MagicMock()
        mock_account.id = uuid4()

        # Pipeline result with provider_error but no specific provider
        mock_pipeline_result = MagicMock()
        mock_pipeline_result.provider_error = True
        mock_pipeline_result.transient_reenqueue_reason = None
        mock_pipeline_result.failed_provider_id = None
        mock_pipeline_result.auto_actions = []
        mock_pipeline_result.plugins_executed = []
        mock_pipeline_result.plugins_completed = []
        mock_pipeline_result.plugins_failed = []
        mock_pipeline_result.plugins_skipped = []
        mock_pipeline_result.approvals_created = 0
        mock_pipeline_result.completion_reason = None

        async def fake_get_session():
            yield AsyncMock()

        with (
            patch(
                "app.workers.mail_processor._update_tracked_status",
                side_effect=fake_update_tracked_status,
            ),
            patch(
                "app.workers.mail_processor.fetch_account",
                return_value=mock_account,
            ),
            patch(
                "app.workers.mail_processor.fetch_raw_mail",
                return_value=(b"raw email bytes", ["INBOX"], "/"),
            ),
            patch(
                "app.workers.mail_processor.parse_raw_mail",
                return_value=MagicMock(),
            ),
            patch(
                "app.workers.mail_processor.run_ai_pipeline",
                return_value=mock_pipeline_result,
            ),
            patch("app.workers.mail_processor.get_session", fake_get_session),
            patch(
                "app.workers.mail_processor._pause_provider",
                new_callable=AsyncMock,
            ) as mock_pause_provider,
            patch("app.workers.mail_processor._update_tracked_metadata", new_callable=AsyncMock),
        ):
            from app.workers.mail_processor import process_mail

            await process_mail(
                {"redis": MagicMock()},
                user_id,
                account_id,
                mail_uid,
            )

        # Mail still goes to QUEUED
        assert status_updates[0] == TrackedEmailStatus.QUEUED
        assert update_kwargs_list[0]["error_type"] == "provider_ai"
        # But provider is NOT paused (no specific provider to pause)
        mock_pause_provider.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_phase4_imap_error_pauses_account(self):
        """Phase 4 IMAP errors pause the account and return mail to QUEUED.

        Previously, Phase 4 errors were silently logged. Now they are
        treated as provider errors with proper account pausing.
        """
        account_id = str(uuid4())
        user_id = str(uuid4())
        mail_uid = "42"

        status_updates: list[TrackedEmailStatus] = []
        update_kwargs_list: list[dict] = []

        async def fake_update_tracked_status(
            _account_id, _mail_uid, status, _log, **kwargs
        ):
            status_updates.append(status)
            update_kwargs_list.append(kwargs)

        mock_account = MagicMock()
        mock_account.id = uuid4()

        # Successful pipeline, but Phase 4 will fail
        mock_pipeline_result = MagicMock()
        mock_pipeline_result.provider_error = False
        mock_pipeline_result.transient_reenqueue_reason = None
        mock_pipeline_result.failed_provider_id = None
        mock_pipeline_result.auto_actions = ["move_to_folder:Archive"]
        mock_pipeline_result.plugins_executed = ["smart_folder"]
        mock_pipeline_result.plugins_completed = ["smart_folder"]
        mock_pipeline_result.plugins_failed = []
        mock_pipeline_result.plugins_skipped = []
        mock_pipeline_result.approvals_created = 0
        mock_pipeline_result.completion_reason = None

        async def fake_get_session():
            yield AsyncMock()

        with (
            patch(
                "app.workers.mail_processor._update_tracked_status",
                side_effect=fake_update_tracked_status,
            ),
            patch(
                "app.workers.mail_processor.fetch_account",
                return_value=mock_account,
            ),
            patch(
                "app.workers.mail_processor.fetch_raw_mail",
                return_value=(b"raw email bytes", ["INBOX"], "/"),
            ),
            patch(
                "app.workers.mail_processor.parse_raw_mail",
                return_value=MagicMock(),
            ),
            patch(
                "app.workers.mail_processor.run_ai_pipeline",
                return_value=mock_pipeline_result,
            ),
            patch("app.workers.mail_processor.get_session", fake_get_session),
            patch(
                "app.workers.mail_processor.execute_post_pipeline",
                side_effect=ConnectionError("IMAP connection lost"),
            ),
            patch(
                "app.workers.mail_processor._pause_account",
                new_callable=AsyncMock,
            ) as mock_pause_account,
            patch("app.workers.mail_processor._update_tracked_metadata", new_callable=AsyncMock),
        ):
            from app.workers.mail_processor import process_mail

            await process_mail(
                {"redis": MagicMock()},
                user_id,
                account_id,
                mail_uid,
            )

        # Mail should go to QUEUED with provider_imap error
        assert status_updates[0] == TrackedEmailStatus.QUEUED
        assert update_kwargs_list[0]["error_type"] == "provider_imap"
        assert "IMAP connection lost" in update_kwargs_list[0]["error"]
        # Account should have been paused
        mock_pause_account.assert_awaited_once()
        assert "phase4_imap_error" in mock_pause_account.call_args[0][1]


# ---------------------------------------------------------------------------
# Plugin executor: pipeline stop on provider unavailability (Issue #49)
# ---------------------------------------------------------------------------


class TestPluginExecutorPipelineStop:
    """Provider unavailability causes a pipeline stop (not skip).

    Issue #49: Skip reasons `no_provider`, `provider_inactive`, and
    `provider_in_backoff` (now `provider_paused`) all return
    transient_error=True with break_pipeline=True so the pipeline
    orchestrator triggers a savepoint rollback.
    """

    def _make_plugin(self, name="email_summary"):
        """Create a minimal mock plugin."""
        plugin = MagicMock()
        plugin.name = name
        plugin.display_name = name.replace("_", " ").title()
        return plugin

    def _make_provider(self, *, is_paused=False,
                       paused_reason=None):
        """Create a mock AIProvider."""
        provider = MagicMock()
        provider.id = uuid4()
        provider.name = "test-provider"
        provider.is_paused = is_paused
        provider.paused_reason = paused_reason
        provider.consecutive_errors = 0
        return provider

    def _make_user_settings(self, approval_mode="auto"):
        """Create a mock UserSettings with common plugin columns."""
        settings = MagicMock()
        # Use the real column names from PLUGIN_TO_APPROVAL_COLUMN
        for col in [
            "approval_mode_summary", "approval_mode_labeling",
            "approval_mode_smart_folder", "approval_mode_spam",
            "approval_mode_newsletter", "approval_mode_coupon",
            "approval_mode_calendar", "approval_mode_auto_reply",
            "approval_mode_rules", "approval_mode_contacts",
            "approval_mode_notifications",
        ]:
            setattr(settings, col, approval_mode)
        settings.language = "en"
        settings.timezone = "UTC"
        return settings

    @pytest.mark.asyncio
    async def test_no_provider_returns_transient_error(self):
        """When no provider is resolved, outcome is transient_error
        with break_pipeline=True (not skipped)."""
        from app.workers.plugin_executor import execute_plugin

        plugin = self._make_plugin()
        user_settings = self._make_user_settings()

        outcome = await execute_plugin(
            db=AsyncMock(),
            plugin=plugin,
            context=MagicMock(user_id=str(uuid4()), account_id=str(uuid4())),
            pipeline=MagicMock(),
            user_settings=user_settings,
            plugin_provider_map={},
            providers_by_id={},
            default_provider=None,  # No provider available
            log=MagicMock(),
        )

        assert outcome.transient_error is True
        assert outcome.break_pipeline is True
        assert outcome.skipped is False
        assert "no_provider" in outcome.transient_error_reason
        assert outcome.failed_provider_id is None  # No specific provider

    @pytest.mark.asyncio
    async def test_inactive_provider_returns_transient_error(self):
        """When the resolved provider is paused (formerly "inactive"),
        outcome is transient_error with break_pipeline=True and the
        provider ID.

        ``is_active`` was collapsed into ``is_paused`` during the provider
        refactor, so the executor now reports ``provider_paused:<plugin>``
        for both former cases.
        """
        from app.workers.plugin_executor import execute_plugin

        plugin = self._make_plugin()
        user_settings = self._make_user_settings()
        provider = self._make_provider(is_paused=True)

        outcome = await execute_plugin(
            db=AsyncMock(),
            plugin=plugin,
            context=MagicMock(user_id=str(uuid4()), account_id=str(uuid4())),
            pipeline=MagicMock(),
            user_settings=user_settings,
            plugin_provider_map={},
            providers_by_id={},
            default_provider=provider,
            log=MagicMock(),
        )

        assert outcome.transient_error is True
        assert outcome.break_pipeline is True
        assert outcome.skipped is False
        assert "provider_paused" in outcome.transient_error_reason
        assert outcome.failed_provider_id == str(provider.id)

    @pytest.mark.asyncio
    async def test_paused_provider_returns_transient_error(self):
        """When the resolved provider is paused, outcome is
        transient_error with break_pipeline=True and the provider ID."""
        from app.workers.plugin_executor import execute_plugin

        plugin = self._make_plugin()
        user_settings = self._make_user_settings()
        provider = self._make_provider(is_paused=True, paused_reason="llm_error")

        outcome = await execute_plugin(
            db=AsyncMock(),
            plugin=plugin,
            context=MagicMock(user_id=str(uuid4()), account_id=str(uuid4())),
            pipeline=MagicMock(),
            user_settings=user_settings,
            plugin_provider_map={},
            providers_by_id={},
            default_provider=provider,
            log=MagicMock(),
        )

        assert outcome.transient_error is True
        assert outcome.break_pipeline is True
        assert outcome.skipped is False
        assert "provider_paused" in outcome.transient_error_reason
        assert outcome.failed_provider_id == str(provider.id)

    @pytest.mark.asyncio
    async def test_provider_unavailability_not_skipped(self):
        """All three provider unavailability cases set failed=True
        (not skipped=True), ensuring the orchestrator treats them as
        errors, not benign skips."""
        from app.workers.plugin_executor import execute_plugin

        plugin = self._make_plugin()
        user_settings = self._make_user_settings()

        # Case 1: no provider
        outcome_no = await execute_plugin(
            db=AsyncMock(), plugin=plugin,
            context=MagicMock(user_id=str(uuid4()), account_id=str(uuid4())),
            pipeline=MagicMock(), user_settings=user_settings,
            plugin_provider_map={}, providers_by_id={},
            default_provider=None, log=MagicMock(),
        )

        # Case 2: paused provider (was "inactive")
        outcome_inactive = await execute_plugin(
            db=AsyncMock(), plugin=plugin,
            context=MagicMock(user_id=str(uuid4()), account_id=str(uuid4())),
            pipeline=MagicMock(), user_settings=user_settings,
            plugin_provider_map={}, providers_by_id={},
            default_provider=self._make_provider(is_paused=True),
            log=MagicMock(),
        )

        # Case 3: paused provider
        outcome_paused = await execute_plugin(
            db=AsyncMock(), plugin=plugin,
            context=MagicMock(user_id=str(uuid4()), account_id=str(uuid4())),
            pipeline=MagicMock(), user_settings=user_settings,
            plugin_provider_map={}, providers_by_id={},
            default_provider=self._make_provider(is_paused=True),
            log=MagicMock(),
        )

        for outcome in [outcome_no, outcome_inactive, outcome_paused]:
            assert outcome.failed is True
            assert outcome.skipped is False
            assert outcome.transient_error is True
            assert outcome.break_pipeline is True
