"""Single-plugin execution against the LLM.

Handles provider resolution, the LLM call itself,
result persistence, and approval creation for one plugin at a time.
Called by :mod:`pipeline_orchestrator` for each enabled plugin.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from app.core.config import get_settings
from app.core.constants import PLUGIN_TO_APPROVAL_COLUMN
from app.core.security import get_encryption
from app.models import AIProvider, Approval, ApprovalStatus, UserSettings
from app.models.user import ApprovalMode
from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext, PipelineContext
from app.services.ai import (
    PermanentLLMError,
    TransientLLMError,
    call_llm,
    call_llm_with_tools,
    check_ai_circuit_breaker,
    update_provider_health,
)
from app.services.imap_actions import has_actionable_results
from app.services.persistence import (
    parse_date_field,
    save_applied_labels,
    save_assigned_folder,
    save_auto_reply,
    save_calendar_event,
    save_contact_assignment,
    save_coupons,
    save_email_summary,
    save_newsletter,
    save_otp,
    save_spam_detection,
)
from app.services.prompt_resolver import resolve_prompts
from app.services.provider_resolver import resolve_plugin_provider
from app.services.spam import is_blocked as check_blocklist

if TYPE_CHECKING:
    from pydantic import BaseModel
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import MailAccount
    from app.plugins.auto_reply import AutoReplyResponse
    from app.plugins.calendar_extraction import CalendarEventResponse
    from app.plugins.contacts import ContactAssignmentResponse
    from app.plugins.coupon_extraction import CouponExtractionResponse
    from app.plugins.email_summary import EmailSummaryResponse
    from app.plugins.labeling import LabelingResponse
    from app.plugins.newsletter_detection import NewsletterDetectionResponse
    from app.plugins.otp_extraction import OtpExtractionResponse
    from app.plugins.smart_folder import SmartFolderResponse
    from app.plugins.spam_detection import SpamDetectionResponse

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Result container returned to the orchestrator
# ---------------------------------------------------------------------------


@dataclass
class PluginOutcome:
    """Result of executing a single plugin."""

    plugin_name: str
    plugin_display_name: str = ""
    executed: bool = False
    completed: bool = False
    failed: bool = False
    skipped: bool = False
    skip_reason: str | None = None
    actions_taken: list[str] = field(default_factory=list)
    approval_created: bool = False
    needs_approval: bool = False
    transient_error: bool = False
    transient_error_reason: str | None = None
    failed_provider_id: str | None = None
    break_pipeline: bool = False
    auto_approved: bool = False
    result_summary: str | None = None
    result_details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def execute_plugin(
    *,
    db: AsyncSession,
    plugin: AIFunctionPlugin[Any],
    context: MailContext,
    pipeline: PipelineContext,
    user_settings: UserSettings,
    plugin_provider_map: dict[str, str],
    providers_by_id: dict[str, AIProvider],
    default_provider: AIProvider | None,
    log: structlog.stdlib.BoundLogger,
) -> PluginOutcome:
    """Execute a single plugin through the full LLM cycle.

    Returns a :class:`PluginOutcome` so the orchestrator can decide how
    to proceed (continue, break, re-enqueue, etc.).
    """
    outcome = PluginOutcome(plugin_name=plugin.name, plugin_display_name=plugin.display_name)

    # --- Check if plugin is enabled ---
    approval_col = PLUGIN_TO_APPROVAL_COLUMN.get(plugin.name)
    approval_mode = ApprovalMode.AUTO  # safe default if approval_col is missing
    if approval_col and user_settings:
        raw = getattr(user_settings, approval_col, ApprovalMode.DISABLED)
        approval_mode = ApprovalMode(raw) if not isinstance(raw, ApprovalMode) else raw
        if approval_mode == ApprovalMode.DISABLED:
            log.debug("plugin_disabled_by_user", plugin=plugin.name)
            outcome.skipped = True
            outcome.skip_reason = "disabled_by_user"
            return outcome
    elif not user_settings:
        outcome.skipped = True
        outcome.skip_reason = "no_user_settings"
        return outcome

    # --- Blocklist pre-check for spam_detection ---
    if plugin.name == "spam_detection":
        blocklist_outcome = await _handle_blocklist(
            db=db,
            plugin=plugin,
            context=context,
            pipeline=pipeline,
            approval_col=approval_col,
            approval_mode=approval_mode,
            user_settings=user_settings,
            log=log,
        )
        if blocklist_outcome is not None:
            return blocklist_outcome

    # --- Resolve provider ---
    provider = resolve_plugin_provider(
        plugin.name,
        plugin_provider_map,
        providers_by_id,
        default_provider,
    )
    if provider is None:
        log.warning("no_provider_for_plugin", plugin=plugin.name)
        outcome.failed = True
        outcome.transient_error = True
        outcome.transient_error_reason = f"no_provider:{plugin.name}"
        outcome.break_pipeline = True
        return outcome

    if provider.is_paused:
        log.warning(
            "provider_paused",
            plugin=plugin.name,
            provider_id=str(provider.id),
            provider_name=provider.name,
            paused_reason=provider.paused_reason,
        )
        outcome.failed = True
        outcome.transient_error = True
        outcome.transient_error_reason = f"provider_paused:{plugin.name}"
        outcome.failed_provider_id = str(provider.id)
        outcome.break_pipeline = True
        return outcome

    # --- Render prompt ---
    from app.core.templating import get_template_engine

    engine = get_template_engine()
    system_prompt, user_prompt = await resolve_prompts(
        db,
        UUID(context.user_id),
        plugin,
        engine,
        context,
        language=user_settings.language if user_settings else "en",
        timezone=user_settings.timezone if user_settings else "UTC",
    )

    # --- Decrypt API key ---
    encryption = get_encryption()
    api_key = None
    if provider.api_key:
        api_key = encryption.decrypt(provider.api_key)

    # --- LLM call (always tool-calling mode) ---
    try:
        from app.tools.registry import get_tool_registry

        try:
            tool_registry = get_tool_registry()
            litellm_tools = tool_registry.get_litellm_tools()
        except RuntimeError:
            litellm_tools = []

        # Append tool-calling instruction to system prompt
        tool_system_prompt = (
            system_prompt + "\n\n## Tools\n"
            "You have access to tools that can help you gather additional context "
            "before making your decision. Use them if the email content alone is "
            "insufficient. When you have gathered enough information, call the "
            "`submit_result` tool with your final analysis.\n"
            "If you do not need additional context, call `submit_result` immediately."
        )

        # Inject pipeline/mail context into all tools so they can access it
        if litellm_tools:
            for _tool in tool_registry.get_all_tools():
                _tool.set_context(pipeline=pipeline, mail_context=context)

        # Tool-calling mode: LLM can call tools to gather context
        async def _execute_tool(tool_name: str, **kwargs: Any) -> str:
            tool = tool_registry.get_tool(tool_name)
            if tool is None:
                return f"Error: Unknown tool '{tool_name}'"
            result = await tool.safe_execute(**kwargs)
            log.debug(
                "tool_executed",
                plugin=plugin.name,
                tool=tool_name,
                is_error=result.is_error,
            )
            return result.content

        ai_response, tokens_used = await call_llm_with_tools(
            provider_type=provider.provider_type.value,
            base_url=provider.base_url,
            model_name=provider.model_name,
            api_key=api_key,
            system_prompt=tool_system_prompt,
            user_prompt=user_prompt,
            response_schema=plugin.get_response_schema(),
            tools=litellm_tools,
            tool_executor=_execute_tool,
            max_iterations=get_settings().ai_max_tool_calls,
            max_tokens=provider.max_tokens,
            temperature=provider.temperature,
            user_id=context.user_id,
            timeout=provider.timeout_seconds or user_settings.ai_timeout_seconds,
        )
    except TransientLLMError as e:
        return await _handle_transient_error(
            db=db,
            provider=provider,
            plugin=plugin,
            error=e,
            outcome=outcome,
            log=log,
        )
    except PermanentLLMError as e:
        log.error(
            "plugin_permanent_llm_error",
            plugin=plugin.name,
            provider_id=str(provider.id),
            error=str(e),
        )
        outcome.failed = True
        return outcome
    except ValueError as e:
        log.error("plugin_llm_invalid_output", plugin=plugin.name, error=str(e))
        outcome.failed = True
        return outcome

    log.info("plugin_llm_complete", plugin=plugin.name, tokens=tokens_used)

    # Record successful LLM call
    try:
        await update_provider_health(db, provider.id)
    except Exception:
        log.warning("provider_health_update_failed", provider_id=str(provider.id))

    # --- Execute plugin action ---
    action_result = await plugin.safe_execute(context, ai_response, pipeline=pipeline)

    # --- Reprompt loop: if the plugin requests a retry with corrective prompt ---
    if action_result.retry_prompt:
        log.info("plugin_reprompt_requested", plugin=plugin.name, retry_prompt=action_result.retry_prompt)
        try:
            ai_response, retry_tokens = await call_llm(
                provider_type=provider.provider_type.value,
                base_url=provider.base_url,
                model_name=provider.model_name,
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=action_result.retry_prompt,
                response_schema=plugin.get_response_schema(),
                max_tokens=provider.max_tokens,
                temperature=provider.temperature,
                user_id=context.user_id,
                timeout=provider.timeout_seconds or user_settings.ai_timeout_seconds,
            )
            tokens_used += retry_tokens
        except (TransientLLMError, PermanentLLMError, ValueError) as e:
            log.error("plugin_reprompt_failed", plugin=plugin.name, error=str(e))
            outcome.failed = True
            return outcome

        action_result = await plugin.safe_execute(context, ai_response, pipeline=pipeline)

    # Only mark as "executed" if the plugin produced actionable results.
    # No-op results (e.g. spam_check_passed, no_reply_needed) should NOT
    # count as executed — they would incorrectly trigger notifications.
    outcome.executed = has_actionable_results(action_result.actions_taken)

    if not action_result.success and action_result.error:
        outcome.failed = True
        try:
            await _create_manual_input_approval(
                db,
                user_id=UUID(context.user_id),
                account_id=UUID(context.account_id),
                plugin=plugin,
                context=context,
                error=action_result.error,
            )
            outcome.approval_created = True
        except Exception:
            log.exception("manual_input_approval_creation_failed", plugin=plugin.name)
        return outcome

    # --- Determine approval mode ---
    needs_approval = action_result.requires_approval
    if approval_col and user_settings:
        if approval_mode == ApprovalMode.AUTO:
            needs_approval = False
        elif approval_mode == ApprovalMode.APPROVAL:
            needs_approval = has_actionable_results(action_result.actions_taken)

    # --- Auto-approve threshold: skip approval if confidence exceeds user threshold ---
    auto_approved = False
    if needs_approval and user_settings and user_settings.auto_approve_threshold is not None:
        response_confidence = getattr(ai_response, "confidence", None)
        if response_confidence is not None and response_confidence >= user_settings.auto_approve_threshold:
            needs_approval = False
            auto_approved = True
            log.info(
                "auto_approve_threshold_met",
                plugin=plugin.name,
                confidence=response_confidence,
                threshold=user_settings.auto_approve_threshold,
            )

    outcome.needs_approval = needs_approval
    outcome.auto_approved = auto_approved

    if needs_approval:
        await _create_approval(
            db,
            user_id=UUID(context.user_id),
            account_id=UUID(context.account_id),
            plugin=plugin,
            context=context,
            ai_response=ai_response,
            action_result=action_result,
        )
        outcome.approval_created = True

    # --- Persist results (auto mode) ---
    if not needs_approval:
        await _persist_plugin_result(
            db=db,
            plugin=plugin,
            context=context,
            ai_response=ai_response,
            log=log,
        )
        if action_result.actions_taken:
            outcome.actions_taken = action_result.actions_taken

    outcome.completed = True

    # Extract result summary for queue display
    outcome.result_summary = _extract_result_summary(plugin.name, ai_response)
    outcome.result_details = _extract_result_details(plugin.name, ai_response)

    log.info(
        "plugin_executed",
        plugin=plugin.name,
        actions=action_result.actions_taken,
        requires_approval=action_result.requires_approval,
    )

    # Short-circuit: only spam_detection may skip remaining plugins
    if action_result.skip_remaining_plugins and plugin.name == "spam_detection":
        log.info("pipeline_short_circuit", triggered_by=plugin.name)
        outcome.break_pipeline = True

    return outcome


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _handle_blocklist(
    *,
    db: AsyncSession,
    plugin: AIFunctionPlugin[Any],
    context: MailContext,
    pipeline: PipelineContext,
    approval_col: str | None,
    approval_mode: ApprovalMode,
    user_settings: UserSettings,
    log: structlog.stdlib.BoundLogger,
) -> PluginOutcome | None:
    """Check blocklist for spam_detection; return outcome if blocked, else None."""
    sender_blocked = await check_blocklist(
        db,
        UUID(context.user_id),
        context.sender,
        context.subject,
    )
    if not sender_blocked:
        return None

    log.info("blocklist_hit", sender=context.sender, subject=context.subject)

    outcome = PluginOutcome(
        plugin_name=plugin.name, plugin_display_name=plugin.display_name, executed=True, completed=True
    )
    action_result = ActionResult(
        success=True,
        actions_taken=["move_to_spam (blocklist match)", "mark_as_read"],
        skip_remaining_plugins=True,
    )
    pipeline.set_result(
        plugin.name,
        {"is_spam": True, "confidence": 1.0, "reason": "Sender on blocklist"},
    )
    pipeline.executed.append(plugin.name)

    if approval_col and user_settings:
        if approval_mode != ApprovalMode.APPROVAL:
            outcome.actions_taken = action_result.actions_taken
            await save_spam_detection(
                user_id=UUID(context.user_id),
                is_spam=True,
                confidence=1.0,
                reason="Sender on blocklist",
                source="blocklist",
                mail_id=UUID(context.mail_id),
                db=db,
            )
        else:
            from app.plugins.spam_detection import SpamDetectionResponse

            await _create_approval(
                db,
                user_id=UUID(context.user_id),
                account_id=UUID(context.account_id),
                plugin=plugin,
                context=context,
                ai_response=SpamDetectionResponse(
                    is_spam=True,
                    confidence=1.0,
                    reason="Sender on blocklist",
                ),
                action_result=action_result,
            )
            outcome.approval_created = True

    outcome.break_pipeline = True
    return outcome


async def _handle_transient_error(
    *,
    db: AsyncSession,
    provider: AIProvider,
    plugin: AIFunctionPlugin[Any],
    error: TransientLLMError,
    outcome: PluginOutcome,
    log: structlog.stdlib.BoundLogger,
) -> PluginOutcome:
    """Handle a transient LLM error: record health, signal re-enqueue.

    Uses an independent DB session for health tracking to avoid
    committing partial pipeline results from the main session.
    """
    log.warning(
        "plugin_transient_llm_error",
        plugin=plugin.name,
        provider_id=str(provider.id),
        error=str(error),
    )
    outcome.failed = True
    outcome.transient_error = True
    outcome.transient_error_reason = f"transient_llm_error:{plugin.name}"
    outcome.failed_provider_id = str(provider.id)

    # Persist provider health in a separate session so we don't commit
    # partially-completed plugin results from the main pipeline session.
    try:
        from app.core.database import get_session

        async for health_db in get_session():
            await update_provider_health(health_db, provider.id, error=error.user_message)
            tripped = await check_ai_circuit_breaker(health_db, provider.id)
            if tripped:
                log.warning(
                    "ai_provider_disabled_by_circuit_breaker",
                    provider_id=str(provider.id),
                    provider_name=provider.name,
                )
    except Exception:
        log.warning("provider_health_tracking_failed", provider_id=str(provider.id))

    outcome.break_pipeline = True
    return outcome


async def _persist_plugin_result(
    *,
    db: AsyncSession,
    plugin: AIFunctionPlugin[Any],
    context: MailContext,
    ai_response: BaseModel,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Persist the AI result for a plugin running in auto mode."""
    user_id = UUID(context.user_id)
    account_id = UUID(context.account_id)
    if not context.mail_id:
        log.error("persist_plugin_result_no_mail_id", plugin=plugin.name)
        return
    mail_id = UUID(context.mail_id)

    if plugin.name == "email_summary":
        resp: EmailSummaryResponse = ai_response  # type: ignore[assignment]
        await save_email_summary(
            user_id=user_id,
            summary=resp.summary,
            key_points=resp.key_points,
            urgency=resp.urgency,
            action_required=resp.action_required,
            action_description=resp.action_description,
            mail_id=mail_id,
            db=db,
        )

    elif plugin.name == "newsletter_detection":
        resp_nl: NewsletterDetectionResponse = ai_response  # type: ignore[assignment]
        await save_newsletter(
            user_id=user_id,
            is_newsletter=resp_nl.is_newsletter,
            newsletter_name=resp_nl.newsletter_name or "Unknown",
            sender_address=context.sender,
            unsubscribe_url=resp_nl.unsubscribe_url,
            has_unsubscribe=resp_nl.has_unsubscribe,
            mail_id=mail_id,
            db=db,
        )

    elif plugin.name == "coupon_extraction":
        resp_cp: CouponExtractionResponse = ai_response  # type: ignore[assignment]
        await save_coupons(
            user_id=user_id,
            has_coupons=resp_cp.has_coupons,
            coupons=[c.model_dump() for c in resp_cp.coupons] if resp_cp.coupons else [],
            mail_id=mail_id,
            db=db,
        )

    elif plugin.name == "otp_extraction":
        resp_otp: OtpExtractionResponse = ai_response  # type: ignore[assignment]
        await save_otp(
            user_id=user_id,
            has_codes=resp_otp.has_codes,
            codes=[c.model_dump() for c in resp_otp.codes] if resp_otp.codes else [],
            mail_id=mail_id,
            db=db,
        )

    elif plugin.name == "labeling":
        resp_lbl: LabelingResponse = ai_response  # type: ignore[assignment]
        await save_applied_labels(
            user_id=user_id,
            labels=resp_lbl.labels,
            existing_labels=set(context.existing_labels) if context.existing_labels else None,
            mail_id=mail_id,
            db=db,
        )

    elif plugin.name == "smart_folder":
        resp_cat: SmartFolderResponse = ai_response  # type: ignore[assignment]
        await save_assigned_folder(
            user_id=user_id,
            folder=resp_cat.folder,
            confidence=resp_cat.confidence,
            reason=resp_cat.reason,
            existing_folders=set(context.existing_folders) if context.existing_folders else None,
            mail_id=mail_id,
            db=db,
        )

    elif plugin.name == "calendar_extraction":
        resp_cal: CalendarEventResponse = ai_response  # type: ignore[assignment]
        await save_calendar_event(
            user_id=user_id,
            has_event=resp_cal.has_event,
            title=resp_cal.title,
            start=resp_cal.start,
            end=resp_cal.end,
            location=resp_cal.location,
            description=resp_cal.description,
            is_all_day=resp_cal.is_all_day,
            mail_id=mail_id,
            db=db,
        )

    elif plugin.name == "auto_reply":
        resp_ar: AutoReplyResponse = ai_response  # type: ignore[assignment]
        await save_auto_reply(
            user_id=user_id,
            should_reply=resp_ar.should_reply,
            draft_body=resp_ar.draft_body,
            tone=resp_ar.tone,
            reasoning=resp_ar.reasoning,
            mail_id=mail_id,
            db=db,
        )

        # Upload draft to IMAP Drafts folder
        if resp_ar.should_reply and resp_ar.draft_body:
            from app.services.draft_upload import upload_draft_to_imap

            account = await _load_mail_account(db, account_id)
            if account:
                await upload_draft_to_imap(
                    account=account,
                    user_id=user_id,
                    mail_uid=context.mail_uid,
                    draft_body=resp_ar.draft_body,
                    original_subject=context.subject,
                    original_from=context.sender,
                    original_message_id=context.headers.get("message-id"),
                    original_references=None,
                )

    elif plugin.name == "contacts":
        resp_ct: ContactAssignmentResponse = ai_response  # type: ignore[assignment]
        await save_contact_assignment(
            user_id=user_id,
            sender_email=context.sender,
            contact_id=resp_ct.contact_id,
            contact_name=resp_ct.contact_name,
            confidence=resp_ct.confidence,
            reasoning=resp_ct.reasoning,
            is_new_contact_suggestion=resp_ct.is_new_contact_suggestion,
            auto_writeback=True,
            mail_id=mail_id,
            db=db,
        )

    elif plugin.name == "spam_detection":
        resp_sd: SpamDetectionResponse = ai_response  # type: ignore[assignment]
        await save_spam_detection(
            user_id=user_id,
            is_spam=resp_sd.is_spam,
            confidence=resp_sd.confidence,
            reason=resp_sd.reason,
            source="ai",
            mail_id=mail_id,
            db=db,
        )


