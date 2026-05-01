"""Prompt management API endpoints.

Provides CRUD for user-customizable Jinja2 prompt templates.
Includes preview rendering with sample data and reset-to-default.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserId, DbSession
from app.core.constants import LANGUAGE_NAMES
from app.core.templating import get_template_engine
from app.models import Prompt
from app.models.user import UserSettings
from app.plugins.registry import get_plugin_registry
from app.schemas.prompt import (
    PromptPreviewRequest,
    PromptPreviewResponse,
    PromptResponse,
    PromptUpdate,
    TemplateVariable,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/prompts", tags=["prompts"])

# All available template variables with metadata
_TEMPLATE_VARIABLES: list[dict[str, Any]] = [
    {"name": "sender", "var_type": "String", "description": "Sender email address", "example": "john@example.com"},
    {"name": "sender_name", "var_type": "String", "description": "Display name from header", "example": "John Doe"},
    {
        "name": "contact.display_name",
        "var_type": "String",
        "description": "Matched contact name",
        "example": "John Doe",
    },
    {
        "name": "contact.organization",
        "var_type": "String",
        "description": "Contact's organization",
        "example": "Acme Corp",
    },
    {"name": "contact.title", "var_type": "String", "description": "Contact's job title", "example": "CTO"},
    {
        "name": "contact.phones",
        "var_type": "List",
        "description": "Contact phone numbers",
        "example": '["+49 123 456"]',
    },
    {"name": "recipient", "var_type": "String", "description": "Recipient (To) address", "example": "me@example.com"},
    {"name": "subject", "var_type": "String", "description": "Email subject line", "example": "Meeting Tomorrow"},
    {"name": "body", "var_type": "String", "description": "Email body (truncated)", "example": "Hi, let's discuss..."},
    {"name": "body_plain", "var_type": "String", "description": "Plain text body", "example": "Hi, let's discuss..."},
    {"name": "body_html", "var_type": "String", "description": "HTML body (sanitized)", "example": "<p>Hi</p>"},
    {
        "name": "headers",
        "var_type": "Dict",
        "description": "All email headers",
        "example": '{"List-Unsubscribe": "..."}',
    },
    {"name": "date", "var_type": "DateTime", "description": "Email send date", "example": "2026-03-30T14:30:00Z"},
    {"name": "has_attachments", "var_type": "Boolean", "description": "Has attachments", "example": "true"},
    {
        "name": "attachment_names",
        "var_type": "List",
        "description": "Attachment filenames",
        "example": '["invoice.pdf"]',
    },
    {"name": "account_name", "var_type": "String", "description": "Mail account name", "example": "Work"},
    {"name": "account_email", "var_type": "String", "description": "Mail account address", "example": "me@work.com"},
    {
        "name": "current_time",
        "var_type": "DateTime",
        "description": "Current UTC time",
        "example": "2026-03-30T15:00:00Z",
    },
    {"name": "current_date", "var_type": "String", "description": "Current date", "example": "2026-03-30"},
    {"name": "current_weekday", "var_type": "String", "description": "Weekday name", "example": "Monday"},
    {"name": "current_hour", "var_type": "Integer", "description": "Hour (0-23)", "example": "15"},
    {"name": "existing_labels", "var_type": "List", "description": "Current mail labels", "example": '["important"]'},
    {
        "name": "existing_folders",
        "var_type": "List",
        "description": "Available IMAP folders",
        "example": '["INBOX", "Work"]',
    },
    {"name": "folder_separator", "var_type": "String", "description": "IMAP folder separator", "example": "/"},
    {"name": "mail_size", "var_type": "Integer", "description": "Message size (bytes)", "example": "45230"},
    {"name": "thread_length", "var_type": "Integer", "description": "Thread message count", "example": "3"},
    {"name": "is_reply", "var_type": "Boolean", "description": "Is a reply", "example": "true"},
    {"name": "is_forwarded", "var_type": "Boolean", "description": "Is forwarded", "example": "false"},
    {"name": "language", "var_type": "String", "description": "User language code (ISO 639-1)", "example": "en"},
    {"name": "language_full", "var_type": "String", "description": "User language full name", "example": "English"},
    {"name": "timezone", "var_type": "String", "description": "User timezone (IANA)", "example": "Europe/Berlin"},
    {
        "name": "local_time",
        "var_type": "DateTime",
        "description": "Current time in user timezone",
        "example": "2026-03-30T16:00:00+01:00",
    },
    {
        "name": "excluded_folders",
        "var_type": "List",
        "description": "Folders excluded from smart folder assignment",
        "example": '["Trash", "Junk"]',
    },
]

# Sample data used for prompt preview rendering
_SAMPLE_CONTEXT: dict[str, Any] = {
    "sender": "john.doe@example.com",
    "sender_name": "John Doe",
    "contact": {
        "display_name": "John Doe",
        "organization": "Acme Corp",
        "title": "CTO",
        "phones": ["+49 123 456789"],
    },
    "recipient": "me@work.com",
    "subject": "Meeting Tomorrow at 2pm",
    "body": "Hi, just wanted to confirm our meeting tomorrow at 2pm. Please bring the Q2 report.",
    "body_plain": "Hi, just wanted to confirm our meeting tomorrow at 2pm. Please bring the Q2 report.",
    "body_html": "<p>Hi, just wanted to confirm our meeting tomorrow at 2pm.</p>",
    "headers": {"List-Unsubscribe": "", "Message-ID": "<abc123@example.com>"},
    "date": "2026-03-30T14:30:00Z",
    "has_attachments": True,
    "attachment_names": ["Q2_report.pdf"],
    "account_name": "Work",
    "account_email": "me@work.com",
    "current_time": "2026-03-30T15:00:00Z",
    "current_date": "2026-03-30",
    "current_weekday": "Monday",
    "current_hour": 15,
    "timezone": "Europe/Berlin",
    "local_time": "2026-03-30T16:00:00+01:00",
    "existing_labels": ["important", "work", "meeting"],
    "existing_folders": ["INBOX", "Work", "Work/Projects", "Personal", "Newsletters", "Spam"],
    "folder_separator": "/",
    "mail_size": 45230,
    "thread_length": 3,
    "is_reply": True,
    "is_forwarded": False,
    "language": "en",
    "language_full": "English",
    "excluded_folders": ["Trash", "Junk"],
}


async def _build_preview_context(db: AsyncSession, user_id: str) -> dict[str, Any]:
    """Build a preview template context enriched with real user settings.

    Starts from the static ``_SAMPLE_CONTEXT`` and overrides ``language``,
    ``language_full``, and ``timezone`` from the user's stored settings.
    """
    context = {**_SAMPLE_CONTEXT}

    stmt = select(UserSettings).where(UserSettings.user_id == UUID(user_id))
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()

    if settings:
        lang = settings.language or "en"
        context["language"] = lang
        context["language_full"] = LANGUAGE_NAMES.get(lang, lang)
        context["timezone"] = settings.timezone or "UTC"

    return context


@router.get("")
async def list_prompts(
    db: DbSession,
    user_id: CurrentUserId,
) -> list[PromptResponse]:
    """List all prompts with defaults for each registered plugin.

    Returns user-customized prompts where they exist, and default
    prompts from the template files for the rest.
    """
    uid = UUID(user_id)
    registry = get_plugin_registry()
    get_template_engine()

    # Fetch user-custom prompts
    stmt = select(Prompt).where(Prompt.user_id == uid)
    result = await db.execute(stmt)
    custom_prompts = {p.function_type: p for p in result.scalars().all()}

    prompts: list[PromptResponse] = []
    for plugin in registry.get_all_plugins():
        if plugin.name in custom_prompts:
            prompts.append(PromptResponse.model_validate(custom_prompts[plugin.name]))
        else:
            # Load default template from filesystem
            default_system = _load_default_template(plugin.default_prompt_template)
            prompts.append(
                PromptResponse(
                    function_type=plugin.name,
                    system_prompt=default_system,
                    user_prompt=None,
                    is_custom=False,
                )
            )

    return prompts


@router.get("/variables")
async def list_variables(user_id: CurrentUserId) -> list[TemplateVariable]:
    """List all available template variables with metadata."""
    return [TemplateVariable(**v) for v in _TEMPLATE_VARIABLES]


@router.get("/{function_type}")
async def get_prompt(
    function_type: str,
    db: DbSession,
    user_id: CurrentUserId,
) -> PromptResponse:
    """Get the prompt for a specific AI function.

    Returns the user-customized version if it exists, otherwise the default.
    """
    uid = UUID(user_id)
    _validate_function_type(function_type)

    stmt = select(Prompt).where(Prompt.user_id == uid, Prompt.function_type == function_type)
    result = await db.execute(stmt)
    prompt = result.scalar_one_or_none()

    if prompt:
        return PromptResponse.model_validate(prompt)

    # Return default
    registry = get_plugin_registry()
    plugin = registry.get_plugin(function_type)
    assert plugin is not None
    default_system = _load_default_template(plugin.default_prompt_template)
    return PromptResponse(
        function_type=function_type,
        system_prompt=default_system,
        user_prompt=None,
        is_custom=False,
    )


@router.put("/{function_type}")
async def update_prompt(
    function_type: str,
    data: PromptUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> PromptResponse:
    """Create or update a custom prompt for an AI function."""
    uid = UUID(user_id)
    _validate_function_type(function_type)

    # Validate template syntax
    engine = get_template_engine()
    errors = engine.validate_template(data.system_prompt)
    if data.user_prompt:
        errors.extend(engine.validate_template(data.user_prompt))
    if errors:
        raise HTTPException(status_code=422, detail=f"Template syntax errors: {'; '.join(errors)}")

    stmt = select(Prompt).where(Prompt.user_id == uid, Prompt.function_type == function_type)
    result = await db.execute(stmt)
    prompt = result.scalar_one_or_none()

    if prompt is None:
        prompt = Prompt(
            user_id=uid,
            function_type=function_type,
            system_prompt=data.system_prompt,
            user_prompt=data.user_prompt,
            is_custom=True,
        )
        db.add(prompt)
    else:
        prompt.system_prompt = data.system_prompt
        prompt.user_prompt = data.user_prompt
        prompt.is_custom = True

    await db.flush()

    # Update the template engine's cache
    engine.set_user_template(f"prompts/{function_type}.j2", data.system_prompt)

    logger.info("prompt_updated", function_type=function_type, user_id=user_id)
    return PromptResponse.model_validate(prompt)


@router.post("/{function_type}/reset")
async def reset_prompt(
    function_type: str,
    db: DbSession,
    user_id: CurrentUserId,
) -> PromptResponse:
    """Reset a prompt to its default template by deleting the custom version."""
    uid = UUID(user_id)
    _validate_function_type(function_type)

    stmt = select(Prompt).where(Prompt.user_id == uid, Prompt.function_type == function_type)
    result = await db.execute(stmt)
    prompt = result.scalar_one_or_none()

    if prompt:
        await db.delete(prompt)
        logger.info("prompt_reset", function_type=function_type, user_id=user_id)

    # Return the default
    registry = get_plugin_registry()
    plugin = registry.get_plugin(function_type)
    assert plugin is not None
    default_system = _load_default_template(plugin.default_prompt_template)
    return PromptResponse(
        function_type=function_type,
        system_prompt=default_system,
        user_prompt=None,
        is_custom=False,
    )


@router.post("/{function_type}/preview")
async def preview_prompt(
    function_type: str,
    data: PromptPreviewRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> PromptPreviewResponse:
    """Render a prompt template with sample data for preview.

    Uses realistic sample data enriched with the user's actual language
    and timezone settings so the preview matches real pipeline output.
    """
    _validate_function_type(function_type)
    engine = get_template_engine()

    context = await _build_preview_context(db, user_id)

    errors: list[str] = []
    rendered_system = ""
    rendered_user = None

    try:
        rendered_system = engine.render_string(data.system_prompt, context)
    except Exception as e:
        errors.append(f"System prompt error: {e}")

    if data.user_prompt:
        try:
            rendered_user = engine.render_string(data.user_prompt, context)
        except Exception as e:
            errors.append(f"User prompt error: {e}")

    return PromptPreviewResponse(
        rendered_system=rendered_system,
        rendered_user=rendered_user,
        errors=errors,
    )


def _validate_function_type(function_type: str) -> None:
    """Ensure the function_type corresponds to a registered plugin."""
    registry = get_plugin_registry()
    if function_type not in registry:
        raise HTTPException(status_code=404, detail=f"Unknown AI function: {function_type}")


def _load_default_template(template_path: str) -> str:
    """Load a default template file from disk.

    Falls back to a placeholder if the file doesn't exist yet or the
    plugin has no template (empty ``default_prompt_template``).
    """
    if not template_path:
        return ""
    full_path = Path(__file__).parent.parent / "templates" / template_path
    if full_path.is_file():
        return full_path.read_text()
    return f"# Default template for {template_path} (not yet created)"
