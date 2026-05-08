"""Regression tests for the AIProcessingCompleteEvent emission order.

Issue #157: when the AI pipeline persists plugin data (e.g. EmailSummary,
ExtractedOtpCode) using the pre-move ``mail_uid`` and Phase 4 then performs
an IMAP MOVE, the new COPYUID is written back to ``tracked_email.mail_uid``
while plugin rows still hold the old UID.  If the completion event is
emitted *after* Phase 4, the notification handler looks up plugin context
with the new UID and finds nothing, sending an empty notification.

The fix moves the event emission to *before* Phase 4 so the event carries
the pre-move UID — matching the UID under which plugin rows were saved.

These tests assert that contract structurally so an accidental move back
to the old (broken) order is caught.
"""

from __future__ import annotations

import inspect

import app.workers.mail_processor as mail_processor


def _source_lines() -> list[str]:
    """Return the source lines of ``_process_mail_inner`` for inspection."""
    src = inspect.getsource(mail_processor._process_mail_inner)
    return src.splitlines()


def test_event_emit_appears_before_phase_4_imap_actions() -> None:
    """The AIProcessingCompleteEvent must be emitted before Phase 4.

    Phase 4 may rewrite ``mail_uid`` after an IMAP MOVE; emitting the
    event before Phase 4 keeps the event's UID consistent with plugin
    table rows persisted in Phase 3.
    """
    lines = _source_lines()

    emit_index = next(
        (i for i, line in enumerate(lines) if "AIProcessingCompleteEvent(" in line),
        None,
    )
    phase4_index = next(
        (i for i, line in enumerate(lines) if "Phase 4: IMAP actions" in line),
        None,
    )

    assert emit_index is not None, "AIProcessingCompleteEvent emission not found in _process_mail_inner"
    assert phase4_index is not None, "Phase 4 marker not found in _process_mail_inner"
    assert emit_index < phase4_index, (
        "AIProcessingCompleteEvent must be emitted BEFORE Phase 4 IMAP actions "
        f"(emit at line {emit_index}, Phase 4 at line {phase4_index}). "
        "See issue #157 — plugin notification context goes empty otherwise."
    )


def test_event_emitted_exactly_once() -> None:
    """Guard against an accidental duplicate emission left over from refactors."""
    lines = _source_lines()
    emit_count = sum(1 for line in lines if "AIProcessingCompleteEvent(" in line)
    assert emit_count == 1, (
        f"AIProcessingCompleteEvent should be emitted exactly once in "
        f"_process_mail_inner, found {emit_count} occurrences."
    )
