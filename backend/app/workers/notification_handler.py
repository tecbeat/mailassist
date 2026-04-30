"""Notification event handler.

Subscribes to ``AIProcessingCompleteEvent`` and sends notifications
via Apprise when the user has enabled the relevant notify_on toggle.

Mapping from plugin names to notification event types:

    auto_reply        -> reply_needed
    spam_detection    -> spam_detected
    coupon_extraction -> coupon_found
    calendar_extraction -> calendar_event_created
    rules             -> rule_executed
    newsletter_detection -> newsletter_detected
    email_summary     -> email_summary
    contacts          -> contact_assigned
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_ctx
from app.core.events import (
    AIProcessingCompleteEvent,
    Event,
    NotificationSentEvent,
    get_event_bus,
)
from app.models.mail import (
    AutoReplyRecord,
    CalendarEvent,
    ContactAssignment,
    EmailSummary,
    ExtractedCoupon,
    MailAccount,
    TrackedEmail,
)
from app.models.notifications import NotificationConfig
from app.services.notifications import send_notification

logger = structlog.get_logger()

# Plugin name -> notify_on toggle key
_PLUGIN_TO_EVENT_TYPE: dict[str, str] = {
    "auto_reply": "reply_needed",
    "spam_detection": "spam_detected",
    "coupon_extraction": "coupon_found",
    "calendar_extraction": "calendar_event_created",
    "rules": "rule_executed",
    "newsletter_detection": "newsletter_detected",
    "email_summary": "email_summary",
    "contacts": "contact_assigned",
}


async def _load_plugin_context(
    db: AsyncSession,
    event_type: str,
    account_id: UUID,
    mail_uid: str,
) -> dict[str, Any]:
    """Load plugin-specific result data for notification template context.

    Each event type maps to a specific result table.  Returns a dict
    of template variables that will be merged into the notification context.
    """
    extra: dict[str, Any] = {}

    try:
        if event_type == "email_summary":
            result = await db.execute(
                select(EmailSummary).where(
                    EmailSummary.mail_account_id == account_id,
                    EmailSummary.mail_uid == mail_uid,
                )
            )
            summary = result.scalar_one_or_none()
            if summary:
                extra["summary"] = summary.summary
                extra["key_points"] = summary.key_points or []
                extra["urgency"] = summary.urgency or "normal"
                extra["action_required"] = summary.action_required
                extra["action_description"] = summary.action_description or ""

        elif event_type == "coupon_found":
            result = await db.execute(
                select(ExtractedCoupon).where(
                    ExtractedCoupon.mail_account_id == account_id,
                    ExtractedCoupon.mail_uid == mail_uid,
                )
            )
            coupons = result.scalars().all()
            extra["coupon_codes"] = [c.code for c in coupons]
            extra["coupons"] = [
                {"code": c.code, "description": c.description, "store": c.store}
                for c in coupons
            ]

        elif event_type == "calendar_event_created":
            result = await db.execute(
                select(CalendarEvent).where(
                    CalendarEvent.mail_account_id == account_id,
                    CalendarEvent.mail_uid == mail_uid,
                )
            )
            cal = result.scalar_one_or_none()
            if cal:
                extra["calendar_event"] = {
                    "title": cal.title,
                    "start": cal.start,
                    "end": cal.end,
                    "location": cal.location,
                    "description": cal.description,
                }

        elif event_type == "reply_needed":
            result = await db.execute(
                select(AutoReplyRecord).where(
                    AutoReplyRecord.mail_account_id == account_id,
                    AutoReplyRecord.mail_uid == mail_uid,
                )
            )
            reply = result.scalar_one_or_none()
            if reply:
                extra["action_taken"] = f"Draft reply created (tone: {reply.tone or 'default'})"
                extra["draft_body"] = reply.draft_body
                extra["tone"] = reply.tone

        elif event_type == "contact_assigned":
            result = await db.execute(
                select(ContactAssignment).where(
                    ContactAssignment.mail_account_id == account_id,
                    ContactAssignment.mail_uid == mail_uid,
                )
            )
            assignment = result.scalar_one_or_none()
            if assignment:
                extra["contact_name"] = assignment.contact_name
                extra["confidence"] = assignment.confidence
                extra["is_new_contact_suggestion"] = assignment.is_new_contact_suggestion
                extra["reasoning"] = assignment.reasoning

    except Exception:
        logger.warning("plugin_context_load_failed", event_type=event_type)

    return extra


async def handle_ai_processing_complete(event: Event) -> None:
    """Send notifications for completed AI processing if configured.

    For each plugin that ran, checks whether the user has enabled the
    corresponding notification toggle.  Sends one notification per
    triggered event type.
    """
    assert isinstance(event, AIProcessingCompleteEvent)

    if not event.plugins_executed and event.approvals_created == 0:
        return

    log = logger.bind(
        user_id=str(event.user_id),
        account_id=str(event.account_id),
        mail_uid=event.mail_uid,
    )

    # Determine which event types should fire
    triggered_event_types: list[str] = []
    for plugin_name in event.plugins_executed:
        event_type = _PLUGIN_TO_EVENT_TYPE.get(plugin_name)
        if event_type:
            triggered_event_types.append(event_type)

    # Fire approval_needed when any approvals were created
    if event.approvals_created > 0:
        triggered_event_types.append("approval_needed")

    if not triggered_event_types:
        log.debug("notification_skip", reason="no_triggered_events")
        return

    # Load notification config and mail metadata from DB
    try:
        async with get_session_ctx() as db:
            # Load NotificationConfig
            config_result = await db.execute(
                select(NotificationConfig).where(
                    NotificationConfig.user_id == event.user_id
                )
            )
            config = config_result.scalar_one_or_none()

            if not config or not config.apprise_urls:
                log.debug("notification_skip", reason="no_config_or_urls")
                return

            notify_on: dict = config.notify_on or {}

            # Filter to only event types the user has enabled
            enabled_types = [
                et for et in triggered_event_types if notify_on.get(et, False)
            ]

            if not enabled_types:
                log.debug("notification_skip", reason="no_enabled_toggles",
                          triggered=triggered_event_types)
                return

            # Load TrackedEmail for context (subject, sender)
            mail_result = await db.execute(
                select(TrackedEmail).where(
                    TrackedEmail.mail_account_id == event.account_id,
                    TrackedEmail.mail_uid == event.mail_uid,
                    TrackedEmail.current_folder == event.current_folder,
                )
            )
            tracked_email = mail_result.scalars().first()

            # Load MailAccount for account name
            account_result = await db.execute(
                select(MailAccount).where(MailAccount.id == event.account_id)
            )
            account = account_result.scalar_one_or_none()

            subject = tracked_email.subject if tracked_email else "Unknown"
            sender = tracked_email.sender if tracked_email else "Unknown"
            account_name = account.name if account else "Unknown"
            account_email = account.email_address if account else ""

            # Extract sender_name from "Name <email>" format
            sender_name = sender or ""
            if sender_name and "<" in sender_name:
                sender_name = sender_name.split("<")[0].strip()
            elif sender_name and "@" in sender_name:
                sender_name = sender_name.split("@")[0]

            # Build base context for template rendering
            base_context: dict[str, Any] = {
                "subject": subject,
                "sender": sender,
                "sender_name": sender_name,
                "account_name": account_name,
                "account_email": account_email,
                "mail_uid": event.mail_uid,
                "plugins_executed": event.plugins_executed,
                "approvals_created": event.approvals_created,
            }

            # Get custom templates from config
            custom_templates: dict = config.templates or {}

            # Send one notification per enabled event type
            channels_sent: list[str] = []
            for event_type in enabled_types:
                # Enrich context with plugin-specific data
                plugin_ctx = await _load_plugin_context(
                    db, event_type, event.account_id, event.mail_uid,
                )
                context = {**base_context, **plugin_ctx}

                custom_tpl = custom_templates.get(event_type)
                success = await send_notification(
                    apprise_urls=config.apprise_urls,
                    event_type=event_type,
                    context=context,
                    custom_template=custom_tpl,
                )
                if success:
                    channels_sent.append(event_type)

            if channels_sent:
                log.info(
                    "notifications_dispatched",
                    event_types=channels_sent,
                    count=len(channels_sent),
                )

                # Mark email summary as notified to prevent duplicates
                summary_result = await db.execute(
                    select(EmailSummary).where(
                        EmailSummary.mail_account_id == event.account_id,
                        EmailSummary.mail_uid == event.mail_uid,
                    )
                )
                summary = summary_result.scalar_one_or_none()
                if summary:
                    summary.notified = True
                    await db.commit()

                # Emit observability event
                bus = get_event_bus()
                await bus.emit(NotificationSentEvent(
                    user_id=event.user_id,
                    account_id=event.account_id,
                    mail_uid=event.mail_uid,
                    channels=channels_sent,
                    correlation_id=event.correlation_id,
                ))
            else:
                log.warning("notifications_all_failed", event_types=enabled_types)

    except Exception:
        log.exception("notification_handler_error")


def register_notification_handlers() -> None:
    """Register notification event handlers on the global event bus."""
    bus = get_event_bus()
    bus.subscribe(AIProcessingCompleteEvent, handle_ai_processing_complete)
    logger.info("notification_handlers_registered")
