"""Prompt resolution for AI plugins.

Resolves system and user prompts for a given plugin by checking for
user-customized templates in the database first, then falling back
to the default template from the filesystem.  Previously duplicated
in mail_processor.py and pipeline.py.
"""

from datetime import UTC, datetime, tzinfo
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import LANGUAGE_NAMES
from app.core.templating import TemplateEngine
from app.models import Prompt
from app.plugins.base import AIFunctionPlugin, MailContext


async def resolve_prompts(
    db: AsyncSession,
    user_id: UUID,
    plugin: AIFunctionPlugin[Any],
    engine: TemplateEngine,
    context: MailContext,
    language: str = "en",
    timezone: str = "UTC",
) -> tuple[str, str]:
    """Resolve system and user prompts for a plugin.

    Checks for user-customized prompts in the database first,
    falls back to the default template from the filesystem.
    Returns rendered (system_prompt, user_prompt) strings.
    """
    language_full = LANGUAGE_NAMES.get(language, language)

    # Use user's timezone for date/time values in prompts so that
    # calendar_extraction (and similar) sees the correct local date
    try:
        from zoneinfo import ZoneInfo

        tz: tzinfo = ZoneInfo(timezone)
    except (KeyError, Exception):
        tz = UTC
    now = datetime.now(tz)

    template_vars = {
        "sender": context.sender,
        "sender_name": context.sender_name,
        "recipient": context.recipient,
        "subject": context.subject,
        "body": context.body or "",
        "body_plain": context.body_plain or "",
        "body_html": context.body_html or "",
        "headers": context.headers,
        "date": context.date,
        "has_attachments": context.has_attachments,
        "attachment_names": context.attachment_names,
        "account_name": context.account_name,
        "account_email": context.account_email,
        "existing_labels": context.existing_labels,
        "existing_folders": context.existing_folders,
        "excluded_folders": context.excluded_folders,
        "folder_separator": context.folder_separator,
        "mail_size": context.mail_size,
        "thread_length": context.thread_length,
        "is_reply": context.is_reply,
        "is_forwarded": context.is_forwarded,
        "contact": context.contact,
        "user_contacts": context.user_contacts or [],
        "current_time": now.isoformat(),
        "current_date": now.strftime("%Y-%m-%d"),
        "current_weekday": now.strftime("%A"),
        "current_hour": now.hour,
        "language": language,
        "language_full": language_full,
    }

    # Check for user-customized prompt
    stmt = select(Prompt).where(
        Prompt.user_id == user_id,
        Prompt.function_type == plugin.name,
    )
    result = await db.execute(stmt)
    custom_prompt = result.scalar_one_or_none()

    if custom_prompt and custom_prompt.is_custom:
        system_prompt = engine.render_string(custom_prompt.system_prompt, template_vars)
        user_prompt = (
            engine.render_string(custom_prompt.user_prompt, template_vars)
            if custom_prompt.user_prompt
            else "Analyze the email above and respond with the required JSON format."
        )
    else:
        # Use default template from filesystem
        system_prompt = engine.render(plugin.default_prompt_template, template_vars)
        user_prompt = "Analyze the email above and respond with the required JSON format."

    return system_prompt, user_prompt