async def _load_mail_account(db: AsyncSession, account_id: UUID) -> MailAccount | None:
    """Load a mail account by ID for IMAP operations."""
    from sqlalchemy import select

    from app.models import MailAccount as _MailAccount

    stmt = select(_MailAccount).where(_MailAccount.id == account_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _create_approval(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    plugin: AIFunctionPlugin[Any],
    context: MailContext,
    ai_response: BaseModel,
    action_result: ActionResult,
) -> None:
    """Create an approval record for an AI action that requires user confirmation."""
    approval = Approval(
        user_id=user_id,
        function_type=plugin.name,
        mail_subject=context.subject[:998],
        mail_from=context.sender[:320],
        proposed_action={
            "actions": action_result.actions_taken,
            **ai_response.model_dump(mode="json"),
        },
        ai_reasoning=action_result.approval_summary or plugin.get_approval_summary(ai_response),
        ai_response_data=ai_response.model_dump(mode="json"),
        mail_date=parse_date_field(context.date) if context.date else None,
        mail_id=UUID(context.mail_id),
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().approval_expiry_days),
    )
    db.add(approval)
    await db.flush()


async def _create_manual_input_approval(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    plugin: AIFunctionPlugin[Any],
    context: MailContext,
    error: str,
) -> None:
    """Create a manual_input approval when a plugin fails.

    Instead of fail-open (silently skipping the plugin), we create an
    approval with ``status=manual_input`` so the user can see that this
    plugin failed and decide what to do.
    """
    approval = Approval(
        user_id=user_id,
        function_type=plugin.name,
        mail_subject=context.subject[:998],
        mail_from=context.sender[:320],
        proposed_action={"actions": [], "error": error},
        ai_reasoning=f"Plugin {plugin.display_name} failed: {error}",
        ai_response_data=None,
        mail_date=parse_date_field(context.date) if context.date else None,
        mail_id=UUID(context.mail_id),
        status=ApprovalStatus.MANUAL_INPUT,
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().approval_expiry_days),
    )
    db.add(approval)
    await db.flush()


