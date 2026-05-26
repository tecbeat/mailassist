"""Coverage tests for app.workers.plugin_executor.

Covers: execute_plugin (main flow, disabled, no settings, paused provider,
transient/permanent/value errors, reprompt, approval modes, auto-approve,
spam short-circuit), _handle_transient_error, _persist_plugin_result,
_create_approval, _create_manual_input_approval, _load_mail_account.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import structlog

from app.models.user import ApprovalMode
from app.plugins.base import ActionResult, MailContext
from app.workers.plugin_executor import (
    PluginOutcome,
    _handle_transient_error,
    _load_mail_account,
    _persist_plugin_result,
    execute_plugin,
)


def _make_context(**kw):
    defaults = {
        "user_id": str(uuid4()),
        "account_id": str(uuid4()),
        "mail_uid": "100",
        "mail_id": str(uuid4()),
        "sender": "sender@example.com",
        "sender_name": "Sender",
        "recipient": "me@example.com",
        "subject": "Test",
        "body": "body",
        "body_plain": "body",
        "body_html": "<p>body</p>",
        "headers": {"message-id": "<abc@example.com>"},
        "date": "2026-01-01T00:00:00Z",
        "has_attachments": False,
        "attachment_names": [],
        "account_name": "Acct",
        "account_email": "me@example.com",
        "existing_labels": [],
        "existing_folders": [],
        "excluded_folders": [],
        "folder_separator": "/",
        "mail_size": 1024,
        "thread_length": 1,
        "is_reply": False,
        "is_forwarded": False,
        "contact": None,
    }
    defaults.update(kw)
    return MailContext(**defaults)


def _make_provider(*, is_paused=False):
    p = MagicMock()
    p.id = uuid4()
    p.name = "test-prov"
    p.provider_type = MagicMock(value="openai")
    p.base_url = "https://api.openai.com"
    p.api_key = b"key"
    p.model_name = "gpt-4"
    p.max_tokens = 1000
    p.temperature = 0.0
    p.timeout_seconds = 30
    p.is_paused = is_paused
    p.paused_reason = "llm_error" if is_paused else None
    p.consecutive_errors = 0
    return p


def _make_plugin(name="email_summary"):
    plugin = MagicMock()
    plugin.name = name
    plugin.display_name = name.replace("_", " ").title()
    plugin.get_response_schema.return_value = MagicMock()
    plugin.get_approval_summary.return_value = "summary"
    return plugin


def _make_user_settings(*, mode=ApprovalMode.AUTO, language="en", timezone="UTC", threshold=None):
    s = MagicMock()
    s.language = language
    s.timezone = timezone
    s.ai_timeout_seconds = 30
    s.auto_approve_threshold = threshold
    # Dynamic attribute for approval column
    s.email_summary_mode = mode
    s.spam_detection_mode = mode
    s.newsletter_detection_mode = mode
    s.labeling_mode = mode
    s.smart_folder_mode = mode
    s.calendar_extraction_mode = mode
    s.auto_reply_mode = mode
    s.contacts_mode = mode
    s.coupon_extraction_mode = mode
    s.otp_extraction_mode = mode
    return s


def _base_patches():
    """Return common patches for execute_plugin."""
    return {
        "resolve_prompts": patch(
            "app.workers.plugin_executor.resolve_prompts", new_callable=AsyncMock, return_value=("sys", "usr")
        ),
        "get_encryption": patch("app.workers.plugin_executor.get_encryption"),
        "get_template_engine": patch("app.core.templating.get_template_engine"),
        "call_llm_with_tools": patch("app.workers.plugin_executor.call_llm_with_tools", new_callable=AsyncMock),
        "update_provider_health": patch("app.workers.plugin_executor.update_provider_health", new_callable=AsyncMock),
        "has_actionable": patch("app.workers.plugin_executor.has_actionable_results", return_value=True),
        "persist": patch("app.workers.plugin_executor._persist_plugin_result", new_callable=AsyncMock),
        "extract_summary": patch("app.workers.plugin_executor._extract_result_summary", return_value="sum"),
        "extract_details": patch("app.workers.plugin_executor._extract_result_details", return_value={}),
    }


# ---------------------------------------------------------------------------
# execute_plugin — disabled / no settings
# ---------------------------------------------------------------------------


class TestExecutePluginSkips:
    @pytest.mark.asyncio
    async def test_plugin_disabled_by_user_skipped(self):
        plugin = _make_plugin()
        settings = _make_user_settings(mode=ApprovalMode.DISABLED)
        ctx = _make_context()
        provider = _make_provider()

        with patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}):
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.skipped is True
        assert result.skip_reason == "disabled_by_user"

    @pytest.mark.asyncio
    async def test_no_user_settings_skipped(self):
        plugin = _make_plugin()
        ctx = _make_context()

        with patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}):
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=None,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=None,
                log=structlog.get_logger(),
            )

        assert result.skipped is True
        assert result.skip_reason == "no_user_settings"


# ---------------------------------------------------------------------------
# execute_plugin — no provider / paused provider
# ---------------------------------------------------------------------------


class TestExecutePluginProviderIssues:
    @pytest.mark.asyncio
    async def test_no_provider_breaks_pipeline(self):
        plugin = _make_plugin()
        settings = _make_user_settings()
        ctx = _make_context()

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=None),
        ):
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=None,
                log=structlog.get_logger(),
            )

        assert result.failed is True
        assert result.break_pipeline is True
        assert result.transient_error is True

    @pytest.mark.asyncio
    async def test_paused_provider_breaks_pipeline(self):
        plugin = _make_plugin()
        settings = _make_user_settings()
        ctx = _make_context()
        provider = _make_provider(is_paused=True)

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=provider),
        ):
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.failed is True
        assert result.break_pipeline is True
        assert "provider_paused" in result.transient_error_reason


# ---------------------------------------------------------------------------
# execute_plugin — LLM errors
# ---------------------------------------------------------------------------


class TestExecutePluginLLMErrors:
    @pytest.mark.asyncio
    async def test_permanent_llm_error_fails(self):
        from app.services.ai import PermanentLLMError

        plugin = _make_plugin()
        settings = _make_user_settings()
        ctx = _make_context()
        provider = _make_provider()

        patches = _base_patches()
        patches["call_llm_with_tools"] = patch(
            "app.workers.plugin_executor.call_llm_with_tools",
            new_callable=AsyncMock,
            side_effect=PermanentLLMError("bad model"),
        )

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=provider),
            patches["resolve_prompts"],
            patches["get_encryption"],
            patches["get_template_engine"],
            patches["call_llm_with_tools"],
        ):
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.failed is True

    @pytest.mark.asyncio
    async def test_value_error_fails(self):
        plugin = _make_plugin()
        settings = _make_user_settings()
        ctx = _make_context()
        provider = _make_provider()

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=provider),
            patch("app.workers.plugin_executor.resolve_prompts", new_callable=AsyncMock, return_value=("s", "u")),
            patch("app.workers.plugin_executor.get_encryption"),
            patch("app.core.templating.get_template_engine"),
            patch(
                "app.workers.plugin_executor.call_llm_with_tools",
                new_callable=AsyncMock,
                side_effect=ValueError("bad json"),
            ),
        ):
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.failed is True


# ---------------------------------------------------------------------------
# execute_plugin — full success path + approval modes
# ---------------------------------------------------------------------------


class TestExecutePluginSuccess:
    @pytest.mark.asyncio
    async def test_auto_mode_persists_results(self):
        plugin = _make_plugin()
        settings = _make_user_settings(mode=ApprovalMode.AUTO)
        ctx = _make_context()
        provider = _make_provider()
        ai_resp = MagicMock()

        action_result = ActionResult(success=True, actions_taken=["summarized"], requires_approval=False)
        plugin.safe_execute = AsyncMock(return_value=action_result)

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=provider),
            patch("app.workers.plugin_executor.resolve_prompts", new_callable=AsyncMock, return_value=("s", "u")),
            patch("app.workers.plugin_executor.get_encryption") as enc,
            patch("app.core.templating.get_template_engine"),
            patch(
                "app.workers.plugin_executor.call_llm_with_tools", new_callable=AsyncMock, return_value=(ai_resp, 100)
            ),
            patch("app.workers.plugin_executor.update_provider_health", new_callable=AsyncMock),
            patch("app.workers.plugin_executor.has_actionable_results", return_value=True),
            patch("app.workers.plugin_executor._persist_plugin_result", new_callable=AsyncMock) as mock_persist,
            patch("app.workers.plugin_executor._extract_result_summary", return_value="sum"),
            patch("app.workers.plugin_executor._extract_result_details", return_value={}),
        ):
            enc.return_value.decrypt.return_value = "key"
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.completed is True
        assert result.executed is True
        mock_persist.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_approval_mode_creates_approval(self):
        plugin = _make_plugin()
        settings = _make_user_settings(mode=ApprovalMode.APPROVAL)
        ctx = _make_context()
        provider = _make_provider()
        ai_resp = MagicMock()

        action_result = ActionResult(success=True, actions_taken=["summarized"], requires_approval=False)
        plugin.safe_execute = AsyncMock(return_value=action_result)

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=provider),
            patch("app.workers.plugin_executor.resolve_prompts", new_callable=AsyncMock, return_value=("s", "u")),
            patch("app.workers.plugin_executor.get_encryption") as enc,
            patch("app.core.templating.get_template_engine"),
            patch(
                "app.workers.plugin_executor.call_llm_with_tools", new_callable=AsyncMock, return_value=(ai_resp, 100)
            ),
            patch("app.workers.plugin_executor.update_provider_health", new_callable=AsyncMock),
            patch("app.workers.plugin_executor.has_actionable_results", return_value=True),
            patch("app.workers.plugin_executor._create_approval", new_callable=AsyncMock) as mock_approval,
            patch("app.workers.plugin_executor._extract_result_summary", return_value="sum"),
            patch("app.workers.plugin_executor._extract_result_details", return_value={}),
        ):
            enc.return_value.decrypt.return_value = "key"
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.approval_created is True
        assert result.needs_approval is True
        mock_approval.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_approve_threshold_met(self):
        plugin = _make_plugin()
        settings = _make_user_settings(mode=ApprovalMode.APPROVAL, threshold=0.8)
        ctx = _make_context()
        provider = _make_provider()
        ai_resp = MagicMock()
        ai_resp.confidence = 0.95

        action_result = ActionResult(success=True, actions_taken=["act"], requires_approval=False)
        plugin.safe_execute = AsyncMock(return_value=action_result)

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=provider),
            patch("app.workers.plugin_executor.resolve_prompts", new_callable=AsyncMock, return_value=("s", "u")),
            patch("app.workers.plugin_executor.get_encryption") as enc,
            patch("app.core.templating.get_template_engine"),
            patch(
                "app.workers.plugin_executor.call_llm_with_tools", new_callable=AsyncMock, return_value=(ai_resp, 50)
            ),
            patch("app.workers.plugin_executor.update_provider_health", new_callable=AsyncMock),
            patch("app.workers.plugin_executor.has_actionable_results", return_value=True),
            patch("app.workers.plugin_executor._persist_plugin_result", new_callable=AsyncMock),
            patch("app.workers.plugin_executor._extract_result_summary", return_value="s"),
            patch("app.workers.plugin_executor._extract_result_details", return_value={}),
        ):
            enc.return_value.decrypt.return_value = "key"
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.auto_approved is True
        assert result.needs_approval is False


# ---------------------------------------------------------------------------
# execute_plugin — action failure creates manual_input approval
# ---------------------------------------------------------------------------


class TestExecutePluginActionFailure:
    @pytest.mark.asyncio
    async def test_action_error_creates_manual_input_approval(self):
        plugin = _make_plugin()
        settings = _make_user_settings()
        ctx = _make_context()
        provider = _make_provider()
        ai_resp = MagicMock()

        action_result = ActionResult(success=False, error="plugin crashed", actions_taken=[])
        plugin.safe_execute = AsyncMock(return_value=action_result)

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=provider),
            patch("app.workers.plugin_executor.resolve_prompts", new_callable=AsyncMock, return_value=("s", "u")),
            patch("app.workers.plugin_executor.get_encryption") as enc,
            patch("app.core.templating.get_template_engine"),
            patch(
                "app.workers.plugin_executor.call_llm_with_tools", new_callable=AsyncMock, return_value=(ai_resp, 50)
            ),
            patch("app.workers.plugin_executor.update_provider_health", new_callable=AsyncMock),
            patch("app.workers.plugin_executor.has_actionable_results", return_value=False),
            patch("app.workers.plugin_executor._create_manual_input_approval", new_callable=AsyncMock) as mock_mi,
        ):
            enc.return_value.decrypt.return_value = "key"
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.failed is True
        assert result.approval_created is True
        mock_mi.assert_awaited_once()


# ---------------------------------------------------------------------------
# execute_plugin — reprompt
# ---------------------------------------------------------------------------


class TestExecutePluginReprompt:
    @pytest.mark.asyncio
    async def test_reprompt_success(self):
        plugin = _make_plugin()
        settings = _make_user_settings()
        ctx = _make_context()
        provider = _make_provider()
        ai_resp1 = MagicMock()
        ai_resp2 = MagicMock()

        first_result = ActionResult(success=True, actions_taken=[], retry_prompt="try again")
        second_result = ActionResult(success=True, actions_taken=["done"], requires_approval=False)
        plugin.safe_execute = AsyncMock(side_effect=[first_result, second_result])

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=provider),
            patch("app.workers.plugin_executor.resolve_prompts", new_callable=AsyncMock, return_value=("s", "u")),
            patch("app.workers.plugin_executor.get_encryption") as enc,
            patch("app.core.templating.get_template_engine"),
            patch(
                "app.workers.plugin_executor.call_llm_with_tools",
                new_callable=AsyncMock,
                side_effect=[(ai_resp1, 50), (ai_resp2, 30)],
            ),
            patch("app.workers.plugin_executor.update_provider_health", new_callable=AsyncMock),
            patch("app.workers.plugin_executor.has_actionable_results", return_value=True),
            patch("app.workers.plugin_executor._persist_plugin_result", new_callable=AsyncMock),
            patch("app.workers.plugin_executor._extract_result_summary", return_value="s"),
            patch("app.workers.plugin_executor._extract_result_details", return_value={}),
        ):
            enc.return_value.decrypt.return_value = "key"
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.completed is True

    @pytest.mark.asyncio
    async def test_reprompt_llm_failure(self):
        from app.services.ai import TransientLLMError

        plugin = _make_plugin()
        settings = _make_user_settings()
        ctx = _make_context()
        provider = _make_provider()
        ai_resp = MagicMock()

        first_result = ActionResult(success=True, actions_taken=[], retry_prompt="retry")
        plugin.safe_execute = AsyncMock(return_value=first_result)

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"email_summary": "email_summary_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=provider),
            patch("app.workers.plugin_executor.resolve_prompts", new_callable=AsyncMock, return_value=("s", "u")),
            patch("app.workers.plugin_executor.get_encryption") as enc,
            patch("app.core.templating.get_template_engine"),
            patch(
                "app.workers.plugin_executor.call_llm_with_tools",
                new_callable=AsyncMock,
                side_effect=[(ai_resp, 50), TransientLLMError("retry fail")],
            ),
            patch("app.workers.plugin_executor.update_provider_health", new_callable=AsyncMock),
            patch("app.workers.plugin_executor.has_actionable_results", return_value=False),
        ):
            enc.return_value.decrypt.return_value = "key"
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.failed is True


# ---------------------------------------------------------------------------
# execute_plugin — spam short-circuit
# ---------------------------------------------------------------------------


class TestExecutePluginSpamShortCircuit:
    @pytest.mark.asyncio
    async def test_spam_skip_remaining_breaks_pipeline(self):
        plugin = _make_plugin("spam_detection")
        settings = _make_user_settings()
        ctx = _make_context()
        provider = _make_provider()
        ai_resp = MagicMock()
        ai_resp.is_spam = True
        ai_resp.confidence = 0.99
        ai_resp.reason = "phishing"

        action_result = ActionResult(success=True, actions_taken=["move_to_spam"], skip_remaining_plugins=True)
        plugin.safe_execute = AsyncMock(return_value=action_result)

        with (
            patch("app.workers.plugin_executor.PLUGIN_TO_APPROVAL_COLUMN", {"spam_detection": "spam_detection_mode"}),
            patch("app.workers.plugin_executor.resolve_plugin_provider", return_value=provider),
            patch("app.workers.plugin_executor.resolve_prompts", new_callable=AsyncMock, return_value=("s", "u")),
            patch("app.workers.plugin_executor.get_encryption") as enc,
            patch("app.core.templating.get_template_engine"),
            patch(
                "app.workers.plugin_executor.call_llm_with_tools", new_callable=AsyncMock, return_value=(ai_resp, 50)
            ),
            patch("app.workers.plugin_executor.update_provider_health", new_callable=AsyncMock),
            patch("app.workers.plugin_executor.has_actionable_results", return_value=True),
            patch("app.workers.plugin_executor._persist_plugin_result", new_callable=AsyncMock),
            patch("app.workers.plugin_executor._extract_result_summary", return_value="s"),
            patch("app.workers.plugin_executor._extract_result_details", return_value={}),
            patch("app.workers.plugin_executor.check_blocklist", new_callable=AsyncMock, return_value=False),
        ):
            enc.return_value.decrypt.return_value = "key"
            result = await execute_plugin(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                pipeline=MagicMock(),
                user_settings=settings,
                plugin_provider_map={},
                providers_by_id={},
                default_provider=provider,
                log=structlog.get_logger(),
            )

        assert result.break_pipeline is True


# ---------------------------------------------------------------------------
# _handle_transient_error
# ---------------------------------------------------------------------------


class TestHandleTransientError:
    @pytest.mark.asyncio
    async def test_transient_error_records_health(self):
        from app.services.ai import TransientLLMError

        provider = _make_provider()
        plugin = _make_plugin()
        outcome = PluginOutcome(plugin_name=plugin.name)
        error = TransientLLMError("timeout")

        mock_health_db = AsyncMock()

        async def fake_get_session():
            yield mock_health_db

        with (
            patch("app.core.database.get_session", return_value=fake_get_session()),
            patch("app.workers.plugin_executor.update_provider_health", new_callable=AsyncMock),
            patch("app.workers.plugin_executor.check_ai_circuit_breaker", new_callable=AsyncMock, return_value=False),
        ):
            result = await _handle_transient_error(
                db=AsyncMock(),
                provider=provider,
                plugin=plugin,
                error=error,
                outcome=outcome,
                log=structlog.get_logger(),
            )

        assert result.failed is True
        assert result.transient_error is True
        assert result.break_pipeline is True

    @pytest.mark.asyncio
    async def test_transient_error_circuit_breaker_trips(self):
        from app.services.ai import TransientLLMError

        provider = _make_provider()
        plugin = _make_plugin()
        outcome = PluginOutcome(plugin_name=plugin.name)
        error = TransientLLMError("timeout")

        mock_health_db = AsyncMock()

        async def fake_get_session():
            yield mock_health_db

        with (
            patch("app.core.database.get_session", return_value=fake_get_session()),
            patch("app.workers.plugin_executor.update_provider_health", new_callable=AsyncMock),
            patch("app.workers.plugin_executor.check_ai_circuit_breaker", new_callable=AsyncMock, return_value=True),
        ):
            result = await _handle_transient_error(
                db=AsyncMock(),
                provider=provider,
                plugin=plugin,
                error=error,
                outcome=outcome,
                log=structlog.get_logger(),
            )

        assert result.break_pipeline is True

    @pytest.mark.asyncio
    async def test_transient_error_health_tracking_fails(self):
        from app.services.ai import TransientLLMError

        provider = _make_provider()
        plugin = _make_plugin()
        outcome = PluginOutcome(plugin_name=plugin.name)
        error = TransientLLMError("timeout")

        with patch("app.core.database.get_session", side_effect=RuntimeError("db down")):
            result = await _handle_transient_error(
                db=AsyncMock(),
                provider=provider,
                plugin=plugin,
                error=error,
                outcome=outcome,
                log=structlog.get_logger(),
            )

        assert result.failed is True


# ---------------------------------------------------------------------------
# _persist_plugin_result — various plugin types
# ---------------------------------------------------------------------------


class TestPersistPluginResult:
    @pytest.mark.asyncio
    async def test_persist_no_mail_id_returns(self):
        ctx = _make_context(mail_id="")
        plugin = _make_plugin()

        await _persist_plugin_result(
            db=AsyncMock(),
            plugin=plugin,
            context=ctx,
            ai_response=MagicMock(),
            log=structlog.get_logger(),
        )
        # Should return early without error

    @pytest.mark.asyncio
    async def test_persist_newsletter_detection(self):
        ctx = _make_context()
        plugin = _make_plugin("newsletter_detection")
        ai_resp = MagicMock()
        ai_resp.is_newsletter = True
        ai_resp.newsletter_name = "TechNews"
        ai_resp.unsubscribe_url = "https://unsub.example.com"
        ai_resp.has_unsubscribe = True

        with patch("app.workers.plugin_executor.save_newsletter", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_result(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                ai_response=ai_resp,
                log=structlog.get_logger(),
            )
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_auto_reply_with_draft(self):
        ctx = _make_context()
        plugin = _make_plugin("auto_reply")
        ai_resp = MagicMock()
        ai_resp.should_reply = True
        ai_resp.draft_body = "Thanks for your email."
        ai_resp.tone = "formal"
        ai_resp.reasoning = "polite response needed"

        mock_account = MagicMock()

        with (
            patch("app.workers.plugin_executor.save_auto_reply", new_callable=AsyncMock),
            patch("app.workers.plugin_executor._load_mail_account", new_callable=AsyncMock, return_value=mock_account),
            patch("app.services.draft_upload.upload_draft_to_imap", new_callable=AsyncMock) as mock_upload,
        ):
            await _persist_plugin_result(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                ai_response=ai_resp,
                log=structlog.get_logger(),
            )
        mock_upload.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_auto_reply_no_draft(self):
        ctx = _make_context()
        plugin = _make_plugin("auto_reply")
        ai_resp = MagicMock()
        ai_resp.should_reply = False
        ai_resp.draft_body = ""
        ai_resp.tone = ""
        ai_resp.reasoning = ""

        with patch("app.workers.plugin_executor.save_auto_reply", new_callable=AsyncMock):
            await _persist_plugin_result(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                ai_response=ai_resp,
                log=structlog.get_logger(),
            )
        # No draft upload attempted

    @pytest.mark.asyncio
    async def test_persist_contacts(self):
        ctx = _make_context()
        plugin = _make_plugin("contacts")
        ai_resp = MagicMock()
        ai_resp.contact_id = str(uuid4())
        ai_resp.contact_name = "Jane"
        ai_resp.confidence = 0.9
        ai_resp.reasoning = "matched"
        ai_resp.is_new_contact_suggestion = False

        with patch("app.workers.plugin_executor.save_contact_assignment", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_result(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                ai_response=ai_resp,
                log=structlog.get_logger(),
            )
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_spam_detection(self):
        ctx = _make_context()
        plugin = _make_plugin("spam_detection")
        ai_resp = MagicMock()
        ai_resp.is_spam = True
        ai_resp.confidence = 0.95
        ai_resp.reason = "phishing"

        with patch("app.workers.plugin_executor.save_spam_detection", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_result(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                ai_response=ai_resp,
                log=structlog.get_logger(),
            )
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_coupon_extraction(self):
        ctx = _make_context()
        plugin = _make_plugin("coupon_extraction")
        ai_resp = MagicMock()
        ai_resp.has_coupons = True
        coupon = MagicMock()
        coupon.model_dump.return_value = {"code": "SAVE10"}
        ai_resp.coupons = [coupon]

        with patch("app.workers.plugin_executor.save_coupons", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_result(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                ai_response=ai_resp,
                log=structlog.get_logger(),
            )
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_otp_extraction(self):
        ctx = _make_context()
        plugin = _make_plugin("otp_extraction")
        ai_resp = MagicMock()
        ai_resp.has_codes = True
        code = MagicMock()
        code.model_dump.return_value = {"code": "123456"}
        ai_resp.codes = [code]

        with patch("app.workers.plugin_executor.save_otp", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_result(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                ai_response=ai_resp,
                log=structlog.get_logger(),
            )
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_labeling(self):
        ctx = _make_context()
        plugin = _make_plugin("labeling")
        ai_resp = MagicMock()
        ai_resp.labels = ["urgent", "work"]

        with patch("app.workers.plugin_executor.save_applied_labels", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_result(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                ai_response=ai_resp,
                log=structlog.get_logger(),
            )
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_smart_folder(self):
        ctx = _make_context()
        plugin = _make_plugin("smart_folder")
        ai_resp = MagicMock()
        ai_resp.folder = "Archive"
        ai_resp.confidence = 0.9
        ai_resp.reason = "old"

        with patch("app.workers.plugin_executor.save_assigned_folder", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_result(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                ai_response=ai_resp,
                log=structlog.get_logger(),
            )
        mock_save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_persist_calendar_extraction(self):
        ctx = _make_context()
        plugin = _make_plugin("calendar_extraction")
        ai_resp = MagicMock()
        ai_resp.has_event = True
        ai_resp.title = "Meeting"
        ai_resp.start = "2026-01-01T10:00:00"
        ai_resp.end = "2026-01-01T11:00:00"
        ai_resp.location = "Room A"
        ai_resp.description = "desc"
        ai_resp.is_all_day = False

        with patch("app.workers.plugin_executor.save_calendar_event", new_callable=AsyncMock) as mock_save:
            await _persist_plugin_result(
                db=AsyncMock(),
                plugin=plugin,
                context=ctx,
                ai_response=ai_resp,
                log=structlog.get_logger(),
            )
        mock_save.assert_awaited_once()


# ---------------------------------------------------------------------------
# _load_mail_account
# ---------------------------------------------------------------------------


class TestLoadMailAccount:
    @pytest.mark.asyncio
    async def test_load_account_found(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _load_mail_account(mock_db, uuid4())
        assert result is not None

    @pytest.mark.asyncio
    async def test_load_account_not_found(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await _load_mail_account(mock_db, uuid4())
        assert result is None
