"""In-process event bus for loose coupling between pipeline handlers.

Implements the event-driven mail processing pipeline described in Section 4.5.
Events are dispatched synchronously within the same process using async handlers.
"""

import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import structlog

logger = structlog.get_logger()

# Default timeout for individual event handlers (seconds).
HANDLER_TIMEOUT_SECONDS = 30.0

# Type alias for event handlers
EventHandler = Callable[["Event"], Coroutine[Any, Any, None]]


@dataclass
class Event:
    """Base class for all events in the processing pipeline."""

    event_id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    correlation_id: str | None = None

    @property
    def event_type(self) -> str:
        return self.__class__.__name__


@dataclass
class MailReceivedEvent(Event):
    """Emitted when a new mail is detected via IDLE or polling."""

    user_id: UUID | None = None
    account_id: UUID | None = None
    mail_uid: str = ""


@dataclass
class MailParsedEvent(Event):
    """Emitted after mail headers and body are parsed."""

    user_id: UUID | None = None
    account_id: UUID | None = None
    mail_uid: str = ""
    sender: str = ""
    subject: str = ""


@dataclass
class ContactMatchedEvent(Event):
    """Emitted after sender is matched (or not) to a contact."""

    user_id: UUID | None = None
    account_id: UUID | None = None
    mail_uid: str = ""
    contact_id: UUID | None = None


@dataclass
class RulesEvaluatedEvent(Event):
    """Emitted after rules are evaluated."""

    user_id: UUID | None = None
    account_id: UUID | None = None
    mail_uid: str = ""
    actions_taken: list[str] = field(default_factory=list)


@dataclass
class AIProcessingCompleteEvent(Event):
    """Emitted after all AI plugins have processed the mail."""

    user_id: UUID | None = None
    account_id: UUID | None = None
    mail_uid: str = ""
    current_folder: str = "INBOX"
    plugins_executed: list[str] = field(default_factory=list)
    approvals_created: int = 0


@dataclass
class MailProcessingFailedEvent(Event):
    """Emitted when mail processing fails at any stage.

    Enables observability: subscribers can alert, increment error counters,
    or trigger compensating actions.
    """

    user_id: UUID | None = None
    account_id: UUID | None = None
    mail_uid: str = ""
    stage: str = ""
    error_type: str = ""
    error_message: str = ""


@dataclass
class NotificationSentEvent(Event):
    """Emitted after notifications are dispatched."""

    user_id: UUID | None = None
    account_id: UUID | None = None
    mail_uid: str = ""
    channels: list[str] = field(default_factory=list)


@dataclass
class AccountReactivatedEvent(Event):
    """Emitted when a mail account is reactivated (unpaused).

    Triggers immediate scheduling of pending mails for this account.
    """

    user_id: UUID | None = None
    account_id: UUID | None = None


@dataclass
class ProviderReactivatedEvent(Event):
    """Emitted when an AI provider is reactivated (unpaused).

    Triggers immediate scheduling of pending mails for all accounts
    belonging to this provider's user.
    """

    user_id: UUID | None = None
    provider_id: UUID | None = None


class EventBus:
    """Simple in-process async event bus.

    Handlers subscribe to event types and are called when events are emitted.
    Each handler failure is isolated -- one handler failing does not block others.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: type[Event], handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type.__name__].append(handler)
        logger.debug("event_handler_registered", event_type=event_type.__name__, handler=handler.__name__)

    def unsubscribe(self, event_type: type[Event], handler: EventHandler) -> None:
        """Remove a handler for a specific event type."""
        handlers = self._handlers.get(event_type.__name__, [])
        if handler in handlers:
            handlers.remove(handler)

    async def emit(self, event: Event) -> None:
        """Emit an event to all registered handlers.

        Handlers are called sequentially in registration order.
        Each handler has a timeout of ``HANDLER_TIMEOUT_SECONDS`` — a slow
        handler will not block the rest of the pipeline indefinitely.
        Handler failures (including timeouts) are logged but do not prevent
        other handlers from executing.
        """
        event_type = event.event_type
        handlers = self._handlers.get(event_type, [])

        if not handlers:
            logger.debug("no_handlers_for_event", event_type=event_type)
            return

        logger.info(
            "event_emitted",
            event_type=event_type,
            event_id=str(event.event_id),
            handler_count=len(handlers),
            correlation_id=event.correlation_id,
        )

        for handler in handlers:
            try:
                await asyncio.wait_for(
                    handler(event),
                    timeout=HANDLER_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "event_handler_timeout",
                    event_type=event_type,
                    handler=handler.__name__,
                    event_id=str(event.event_id),
                    timeout_seconds=HANDLER_TIMEOUT_SECONDS,
                )
            except Exception:
                logger.exception(
                    "event_handler_failed",
                    event_type=event_type,
                    handler=handler.__name__,
                    event_id=str(event.event_id),
                )

    def clear(self) -> None:
        """Remove all registered handlers. Useful for testing."""
        self._handlers.clear()


# Module-level singleton
_event_bus: EventBus | None = None


def init_event_bus() -> EventBus:
    """Initialize and return the global event bus."""
    global _event_bus
    _event_bus = EventBus()
    return _event_bus


def get_event_bus() -> EventBus:
    """Return the global event bus instance."""
    if _event_bus is None:
        raise RuntimeError("Event bus not initialized. Call init_event_bus() first.")
    return _event_bus
