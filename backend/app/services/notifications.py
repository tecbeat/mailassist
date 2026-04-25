"""Notification service using Apprise.

Wraps the Apprise library for sending notifications to configured channels.
Renders Jinja2 notification templates before sending.
"""

from typing import Any

import apprise
import structlog

from app.core.templating import get_template_engine

logger = structlog.get_logger()

# Default notification templates by event type
_DEFAULT_TEMPLATES: dict[str, str] = {
    "reply_needed": "notifications/reply_needed.j2",
    "coupon_found": "notifications/coupon_found.j2",
    "calendar_created": "notifications/calendar_created.j2",
    "email_summary": "notifications/email_summary.j2",
    "contact_assigned": "notifications/contact_assigned.j2",
    "approval_needed": "notifications/approval_needed.j2",
}

_FALLBACK_TEMPLATE = "notifications/default.j2"


async def send_notification(
    apprise_urls: list[str],
    event_type: str,
    context: dict[str, Any],
    custom_template: str | None = None,
) -> bool:
    """Send a notification to all configured Apprise URLs.

    Renders the appropriate template for the event type, then sends
    via Apprise to all URLs. Returns True if at least one notification
    was sent successfully.
    """
    if not apprise_urls:
        logger.debug("notification_skip", reason="no_apprise_urls")
        return False

    engine = get_template_engine()

    # Render notification body
    body = _render_notification(engine, event_type, context, custom_template)

    # Build title from context
    subject = context.get("subject", "")
    account_name = context.get("account_name", "")
    title = f"[{account_name}] {event_type.replace('_', ' ').title()}: {subject[:60]}"

    # Send via Apprise
    ap = apprise.Apprise()
    for url in apprise_urls:
        ap.add(url)

    try:
        result = await _send_async(ap, body=body, title=title)
        logger.info(
            "notification_sent",
            event_type=event_type,
            urls_count=len(apprise_urls),
            success=result,
        )
        return result
    except Exception:
        logger.exception("notification_send_failed", event_type=event_type)
        return False


async def send_test_notification(apprise_urls: list[str], message: str) -> bool:
    """Send a test notification to validate Apprise configuration."""
    if not apprise_urls:
        return False

    ap = apprise.Apprise()
    for url in apprise_urls:
        ap.add(url)

    try:
        return await _send_async(
            ap,
            body=message,
            title="mailassist - Test Notification",
        )
    except Exception:
        logger.exception("test_notification_failed")
        return False


def _render_notification(
    engine: Any,
    event_type: str,
    context: dict[str, Any],
    custom_template: str | None = None,
) -> str:
    """Render a notification template with context variables.

    Priority: custom_template (from DB) -> event-specific default -> fallback default.
    """
    if custom_template:
        try:
            return engine.render_string(custom_template, context)
        except Exception:
            logger.warning(
                "custom_template_render_failed",
                event_type=event_type,
                fallback="default",
            )

    # Try event-specific default template
    template_name = _DEFAULT_TEMPLATES.get(event_type, _FALLBACK_TEMPLATE)
    try:
        return engine.render(template_name, context)
    except Exception:
        logger.debug("default_template_not_found", template=template_name)

    # Hardcoded fallback
    subject = context.get("subject", "Unknown")
    sender = context.get("sender", "Unknown")
    return f"New event: {event_type}\nFrom: {sender}\nSubject: {subject}"


async def _send_async(ap: apprise.Apprise, body: str, title: str) -> bool:
    """Send notification asynchronously.

    Apprise supports async sending natively via async_notify.
    """
    return await ap.async_notify(body=body, title=title)
