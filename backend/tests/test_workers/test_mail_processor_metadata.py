"""Tests for _update_tracked_metadata and duplicate Message-ID detection.

Covers the inner ``_apply`` logic of ``_update_tracked_metadata`` (selective
field updates and first_seen back-fill) and the observability-only duplicate
detection query that fires after metadata update.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import structlog

from app.workers.mail_processor import _update_tracked_metadata

MODULE = "app.workers.mail_processor"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tracked(
    *,
    mail_uid: str = "100",
    current_folder: str = "INBOX",
    subject: str | None = None,
    sender: str | None = None,
    received_at: datetime | None = None,
    message_id: str | None = None,
    first_seen_uid: str | None = None,
    first_seen_folder: str | None = None,
) -> MagicMock:
    """Build a MagicMock TrackedEmail for unit testing."""
    t = MagicMock()
    t.id = uuid4()
    t.mail_uid = mail_uid
    t.current_folder = current_folder
    t.subject = subject
    t.sender = sender
    t.received_at = received_at
    t.message_id = message_id
    t.first_seen_uid = first_seen_uid
    t.first_seen_folder = first_seen_folder
    return t


def _capture_updater_and_call(tracked: MagicMock):
    """Patch ``_update_tracked_email`` to capture and invoke the updater callable."""

    async def _fake_update(_aid, _uid, _folder, _log, *, updater, **_kw):
        updater(tracked)

    return patch(f"{MODULE}._update_tracked_email", side_effect=_fake_update)


LOG = structlog.get_logger()
ACCOUNT_ID = str(uuid4())


# ---------------------------------------------------------------------------
# _update_tracked_metadata — selective field updates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metadata_sets_subject_when_provided() -> None:
    tracked = _make_tracked()
    with _capture_updater_and_call(tracked):
        await _update_tracked_metadata(
            ACCOUNT_ID, "100", "INBOX",
            subject="Hello", sender=None, received_at=None, log=LOG,
        )
    assert tracked.subject == "Hello"


@pytest.mark.asyncio
async def test_metadata_sets_all_fields_when_provided() -> None:
    now = datetime.now(UTC)
    tracked = _make_tracked()
    with _capture_updater_and_call(tracked):
        await _update_tracked_metadata(
            ACCOUNT_ID, "100", "INBOX",
            subject="Re: test", sender="alice@example.com",
            received_at=now, message_id="<abc@example.com>", log=LOG,
        )
    assert tracked.subject == "Re: test"
    assert tracked.sender == "alice@example.com"
    assert tracked.received_at is now
    assert tracked.message_id == "<abc@example.com>"


@pytest.mark.asyncio
async def test_metadata_skips_none_fields() -> None:
    tracked = _make_tracked(
        subject="Original", sender="bob@example.com",
        received_at=datetime(2025, 1, 1, tzinfo=UTC), message_id="<old@x>",
    )
    with _capture_updater_and_call(tracked):
        await _update_tracked_metadata(
            ACCOUNT_ID, "100", "INBOX",
            subject=None, sender=None, received_at=None, message_id=None, log=LOG,
        )
    assert tracked.subject == "Original"
    assert tracked.sender == "bob@example.com"
    assert tracked.received_at == datetime(2025, 1, 1, tzinfo=UTC)
    assert tracked.message_id == "<old@x>"


# ---------------------------------------------------------------------------
# _update_tracked_metadata — first_seen back-fill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_seen_uid_backfill_when_empty() -> None:
    tracked = _make_tracked(mail_uid="42", first_seen_uid=None)
    with _capture_updater_and_call(tracked):
        await _update_tracked_metadata(
            ACCOUNT_ID, "42", "INBOX",
            subject=None, sender=None, received_at=None, log=LOG,
        )
    assert tracked.first_seen_uid == "42"


@pytest.mark.asyncio
async def test_first_seen_uid_not_overwritten_when_set() -> None:
    tracked = _make_tracked(mail_uid="99", first_seen_uid="1")
    with _capture_updater_and_call(tracked):
        await _update_tracked_metadata(
            ACCOUNT_ID, "99", "INBOX",
            subject=None, sender=None, received_at=None, log=LOG,
        )
    assert tracked.first_seen_uid == "1"


@pytest.mark.asyncio
async def test_first_seen_folder_backfill_when_empty() -> None:
    tracked = _make_tracked(current_folder="Sent", first_seen_folder=None)
    with _capture_updater_and_call(tracked):
        await _update_tracked_metadata(
            ACCOUNT_ID, "100", "Sent",
            subject=None, sender=None, received_at=None, log=LOG,
        )
    assert tracked.first_seen_folder == "Sent"


@pytest.mark.asyncio
async def test_first_seen_folder_not_overwritten_when_set() -> None:
    tracked = _make_tracked(current_folder="Archive", first_seen_folder="INBOX")
    with _capture_updater_and_call(tracked):
        await _update_tracked_metadata(
            ACCOUNT_ID, "100", "Archive",
            subject=None, sender=None, received_at=None, log=LOG,
        )
    assert tracked.first_seen_folder == "INBOX"
