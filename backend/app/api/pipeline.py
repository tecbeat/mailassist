"""Pipeline test API endpoint.

Provides a dry-run pipeline test that runs sample email data through
all enabled AI plugins without persisting results or executing IMAP actions.
Results are streamed via Server-Sent Events so the frontend can display
live progress as each plugin step is processed.
"""

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Request
from sqlalchemy import select
from starlette.responses import StreamingResponse

from app.api.deps import CurrentUserId, DbSession
from app.core.constants import PLUGIN_TO_APPROVAL_COLUMN
from app.core.security import get_encryption
from app.core.templating import get_template_engine
from app.models import AIProvider, LabelChangeLog, UserSettings
from app.models.user import ApprovalMode
from app.plugins.base import AIFunctionPlugin, MailContext, PipelineContext
from app.plugins.registry import get_plugin_registry
from app.schemas.pipeline import (
    PipelineTestRequest,
    PluginTestResult,
)
from app.services.ai import call_llm
from app.services.prompt_resolver import resolve_prompts
from app.services.provider_resolver import get_default_provider, resolve_plugin_provider

logger = structlog.get_logger()

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


def _sse(event: str, data: dict) -> str:
    """Format a single Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("/test")
async def test_pipeline(
    data: PipelineTestRequest,
    db: DbSession,
    user_id: CurrentUserId,
    request: Request,
) -> StreamingResponse:
    """Test the AI processing pipeline with sample email data (SSE stream).

    Streams progress events as each plugin step is processed:
      - ``step``: a plugin is about to be processed (index, total, name)
      - ``skip``: a plugin was skipped (with reason)
      - ``result``: a plugin finished (full PluginTestResult)
      - ``done``: pipeline completed (summary)
      - ``error``: fatal pipeline error
    """

    async def _generate() -> AsyncGenerator[str, None]:
        log = logger.bind(user_id=user_id, test_pipeline=True)
        total_tokens = 0
        results: list[PluginTestResult] = []

        try:
            # Fetch user settings
            settings_stmt = select(UserSettings).where(UserSettings.user_id == UUID(user_id))
            settings_result = await db.execute(settings_stmt)
            user_settings = settings_result.scalar_one_or_none()

            # Fetch existing labels for context
            existing_labels_stmt = (
                select(LabelChangeLog.label)
                .where(LabelChangeLog.user_id == UUID(user_id))
                .distinct()
            )
            existing_labels_result = await db.execute(existing_labels_stmt)
            existing_labels = [row[0] for row in existing_labels_result.all()]

            # Resolve providers
            default_provider = await get_default_provider(db, UUID(user_id))
            if not default_provider:
                yield _sse("error", {"error": "No AI provider configured. Please add an AI provider first."})
                return

            plugin_provider_map = (user_settings.plugin_provider_map or {}) if user_settings else {}
            all_providers_stmt = select(AIProvider).where(AIProvider.user_id == UUID(user_id))
            all_providers_result = await db.execute(all_providers_stmt)
            providers_by_id = {str(p.id): p for p in all_providers_result.scalars().all()}

            encryption = get_encryption()

            # Build test mail context
            test_date = data.date or datetime.now(UTC).isoformat()
            context = MailContext(
                user_id=user_id,
                account_id=str(uuid4()),
                mail_uid="TEST-" + str(uuid4())[:8],
                sender=data.sender,
                sender_name=data.sender_name,
                recipient=data.recipient,
                subject=data.subject,
                body=data.body,
                body_plain=data.body,
                body_html="",
                headers={
                    "from": f"{data.sender_name} <{data.sender}>",
                    "to": data.recipient,
                    "subject": data.subject,
                    "date": test_date,
                },
                date=test_date,
                has_attachments=data.has_attachments,
                attachment_names=[],
                account_name="Test Account",
                account_email=data.recipient,
                existing_labels=existing_labels,
                existing_folders=["INBOX", "Sent", "Drafts", "Trash", "Spam"],
                excluded_folders=[],
                folder_separator="/",
                mail_size=len(data.body.encode("utf-8")),
                thread_length=1,
                is_reply=data.is_reply,
                is_forwarded=data.is_forwarded,
                contact=None,
            )

            # Collect pipeline plugins in order
            registry = get_plugin_registry()
            engine = get_template_engine()
            pipeline = PipelineContext()

            all_plugins = registry.get_all_plugins()
            if user_settings and user_settings.plugin_order:
                order_map = {name: idx for idx, name in enumerate(user_settings.plugin_order)}
                fallback = len(order_map)
                all_plugins = sorted(all_plugins, key=lambda p: order_map.get(p.name, fallback))

            pipeline_plugins = [p for p in all_plugins if p.runs_in_pipeline]
            total_steps = len(pipeline_plugins)

            # Stream: init event with plugin list
            yield _sse("init", {
                "total_steps": total_steps,
                "plugins": [
                    {"name": p.name, "display_name": p.display_name}
                    for p in pipeline_plugins
                ],
            })

            for step_index, plugin in enumerate(pipeline_plugins):
                # Check client disconnect
                if await request.is_disconnected():
                    return

                # Check if plugin is enabled
                approval_col = PLUGIN_TO_APPROVAL_COLUMN.get(plugin.name)
                if approval_col and user_settings:
                    approval_mode = getattr(user_settings, approval_col, ApprovalMode.DISABLED)
                    if approval_mode == ApprovalMode.DISABLED:
                        skip_result = PluginTestResult(
                            plugin_name=plugin.name,
                            display_name=plugin.display_name,
                            success=True,
                            skipped=True,
                            skip_reason="Plugin disabled by user settings",
                        )
                        results.append(skip_result)
                        yield _sse("skip", {
                            "step": step_index,
                            "total_steps": total_steps,
                            "result": skip_result.model_dump(),
                        })
                        continue
                elif not user_settings:
                    skip_result = PluginTestResult(
                        plugin_name=plugin.name,
                        display_name=plugin.display_name,
                        success=False,
                        skipped=True,
                        skip_reason="No user settings configured",
                    )
                    results.append(skip_result)
                    yield _sse("skip", {
                        "step": step_index,
                        "total_steps": total_steps,
                        "result": skip_result.model_dump(),
                    })
                    break

                # Stream: step starting
                yield _sse("step", {
                    "step": step_index,
                    "total_steps": total_steps,
                    "plugin_name": plugin.name,
                    "display_name": plugin.display_name,
                    "status": "running",
                })

                try:
                    # Resolve prompts
                    system_prompt, user_prompt = await resolve_prompts(
                        db, UUID(user_id), plugin, engine, context,
                        language=user_settings.language if user_settings else "en",
                        timezone=user_settings.timezone if user_settings else "UTC",
                    )

                    # Resolve provider
                    provider = resolve_plugin_provider(
                        plugin.name, plugin_provider_map, providers_by_id, default_provider,
                    )
                    if provider is None:
                        skip_result = PluginTestResult(
                            plugin_name=plugin.name,
                            display_name=plugin.display_name,
                            success=False,
                            skipped=True,
                            skip_reason="No AI provider assigned",
                        )
                        results.append(skip_result)
                        yield _sse("skip", {
                            "step": step_index,
                            "total_steps": total_steps,
                            "result": skip_result.model_dump(),
                        })
                        continue

                    api_key = None
                    if provider.api_key:
                        api_key = encryption.decrypt(provider.api_key)

                    # Call LLM
                    ai_response, tokens_used = await call_llm(
                        provider_type=provider.provider_type.value,
                        base_url=provider.base_url,
                        model_name=provider.model_name,
                        api_key=api_key,
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        response_schema=plugin.get_response_schema(),
                        max_tokens=provider.max_tokens,
                        temperature=provider.temperature,
                        user_id=user_id,
                        timeout=provider.timeout_seconds or (user_settings.ai_timeout_seconds if user_settings else None),
                    )

                    total_tokens += tokens_used

                    # Execute plugin action (dry-run)
                    action_result = await plugin.safe_execute(context, ai_response, pipeline=pipeline)

                    plugin_result = PluginTestResult(
                        plugin_name=plugin.name,
                        display_name=plugin.display_name,
                        success=action_result.success,
                        actions=action_result.actions_taken,
                        ai_response=ai_response.model_dump(mode="json") if ai_response else None,
                        tokens_used=tokens_used,
                    )
                    results.append(plugin_result)

                    yield _sse("result", {
                        "step": step_index,
                        "total_steps": total_steps,
                        "result": plugin_result.model_dump(),
                    })

                    log.info(
                        "test_plugin_executed",
                        plugin=plugin.name,
                        tokens=tokens_used,
                        actions=action_result.actions_taken,
                    )

                    # Respect short-circuit
                    if action_result.skip_remaining_plugins:
                        log.info("test_pipeline_short_circuit", triggered_by=plugin.name)
                        break

                except ValueError as e:
                    logger.warning("plugin_test_invalid_llm_output", plugin=plugin.name, error=str(e))
                    err_result = PluginTestResult(
                        plugin_name=plugin.name,
                        display_name=plugin.display_name,
                        success=False,
                        error="Invalid LLM output",
                    )
                    results.append(err_result)
                    yield _sse("result", {
                        "step": step_index,
                        "total_steps": total_steps,
                        "result": err_result.model_dump(),
                    })
                except Exception as e:
                    log.exception("test_plugin_failed", plugin=plugin.name)
                    err_result = PluginTestResult(
                        plugin_name=plugin.name,
                        display_name=plugin.display_name,
                        success=False,
                        error=f"Plugin execution failed: {type(e).__name__}",
                    )
                    results.append(err_result)
                    yield _sse("result", {
                        "step": step_index,
                        "total_steps": total_steps,
                        "result": err_result.model_dump(),
                    })

            # Stream: done
            plugins_executed = sum(1 for r in results if not r.skipped)
            yield _sse("done", {
                "success": True,
                "plugins_executed": plugins_executed,
                "total_tokens": total_tokens,
            })

        except Exception:
            log.exception("test_pipeline_failed")
            yield _sse("error", {
                "error": "Pipeline test failed unexpectedly. Check server logs for details.",
            })

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
