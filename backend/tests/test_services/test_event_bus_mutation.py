"""Tests for EventBus handler list mutation safety.

Verifies that unsubscribing during emit does not skip handlers.
"""

from __future__ import annotations

import pytest

from app.core.events import Event, EventBus, MailReceivedEvent


@pytest.mark.asyncio
async def test_unsubscribe_during_emit_does_not_skip_handlers():
    """If handler A unsubscribes itself during emit, handler B must still run."""
    bus = EventBus()
    called: list[str] = []

    async def handler_a(event: Event) -> None:
        called.append("a")
        bus.unsubscribe(MailReceivedEvent, handler_a)

    async def handler_b(event: Event) -> None:
        called.append("b")

    bus.subscribe(MailReceivedEvent, handler_a)
    bus.subscribe(MailReceivedEvent, handler_b)

    await bus.emit(MailReceivedEvent())

    assert called == ["a", "b"]
    # handler_a should be unsubscribed now
    assert handler_a not in bus._handlers["MailReceivedEvent"]


@pytest.mark.asyncio
async def test_unsubscribe_other_handler_during_emit():
    """If handler A unsubscribes handler B during emit, B still runs
    (because emit iterates a snapshot)."""
    bus = EventBus()
    called: list[str] = []

    async def handler_b(event: Event) -> None:
        called.append("b")

    async def handler_a(event: Event) -> None:
        called.append("a")
        bus.unsubscribe(MailReceivedEvent, handler_b)

    bus.subscribe(MailReceivedEvent, handler_a)
    bus.subscribe(MailReceivedEvent, handler_b)

    await bus.emit(MailReceivedEvent())

    assert called == ["a", "b"]
    # handler_b should be unsubscribed for future emits
    assert handler_b not in bus._handlers["MailReceivedEvent"]
