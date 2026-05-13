"""Tests for the Spam API endpoints.

Covers report spam, report contact spam, blocklist CRUD.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.spam import BlocklistEntryType, BlocklistSource


def _make_blocklist_entry(*, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        entry_type=BlocklistEntryType.EMAIL,
        value="spam@example.com",
        source=BlocklistSource.MANUAL,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestReportSpam:
    """POST /api/spam/report"""

    @pytest.mark.asyncio
    async def test_reports_spam_successfully(self):
        from app.api.spam import report_spam
        from app.schemas.spam import SpamReportRequest

        db = AsyncMock()
        uid = uuid4()
        data = SpamReportRequest(
            mail_account_id=uuid4(),
            mail_uid="uid-1",
            sender_email="spam@example.com",
            subject="Buy now",
        )

        with patch(
            "app.api.spam.report_as_spam",
            new=AsyncMock(
                return_value={
                    "blocked_entries_created": 2,
                    "mail_moved": True,
                    "message": "Reported as spam",
                }
            ),
        ):
            result = await report_spam(data=data, db=db, user_id=uid)

        assert result.mail_moved is True


class TestReportContactSpam:
    """POST /api/spam/report-contact"""

    @pytest.mark.asyncio
    async def test_reports_contact_as_spam(self):
        from app.api.spam import report_contact_spam
        from app.schemas.spam import SpamReportContactRequest

        db = AsyncMock()
        uid = uuid4()
        data = SpamReportContactRequest(contact_id=uuid4())

        with patch(
            "app.api.spam.report_contact_as_spam",
            new=AsyncMock(
                return_value={
                    "blocked_entries_created": 1,
                    "mail_moved": False,
                    "message": "Contact blocked",
                }
            ),
        ):
            result = await report_contact_spam(data=data, db=db, user_id=uid)

        assert result.mail_moved is False


class TestListBlocklist:
    """GET /api/spam/blocklist"""

    @pytest.mark.asyncio
    async def test_returns_paginated_response(self):
        from app.api.spam import list_blocklist

        entry = _make_blocklist_entry()
        paginated = MagicMock(items=[entry], total=1, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.spam.paginate", new=AsyncMock(return_value=paginated)) as mock_paginate,
            patch("app.api.spam.build_paginated_response") as mock_build,
        ):
            mock_build.return_value = MagicMock()
            await list_blocklist(db=db, user_id=entry.user_id, search=None, entry_type=None, page=1, per_page=20)

        mock_paginate.assert_awaited_once()
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_filter(self):
        from app.api.spam import list_blocklist

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.spam.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.spam.build_paginated_response", return_value=MagicMock()),
        ):
            await list_blocklist(db=db, user_id=uuid4(), search="spam", entry_type=None, page=1, per_page=20)

    @pytest.mark.asyncio
    async def test_entry_type_filter(self):
        from app.api.spam import list_blocklist

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.spam.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.spam.build_paginated_response", return_value=MagicMock()),
        ):
            await list_blocklist(
                db=db,
                user_id=uuid4(),
                search=None,
                entry_type=BlocklistEntryType.DOMAIN,
                page=1,
                per_page=20,
            )


class TestCreateBlocklistEntry:
    """POST /api/spam/blocklist"""

    @pytest.mark.asyncio
    async def test_creates_entry(self):
        from app.api.spam import create_blocklist_entry
        from app.schemas.spam import BlocklistEntryCreate

        db = AsyncMock()
        uid = uuid4()
        data = BlocklistEntryCreate(entry_type="email", value="bad@example.com")

        # No existing duplicate
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute.return_value = result_mock

        with patch("app.api.spam.BlocklistEntryResponse.model_validate", return_value=MagicMock()):
            await create_blocklist_entry(data=data, db=db, user_id=uid)

        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_raises_409(self):
        from app.api.spam import create_blocklist_entry
        from app.schemas.spam import BlocklistEntryCreate

        db = AsyncMock()
        uid = uuid4()
        data = BlocklistEntryCreate(entry_type="email", value="bad@example.com")

        existing = _make_blocklist_entry(user_id=uid)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = existing
        db.execute.return_value = result_mock

        with pytest.raises(HTTPException) as exc_info:
            await create_blocklist_entry(data=data, db=db, user_id=uid)

        assert exc_info.value.status_code == 409


class TestDeleteBlocklistEntry:
    """DELETE /api/spam/blocklist/{entry_id}"""

    @pytest.mark.asyncio
    async def test_deletes_entry(self):
        from app.api.spam import delete_blocklist_entry

        entry = _make_blocklist_entry()
        db = AsyncMock()

        with patch("app.api.spam.get_or_404", new=AsyncMock(return_value=entry)):
            await delete_blocklist_entry(entry_id=entry.id, db=db, user_id=entry.user_id)

        db.delete.assert_awaited_once_with(entry)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.spam import delete_blocklist_entry

        db = AsyncMock()

        with patch("app.api.spam.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await delete_blocklist_entry(entry_id=uuid4(), db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404
