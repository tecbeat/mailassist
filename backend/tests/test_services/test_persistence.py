"""Tests for the persistence service.

Verifies SQL statement construction (upsert vs delete+insert), truncation
helpers, no-op conditions, date parsing, and the _persist context manager.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers: _trunc, _trunc_required, parse_date_field
# ---------------------------------------------------------------------------


class TestTrunc:
    def test_trunc_none_returns_none(self) -> None:
        from app.services.persistence import _trunc

        assert _trunc(None, 100) is None

    def test_trunc_empty_string_returns_none(self) -> None:
        from app.services.persistence import _trunc

        assert _trunc("", 100) is None

    def test_trunc_short_string_unchanged(self) -> None:
        from app.services.persistence import _trunc

        assert _trunc("hello", 100) == "hello"

    def test_trunc_long_string_truncated(self) -> None:
        from app.services.persistence import _trunc

        assert _trunc("abcdef", 3) == "abc"


class TestTruncRequired:
    def test_trunc_required_short_unchanged(self) -> None:
        from app.services.persistence import _trunc_required

        assert _trunc_required("hi", 10) == "hi"

    def test_trunc_required_long_truncated(self) -> None:
        from app.services.persistence import _trunc_required

        assert _trunc_required("abcdef", 4) == "abcd"


class TestParseDateField:
    def test_parse_datetime_passthrough(self) -> None:
        from app.services.persistence import parse_date_field

        dt = datetime(2025, 1, 1, tzinfo=UTC)
        assert parse_date_field(dt) is dt

    def test_parse_iso_string(self) -> None:
        from app.services.persistence import parse_date_field

        result = parse_date_field("2025-06-15T10:30:00+00:00")
        assert isinstance(result, datetime)
        assert result.year == 2025
        assert result.month == 6

    def test_parse_rfc2822_string(self) -> None:
        from app.services.persistence import parse_date_field

        result = parse_date_field("Mon, 15 Jun 2025 10:30:00 +0000")
        assert isinstance(result, datetime)
        assert result.year == 2025

    def test_parse_invalid_returns_none(self) -> None:
        from app.services.persistence import parse_date_field

        assert parse_date_field("not-a-date") is None

    def test_parse_empty_string_returns_none(self) -> None:
        from app.services.persistence import parse_date_field

        assert parse_date_field("") is None


# ---------------------------------------------------------------------------
# Helpers: _persist context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_raises_without_session_or_db() -> None:
    from app.services.persistence import _persist

    with pytest.raises(ValueError, match="Either own_session=True or db must be provided"):
        async with _persist(own_session=False, db=None):
            pass


@pytest.mark.asyncio
async def test_persist_with_db_flushes() -> None:
    from app.services.persistence import _persist

    mock_db = AsyncMock()
    async with _persist(own_session=False, db=mock_db) as session:
        assert session is mock_db
    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_persist_with_own_session_uses_context() -> None:
    from app.services.persistence import _persist

    mock_session = AsyncMock()

    async def _fake_ctx():
        yield mock_session

    from contextlib import asynccontextmanager

    fake_ctx = asynccontextmanager(_fake_ctx)

    with patch("app.services.persistence.get_session_ctx", return_value=fake_ctx()):
        async with _persist(own_session=True, db=None) as session:
            assert session is mock_session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_db() -> AsyncMock:
    """Async mock session that tracks execute and add calls."""
    db = AsyncMock()
    result_mock = MagicMock()
    row_mock = MagicMock()
    row_mock.id = uuid4()
    result_mock.fetchone.return_value = row_mock
    db.execute.return_value = result_mock
    return db


# ---------------------------------------------------------------------------
# save_email_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_email_summary_executes_upsert(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_email_summary

    await save_email_summary(
        user_id=uuid4(),
        summary="Test summary",
        key_points=["point1"],
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_awaited_once()
    mock_db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_email_summary_passes_mail_id(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_email_summary

    mail_id = uuid4()

    with patch("app.services.persistence.pg_insert") as mock_insert:
        mock_stmt = MagicMock()
        mock_insert.return_value.values.return_value.on_conflict_do_update.return_value = mock_stmt

        await save_email_summary(
            user_id=uuid4(),
            summary="s",
            key_points=[],
            mail_id=mail_id,
            db=mock_db,
        )

        call_kwargs = mock_insert.return_value.values.call_args
        assert call_kwargs.kwargs["mail_id"] == mail_id


# ---------------------------------------------------------------------------
# save_newsletter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_newsletter_noop_when_not_newsletter(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_newsletter

    await save_newsletter(
        user_id=uuid4(),
        is_newsletter=False,
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_newsletter_executes_upsert(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_newsletter

    await save_newsletter(
        user_id=uuid4(),
        is_newsletter=True,
        newsletter_name="Tech Weekly",
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_newsletter_truncates_sender_address(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_newsletter

    long_address = "a" * 500

    with patch("app.services.persistence.pg_insert") as mock_insert:
        mock_stmt = MagicMock()
        mock_insert.return_value.values.return_value.on_conflict_do_update.return_value = mock_stmt

        await save_newsletter(
            user_id=uuid4(),
            is_newsletter=True,
            sender_address=long_address,
            mail_id=uuid4(),
            db=mock_db,
        )

        call_kwargs = mock_insert.return_value.values.call_args.kwargs
        assert len(call_kwargs["sender_address"]) == 320


# ---------------------------------------------------------------------------
# save_coupons (delete + re-insert)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_coupons_noop_when_no_coupons(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_coupons

    await save_coupons(
        user_id=uuid4(),
        has_coupons=False,
        coupons=[],
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_coupons_noop_when_empty_list(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_coupons

    await save_coupons(
        user_id=uuid4(),
        has_coupons=True,
        coupons=[],
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_coupons_deletes_then_inserts(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_coupons

    await save_coupons(
        user_id=uuid4(),
        has_coupons=True,
        coupons=[{"code": "SAVE10", "store": "TestStore"}],
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_awaited_once()  # the DELETE
    mock_db.add.assert_called_once()


@pytest.mark.asyncio
async def test_save_coupons_multiple_records(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_coupons

    coupons = [
        {"code": "A", "store": "S1"},
        {"code": "B", "store": "S2"},
        {"code": "C", "store": "S3"},
    ]

    await save_coupons(
        user_id=uuid4(),
        has_coupons=True,
        coupons=coupons,
        mail_id=uuid4(),
        db=mock_db,
    )

    assert mock_db.add.call_count == 3


# ---------------------------------------------------------------------------
# save_applied_labels (delete + re-insert)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_applied_labels_noop_when_empty(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_applied_labels

    await save_applied_labels(
        user_id=uuid4(),
        labels=[],
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_applied_labels_deletes_then_inserts(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_applied_labels

    await save_applied_labels(
        user_id=uuid4(),
        labels=["Important", "Urgent"],
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_awaited_once()  # DELETE
    assert mock_db.add.call_count == 2


@pytest.mark.asyncio
async def test_save_applied_labels_marks_existing(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_applied_labels

    await save_applied_labels(
        user_id=uuid4(),
        labels=["Existing", "NewLabel"],
        existing_labels={"existing"},
        mail_id=uuid4(),
        db=mock_db,
    )

    records = [call[0][0] for call in mock_db.add.call_args_list]
    existing_record = next(r for r in records if r.label == "Existing")
    new_record = next(r for r in records if r.label == "NewLabel")
    assert existing_record.is_new_label is False
    assert new_record.is_new_label is True


# ---------------------------------------------------------------------------
# save_assigned_folder (upsert)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_assigned_folder_executes_upsert(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_assigned_folder

    await save_assigned_folder(
        user_id=uuid4(),
        folder="INBOX/Important",
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_assigned_folder_marks_new_folder(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_assigned_folder

    with patch("app.services.persistence.pg_insert") as mock_insert:
        mock_stmt = MagicMock()
        mock_insert.return_value.values.return_value.on_conflict_do_update.return_value = mock_stmt

        await save_assigned_folder(
            user_id=uuid4(),
            folder="NewFolder",
            existing_folders={"OldFolder"},
            mail_id=uuid4(),
            db=mock_db,
        )

        call_kwargs = mock_insert.return_value.values.call_args.kwargs
        assert call_kwargs["is_new_folder"] is True


@pytest.mark.asyncio
async def test_save_assigned_folder_existing_not_new(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_assigned_folder

    with patch("app.services.persistence.pg_insert") as mock_insert:
        mock_stmt = MagicMock()
        mock_insert.return_value.values.return_value.on_conflict_do_update.return_value = mock_stmt

        await save_assigned_folder(
            user_id=uuid4(),
            folder="Existing",
            existing_folders={"existing"},
            mail_id=uuid4(),
            db=mock_db,
        )

        call_kwargs = mock_insert.return_value.values.call_args.kwargs
        assert call_kwargs["is_new_folder"] is False


# ---------------------------------------------------------------------------
# save_auto_reply (upsert)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_auto_reply_noop_when_should_not_reply(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_auto_reply

    await save_auto_reply(
        user_id=uuid4(),
        should_reply=False,
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_auto_reply_noop_when_no_draft(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_auto_reply

    await save_auto_reply(
        user_id=uuid4(),
        should_reply=True,
        draft_body=None,
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_auto_reply_executes_upsert(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_auto_reply

    await save_auto_reply(
        user_id=uuid4(),
        should_reply=True,
        draft_body="Thanks for your email.",
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# save_contact_assignment (upsert)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_contact_assignment_executes_upsert(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_contact_assignment

    await save_contact_assignment(
        user_id=uuid4(),
        contact_name="John Doe",
        confidence=0.95,
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_contact_assignment_auto_writeback(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_contact_assignment

    contact_id = str(uuid4())

    with patch("app.services.contacts.writeback.auto_add_sender_email", new_callable=AsyncMock) as mock_wb:
        await save_contact_assignment(
            user_id=uuid4(),
            contact_id=contact_id,
            contact_name="John",
            confidence=0.9,
            sender_email="john@example.com",
            auto_writeback=True,
            is_new_contact_suggestion=False,
            mail_id=uuid4(),
            db=mock_db,
        )

        mock_wb.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_contact_assignment_no_writeback_for_new_contact(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_contact_assignment

    contact_id = str(uuid4())

    with patch("app.services.contacts.writeback.auto_add_sender_email", new_callable=AsyncMock) as mock_wb:
        await save_contact_assignment(
            user_id=uuid4(),
            contact_id=contact_id,
            contact_name="John",
            confidence=0.9,
            sender_email="john@example.com",
            auto_writeback=True,
            is_new_contact_suggestion=True,
            mail_id=uuid4(),
            db=mock_db,
        )

        mock_wb.assert_not_awaited()


# ---------------------------------------------------------------------------
# save_spam_detection (upsert)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_spam_detection_executes_upsert(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_spam_detection

    await save_spam_detection(
        user_id=uuid4(),
        is_spam=True,
        confidence=0.99,
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_spam_detection_truncates_reason(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_spam_detection

    with patch("app.services.persistence.pg_insert") as mock_insert:
        mock_stmt = MagicMock()
        mock_insert.return_value.values.return_value.on_conflict_do_update.return_value = mock_stmt

        await save_spam_detection(
            user_id=uuid4(),
            is_spam=False,
            confidence=0.1,
            reason="r" * 600,
            mail_id=uuid4(),
            db=mock_db,
        )

        call_kwargs = mock_insert.return_value.values.call_args.kwargs
        assert len(call_kwargs["reason"]) == 500


# ---------------------------------------------------------------------------
# save_otp (delete + re-insert)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_otp_noop_when_no_codes(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_otp

    await save_otp(
        user_id=uuid4(),
        has_codes=False,
        codes=[],
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_otp_noop_when_empty_codes(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_otp

    await save_otp(
        user_id=uuid4(),
        has_codes=True,
        codes=[],
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_otp_deletes_then_inserts(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_otp

    await save_otp(
        user_id=uuid4(),
        has_codes=True,
        codes=[{"code": "123456", "service": "GitHub", "code_type": "totp"}],
        mail_id=uuid4(),
        db=mock_db,
    )

    mock_db.execute.assert_awaited_once()  # DELETE
    mock_db.add.assert_called_once()


@pytest.mark.asyncio
async def test_save_otp_computes_expires_at(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_otp

    await save_otp(
        user_id=uuid4(),
        has_codes=True,
        codes=[{"code": "999", "expires_in_minutes": 10}],
        mail_id=uuid4(),
        db=mock_db,
    )

    added_record = mock_db.add.call_args[0][0]
    assert added_record.expires_at is not None


@pytest.mark.asyncio
async def test_save_otp_caps_expires_at_1440(mock_db: AsyncMock) -> None:
    from app.services.persistence import save_otp

    await save_otp(
        user_id=uuid4(),
        has_codes=True,
        codes=[{"code": "999", "expires_in_minutes": 99999}],
        mail_id=uuid4(),
        db=mock_db,
    )

    added_record = mock_db.add.call_args[0][0]
    assert added_record.expires_at is not None
    diff = added_record.expires_at - datetime.now(UTC)
    assert diff <= timedelta(minutes=1441)
