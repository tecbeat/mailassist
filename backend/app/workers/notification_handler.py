"""Notification event handler.

Subscribes to ``AIProcessingCompleteEvent`` and sends notifications
via Apprise when the user has configured channels for the relevant events.

Event types are derived dynamically from the plugin registry via each
plugin's ``notification_event_type`` attribute.  Per-channel filtering
routes notifications only to channels that match the mail account and
event type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select

from app.core.database import get_session_ctx
from app.core.events import (
    AIProcessingCompleteEvent,
    Event,
    NotificationSentEvent,
    get_event_bus,
)
from app.models.mail import (
    MailAccount,
    TrackedEmail,
)
from app.models.notifications import NotificationChannel, NotificationConfig
from app.plugins.registry import get_plugin_registry
from app.services.notifications import send_notification

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


def _build_event_type_map() -> dict[str, str]:
    """Build plugin_name → event_type mapping from the plugin registry."""
    registry = get_plugin_registry()
    mapping: dict[str, str] = {}
    for plugin in registry.get_all_plugins():
        if plugin.notification_event_type:
            mapping[plugin.name] = plugin.notification_event_type
    return mapping


async def _load_plugin_context(
    db: AsyncSession,
    event_type: str,
    account_id: UUID,
    mail_uid: str,
) -> dict[str, Any]:
    """Load plugin-specific notification context from the plugin registry.

    Delegates to the plugin's ``load_notification_context()`` method.
    """
    registry = get_plugin_registry()

    # Find the plugin that owns this event type
    for plugin in registry.get_all_plugins():
        if plugin.notification_event_type == event_type:
            try:
                return await plugin.load_notification_context(db, account_id, mail_uid)
            except Exception:
                logger.warning("plugin_context_load_failed", event_type=event_type, plugin=plugin.name)
                return {}

    return {}


def _channel_matches(
    channel: NotificationChannel,
    account_id: UUID,
    event_type: str,
) -> bool:
    """Check if a channel should receive a notification for this event."""
    # Check mail account filter
    if channel.mail_account_ids is not None:
        if str(account_id) not in channel.mail_account_ids:
            return False

    # Check event type filter
    if channel.event_types is not None:
        if event_type not in channel.event_types:
            return False

    return True


async def handle_ai_processing_complete(event: Event) -> None:
    """Send notifications for completed AI processing if configured.

    For each plugin that ran, checks whether any notification channel is
    configured for the event.  Sends one notification per triggered event
    type to each matching channel.
    """
    assert isinstance(event, AIProcessingCompleteEvent)

    if not event.plugins_executed and event.approvals_created == 0:
        return

    log = logger.bind(
        user_id=str(event.user_id),
        account_id=str(event.account_id),
        mail_uid=event.mail_uid,
    )

    # Build dynamic mapping
    plugin_to_event = _build_event_type_map()

    # Determine which event types should fire
    triggered_event_types: list[str] = []
    for plugin_name in event.plugins_executed:
        event_type = plugin_to_event.get(plugin_name)
        if event_type:
            triggered_event_types.append(event_type)

    # Fire approval_needed when any approvals were created
    if event.approvals_created > 0:
        triggered_event_types.append("approval_needed")

    if not triggered_event_types:
        log.debug("notification_skip", reason="no_triggered_events")
        return

    try:
        async with get_session_ctx() as db:
            # Load all notification channels for this user
            channels_result = await db.execute(
                select(NotificationChannel).where(NotificationChannel.user_id == event.user_id)
            )
            channels = channels_result.scalars().all()

            if not channels:
                log.debug("notification_skip", reason="no_channels")
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
            account_result = await db.execute(select(MailAccount).where(MailAccount.id == event.account_id))
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
            config_result = await db.execute(
                select(NotificationConfig).where(NotificationConfig.user_id == event.user_id)
            )
            config = config_result.scalar_one_or_none()
            custom_templates: dict[str, Any] = config.templates if config else {}

            # Send notifications per event type per matching channel
            channels_sent: list[str] = []
            for event_type in triggered_event_types:
                # Find channels that match this event + account
                assert event.account_id is not None
                matching_channels = [
                    c for c in channels if _channel_matches(c, event.account_id, event_type)
                ]

                if not matching_channels:
                    continue

                # Load plugin-specific context
                plugin_ctx = await _load_plugin_context(
                    db,
                    event_type,
                    event.account_id,
                    event.mail_uid,
                )
                context = {**base_context, **plugin_ctx}
                custom_tpl = custom_templates.get(event_type)

                # Send to each matching channel individually
                for channel in matching_channels:
                    success = await send_notification(
                        apprise_urls=[channel.url],
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
                from app.models.mail import EmailSummary

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
                await bus.emit(
                    NotificationSentEvent(
                        user_id=event.user_id,
                        account_id=event.account_id,
                        mail_uid=event.mail_uid,
                        channels=channels_sent,
                        correlation_id=event.correlation_id,
                    )
                )
            else:
                log.debug("notifications_no_matching_channels", event_types=triggered_event_types)

    except Exception:
        log.exception("notification_handler_error")


def register_notification_handlers() -> None:
    """Register notification event handlers on the global event bus."""
    bus = get_event_bus()
    bus.subscribe(AIProcessingCompleteEvent, handle_ai_processing_complete)
