"""Additional coverage tests for pipeline_orchestrator.

Covers lines 353-360, 402-414, 439-725, 750-786, 813-838, 852-870, 883-923.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.mail import CompletionReason
from app.workers.pipeline_orchestrator import (
    EmailParseError,
    IMAPFolderError,
    PipelineResult,
    _apply_outcome,
    _evaluate_rules,
    _match_contact,
    execute_post_pipeline,
    fetch_raw_mail,
    parse_raw_mail,
)
from app.workers.plugin_executor import PluginOutcome

# ---------------------------------------------------------------------------
# _apply_outcome
# ---------------------------------------------------------------------------


class TestApplyOutcome:
    def test_apply_outcome_skipped_sets_status(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="spam",
            plugin_display_name="Spam",
            skipped=True,
            skip_reason="disabled_by_user",
        )
        _apply_outcome(result, outcome)
        assert result.plugins_skipped == ["spam"]
        assert result.plugin_results["spam"].status == "skipped"
        assert "disabled_by_user" in result.plugin_results["spam"].summary  # type: ignore[operator]
        # Should not be in executed/completed/failed
        assert result.plugins_executed == []
        assert result.plugins_completed == []
        assert result.plugins_failed == []

    def test_apply_outcome_skipped_default_reason(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="x",
            plugin_display_name="X",
            skipped=True,
            skip_reason=None,
        )
        _apply_outcome(result, outcome)
        assert "disabled" in result.plugin_results["x"].summary  # type: ignore[operator]

    def test_apply_outcome_executed_completed(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="labels",
            plugin_display_name="Labels",
            executed=True,
            completed=True,
            result_summary="Applied 2 labels",
            result_details={"labels": ["a", "b"]},
        )
        _apply_outcome(result, outcome)
        assert "labels" in result.plugins_executed
        assert "labels" in result.plugins_completed
        entry = result.plugin_results["labels"]
        assert entry.status == "completed"
        assert entry.summary == "Applied 2 labels"
        assert entry.details == {"labels": ["a", "b"]}

    def test_apply_outcome_completed_auto_approved(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="move",
            plugin_display_name="Move",
            executed=True,
            completed=True,
            auto_approved=True,
            result_details={"folder": "Archive"},
        )
        _apply_outcome(result, outcome)
        assert result.plugin_results["move"].details == {"folder": "Archive", "auto_approved": True}

    def test_apply_outcome_completed_auto_approved_no_details(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="p",
            plugin_display_name="P",
            executed=True,
            completed=True,
            auto_approved=True,
            result_details=None,
        )
        _apply_outcome(result, outcome)
        assert result.plugin_results["p"].details == {"auto_approved": True}

    def test_apply_outcome_failed_not_transient(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="summary",
            plugin_display_name="Summary",
            executed=True,
            failed=True,
            transient_error=False,
        )
        _apply_outcome(result, outcome)
        assert "summary" in result.plugins_failed
        assert result.plugin_results["summary"].status == "failed"
        assert result.plugin_results["summary"].summary == "Plugin failed"

    def test_apply_outcome_failed_transient(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="summary",
            plugin_display_name="Summary",
            executed=True,
            failed=True,
            transient_error=True,
            transient_error_reason="provider timeout",
        )
        _apply_outcome(result, outcome)
        assert result.plugin_results["summary"].status == "warning"
        assert result.plugin_results["summary"].summary == "provider timeout"

    def test_apply_outcome_approval_created(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="move",
            plugin_display_name="Move",
            executed=True,
            approval_created=True,
        )
        _apply_outcome(result, outcome)
        assert result.approvals_created == 1

    def test_apply_outcome_actions_taken(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="labels",
            plugin_display_name="Labels",
            executed=True,
            completed=True,
            actions_taken=["label:Important", "label:Work"],
        )
        _apply_outcome(result, outcome)
        assert result.auto_actions == ["label:Important", "label:Work"]

    def test_apply_outcome_break_pipeline_completed(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="spam",
            plugin_display_name="Spam",
            executed=True,
            completed=True,
            break_pipeline=True,
        )
        _apply_outcome(result, outcome)
        assert result.completion_reason == CompletionReason.SPAM_SHORT_CIRCUIT

    def test_apply_outcome_break_pipeline_not_completed(self) -> None:
        result = PipelineResult()
        outcome = PluginOutcome(
            plugin_name="spam",
            plugin_display_name="Spam",
            executed=True,
            completed=False,
            break_pipeline=True,
        )
        _apply_outcome(result, outcome)
        assert result.completion_reason is None


# ---------------------------------------------------------------------------
# _match_contact
# ---------------------------------------------------------------------------


class TestMatchContact:
    @pytest.mark.asyncio
    async def test_match_contact_success(self) -> None:
        contact = MagicMock()
        contact.id = uuid4()
        contact.display_name = "Alice"
        contact.first_name = "Alice"
        contact.last_name = "Smith"
        contact.organization = "Acme"
        contact.title = "CTO"
        contact.emails = ["alice@example.com"]
        contact.phones = ["+1234"]

        db = AsyncMock()
        db.begin_nested = MagicMock(return_value=AsyncMock())
        event_bus = AsyncMock()
        parsed = MagicMock()
        parsed.sender = "alice@example.com"
        log = MagicMock()

        with patch(
            "app.workers.pipeline_orchestrator.match_sender_to_contact",
            new_callable=AsyncMock,
            return_value=contact,
        ):
            result = await _match_contact(db, str(uuid4()), str(uuid4()), "uid1", parsed, event_bus, log)

        assert result is not None
        assert result["display_name"] == "Alice"
        assert result["id"] == str(contact.id)
        event_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_match_contact_no_match(self) -> None:
        db = AsyncMock()
        db.begin_nested = MagicMock(return_value=AsyncMock())
        event_bus = AsyncMock()
        parsed = MagicMock()
        parsed.sender = "unknown@example.com"
        log = MagicMock()

        with patch(
            "app.workers.pipeline_orchestrator.match_sender_to_contact",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await _match_contact(db, str(uuid4()), str(uuid4()), "uid1", parsed, event_bus, log)

        assert result is None
        event_bus.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_match_contact_exception(self) -> None:
        db = AsyncMock()
        db.begin_nested = MagicMock(return_value=AsyncMock())
        event_bus = AsyncMock()
        parsed = MagicMock()
        parsed.sender = "bad@example.com"
        log = MagicMock()

        with patch(
            "app.workers.pipeline_orchestrator.match_sender_to_contact",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db error"),
        ):
            result = await _match_contact(db, str(uuid4()), str(uuid4()), "uid1", parsed, event_bus, log)

        assert result is None
        log.warning.assert_called_once_with("contact_match_failed", sender="bad@example.com")


# ---------------------------------------------------------------------------
# _evaluate_rules
# ---------------------------------------------------------------------------


class TestEvaluateRules:
    @pytest.mark.asyncio
    async def test_evaluate_rules_with_actions(self) -> None:
        rule_result_mock = MagicMock()
        rule_result_mock.matched_rule_ids = ["r1"]
        rule_result_mock.actions_taken = ["move:Archive"]
        rule_result_mock.imap_actions = ["move:Archive"]

        db = AsyncMock()
        db.begin_nested = MagicMock(return_value=AsyncMock())
        event_bus = AsyncMock()
        context = MagicMock()
        context.mail_id = str(uuid4())
        log = MagicMock()
        result = PipelineResult()

        with patch(
            "app.services.rules.evaluate_rules",
            new_callable=AsyncMock,
            return_value=rule_result_mock,
        ):
            await _evaluate_rules(db, str(uuid4()), str(uuid4()), "uid1", context, event_bus, log, result)

        assert result.auto_actions == ["move:Archive"]
        event_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_evaluate_rules_no_imap_actions(self) -> None:
        rule_result_mock = MagicMock()
        rule_result_mock.matched_rule_ids = []
        rule_result_mock.actions_taken = []
        rule_result_mock.imap_actions = []

        db = AsyncMock()
        db.begin_nested = MagicMock(return_value=AsyncMock())
        event_bus = AsyncMock()
        context = MagicMock()
        context.mail_id = None
        log = MagicMock()
        result = PipelineResult()

        with patch(
            "app.services.rules.evaluate_rules",
            new_callable=AsyncMock,
            return_value=rule_result_mock,
        ):
            await _evaluate_rules(db, str(uuid4()), str(uuid4()), "uid1", context, event_bus, log, result)

        assert result.auto_actions == []
        event_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_evaluate_rules_exception(self) -> None:
        db = AsyncMock()
        db.begin_nested = MagicMock(return_value=AsyncMock())
        event_bus = AsyncMock()
        context = MagicMock()
        context.mail_id = None
        log = MagicMock()
        result = PipelineResult()

        with patch(
            "app.services.rules.evaluate_rules",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            await _evaluate_rules(db, str(uuid4()), str(uuid4()), "uid1", context, event_bus, log, result)

        assert result.auto_actions == []
        log.exception.assert_called_once_with("rule_evaluation_failed")
        # Event still emitted with empty actions
        event_bus.emit.assert_awaited_once()


# ---------------------------------------------------------------------------
# parse_raw_mail (lines 402-414)
# ---------------------------------------------------------------------------


class TestParseRawMail:
    def test_parse_raw_mail_success(self) -> None:
        parsed = MagicMock()
        parsed.subject = "Hello"
        parsed.sender = "a@b.com"
        parsed.body_plain = "text"
        parsed.body_html = None
        log = MagicMock()

        with patch("app.workers.pipeline_orchestrator.parse_email", return_value=parsed):
            result = parse_raw_mail(b"raw", "uid1", log)

        assert result is parsed
        log.info.assert_called_once()

    def test_parse_raw_mail_exception_wraps(self) -> None:
        log = MagicMock()
        with (
            patch(
                "app.workers.pipeline_orchestrator.parse_email",
                side_effect=ValueError("bad"),
            ),
            pytest.raises(EmailParseError, match="email_parse_failed"),
        ):
            parse_raw_mail(b"raw", "uid1", log)

    def test_parse_raw_mail_empty_body_logs(self) -> None:
        parsed = MagicMock()
        parsed.subject = "Empty"
        parsed.sender = "a@b.com"
        parsed.body_plain = ""
        parsed.body_html = ""
        parsed.size = 100
        log = MagicMock()

        with patch("app.workers.pipeline_orchestrator.parse_email", return_value=parsed):
            parse_raw_mail(b"raw", "uid1", log)

        # Should have two log.info calls: mail_parsed + mail_body_empty
        assert log.info.call_count == 2


# ---------------------------------------------------------------------------
# fetch_raw_mail — IMAP folder select error wrapping (lines 353-360)
# ---------------------------------------------------------------------------


class TestFetchRawMailFolderError:
    @pytest.mark.asyncio
    async def test_select_error_wrapped_as_imap_folder_error(self) -> None:
        account = MagicMock()
        account.id = uuid4()
        log = MagicMock()

        conn = AsyncMock()
        conn.separator = "/"

        async def _raise_select(*args, **kwargs):
            raise Exception("select failed for folder")

        with (
            patch(
                "app.workers.pipeline_orchestrator.imap_connection",
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=False)
                ),
            ),
            patch(
                "app.workers.pipeline_orchestrator.fetch_raw_message",
                side_effect=Exception("select failed for folder"),
            ),
            pytest.raises(IMAPFolderError, match="imap_select_failed"),
        ):
            await fetch_raw_mail(account, "uid1", "INBOX", log)

    @pytest.mark.asyncio
    async def test_mailbox_error_wrapped(self) -> None:
        account = MagicMock()
        account.id = uuid4()
        log = MagicMock()

        conn = AsyncMock()
        conn.separator = "/"

        with (
            patch(
                "app.workers.pipeline_orchestrator.imap_connection",
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=False)
                ),
            ),
            patch(
                "app.workers.pipeline_orchestrator.fetch_raw_message",
                side_effect=Exception("Mailbox does not exist"),
            ),
            pytest.raises(IMAPFolderError),
        ):
            await fetch_raw_mail(account, "uid1", "INBOX", log)

    @pytest.mark.asyncio
    async def test_non_folder_exception_reraises(self) -> None:
        account = MagicMock()
        account.id = uuid4()
        log = MagicMock()

        conn = AsyncMock()
        conn.separator = "/"

        with (
            patch(
                "app.workers.pipeline_orchestrator.imap_connection",
                return_value=AsyncMock(
                    __aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=False)
                ),
            ),
            patch(
                "app.workers.pipeline_orchestrator.fetch_raw_message",
                side_effect=Exception("network timeout"),
            ),
            pytest.raises(Exception, match="network timeout"),
        ):
            await fetch_raw_mail(account, "uid1", "INBOX", log)


# ---------------------------------------------------------------------------
# execute_post_pipeline (lines 750-786)
# ---------------------------------------------------------------------------


class TestExecutePostPipeline:
    @pytest.mark.asyncio
    async def test_account_deactivated_skips_imap(self) -> None:
        account = MagicMock()
        log = MagicMock()
        account_id = str(uuid4())
        user_id = str(uuid4())

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.workers.pipeline_orchestrator.save_new_labels", new_callable=AsyncMock),
            patch("app.workers.pipeline_orchestrator.save_new_folders", new_callable=AsyncMock),
            patch("app.workers.pipeline_orchestrator.get_session_ctx", return_value=mock_ctx),
            patch("app.workers.pipeline_orchestrator.execute_imap_actions", new_callable=AsyncMock) as mock_imap,
        ):
            folder, uid = await execute_post_pipeline(
                account=account,
                account_id=account_id,
                mail_uid="uid1",
                current_folder="INBOX",
                auto_actions=["label:Test"],
                user_id=user_id,
                log=log,
            )

        assert folder == "INBOX"
        assert uid is None
        mock_imap.assert_not_awaited()
        log.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_move_outcome_returns_new_folder(self) -> None:
        account = MagicMock()
        log = MagicMock()
        account_id = str(uuid4())
        user_id = str(uuid4())

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()  # account active
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        move_outcome = MagicMock()
        move_outcome.folder = "Archive"
        move_outcome.new_uid = "999"

        with (
            patch("app.workers.pipeline_orchestrator.save_new_labels", new_callable=AsyncMock),
            patch("app.workers.pipeline_orchestrator.save_new_folders", new_callable=AsyncMock),
            patch("app.workers.pipeline_orchestrator.get_session_ctx", return_value=mock_ctx),
            patch(
                "app.workers.pipeline_orchestrator.execute_imap_actions",
                new_callable=AsyncMock,
                return_value=move_outcome,
            ),
        ):
            folder, uid = await execute_post_pipeline(
                account=account,
                account_id=account_id,
                mail_uid="uid1",
                current_folder="INBOX",
                auto_actions=["move:Archive"],
                user_id=user_id,
                log=log,
            )

        assert folder == "Archive"
        assert uid == "999"

    @pytest.mark.asyncio
    async def test_no_move_returns_current_folder(self) -> None:
        account = MagicMock()
        log = MagicMock()
        account_id = str(uuid4())
        user_id = str(uuid4())

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        move_outcome = MagicMock()
        move_outcome.folder = None
        move_outcome.new_uid = None

        with (
            patch("app.workers.pipeline_orchestrator.save_new_labels", new_callable=AsyncMock),
            patch("app.workers.pipeline_orchestrator.save_new_folders", new_callable=AsyncMock),
            patch("app.workers.pipeline_orchestrator.get_session_ctx", return_value=mock_ctx),
            patch(
                "app.workers.pipeline_orchestrator.execute_imap_actions",
                new_callable=AsyncMock,
                return_value=move_outcome,
            ),
        ):
            folder, uid = await execute_post_pipeline(
                account=account,
                account_id=account_id,
                mail_uid="uid1",
                current_folder="Sent",
                auto_actions=[],
                user_id=user_id,
                log=log,
            )

        assert folder == "Sent"
        assert uid is None