# ---------------------------------------------------------------------------
# Result summary extraction for queue display
# ---------------------------------------------------------------------------


def _extract_result_summary(plugin_name: str, ai_response: BaseModel) -> str | None:
    """Extract a short human-readable summary from a plugin's AI response."""
    try:
        if plugin_name == "email_summary":
            return getattr(ai_response, "summary", None)
        if plugin_name == "spam_detection":
            is_spam = getattr(ai_response, "is_spam", False)
            reason = getattr(ai_response, "reason", "")
            return f"{'Spam' if is_spam else 'Not spam'}: {reason}" if reason else ("Spam" if is_spam else "Not spam")
        if plugin_name == "smart_folder":
            folder = getattr(ai_response, "folder", None)
            return f"Folder: {folder}" if folder else None
        if plugin_name == "labeling":
            labels = getattr(ai_response, "labels", [])
            return f"Labels: {', '.join(labels)}" if labels else "No labels"
        if plugin_name == "newsletter_detection":
            is_nl = getattr(ai_response, "is_newsletter", False)
            name = getattr(ai_response, "newsletter_name", "")
            return f"Newsletter: {name}" if is_nl else "Not a newsletter"
        if plugin_name == "coupon_extraction":
            has = getattr(ai_response, "has_coupons", False)
            coupons = getattr(ai_response, "coupons", [])
            return f"{len(coupons)} coupon(s) found" if has and coupons else "No coupons"
        if plugin_name == "otp_extraction":
            has = getattr(ai_response, "has_codes", False)
            codes = getattr(ai_response, "codes", [])
            return f"{len(codes)} OTP code(s) found" if has and codes else "No OTP codes"
        if plugin_name == "calendar_extraction":
            has = getattr(ai_response, "has_event", False)
            title = getattr(ai_response, "title", "")
            return f"Event: {title}" if has and title else "No event"
        if plugin_name == "auto_reply":
            should = getattr(ai_response, "should_reply", False)
            return "Reply drafted" if should else "No reply needed"
        if plugin_name == "contacts":
            name = getattr(ai_response, "contact_name", "")
            return f"Contact: {name}" if name else "No contact match"
    except Exception:
        pass
    return None


def _extract_result_details(plugin_name: str, ai_response: BaseModel) -> dict[str, Any] | None:
    """Extract structured details from a plugin's AI response for the queue UI."""
    try:
        data = ai_response.model_dump(mode="json")
        # Remove very large fields to keep the stored JSON small
        for key in ("draft_body",):
            data.pop(key, None)
        return data
    except Exception:
        return None
