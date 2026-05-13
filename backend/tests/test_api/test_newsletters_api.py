"""Tests for the Newsletters API endpoints.

Covers list with filters, detail, and delete.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _make_newsletter(*, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        mail_id=uuid4(),
        newsletter_name="Tech Weekly",
        sender_address="news@tech.com",
        unsubscribe_url="https://tech.com/unsub",
        frequency="weekly",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestListNewsletters:
    """GET /api/newsletters"""

    @pytest.mark.asyncio
    async def test_returns_paginated_response(self):
        from app.api.newsletters import list_newsletters

        nl = _make_newsletter()
        paginated = MagicMock(items=[nl], total=1, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.newsletters.paginate", new=AsyncMock(return_value=paginated)) as mock_paginate,
            patch("app.api.newsletters.build_paginated_response") as mock_build,
        ):
            mock_build.return_value = MagicMock()
            await list_newsletters(db=db, user_id=nl.user_id, page=1, per_page=20, sender=None, sort="newest")

        mock_paginate.assert_awaited_once()
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_sender_filter(self):
        from app.api.newsletters import list_newsletters

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.newsletters.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.newsletters.build_paginated_response", return_value=MagicMock()),
        ):
            await list_newsletters(db=db, user_id=uuid4(), page=1, per_page=20, sender="tech.com", sort="newest")

    @pytest.mark.asyncio
    async def test_sort_by_name(self):
        from app.api.newsletters import list_newsletters

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.newsletters.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.newsletters.build_paginated_response", return_value=MagicMock()),
        ):
            await list_newsletters(db=db, user_id=uuid4(), page=1, per_page=20, sender=None, sort="name")


class TestGetNewsletter:
    """GET /api/newsletters/{newsletter_id}"""

    @pytest.mark.asyncio
    async def test_returns_newsletter(self):
        from app.api.newsletters import get_newsletter

        nl = _make_newsletter()
        db = AsyncMock()

        with (
            patch("app.api.newsletters.get_or_404", new=AsyncMock(return_value=nl)),
            patch("app.api.newsletters.DetectedNewsletterResponse.model_validate", return_value=MagicMock()),
        ):
            await get_newsletter(newsletter_id=nl.id, db=db, user_id=nl.user_id)

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.newsletters import get_newsletter

        db = AsyncMock()

        with patch("app.api.newsletters.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await get_newsletter(newsletter_id=uuid4(), db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404


class TestDeleteNewsletter:
    """DELETE /api/newsletters/{newsletter_id}"""

    @pytest.mark.asyncio
    async def test_deletes_newsletter(self):
        from app.api.newsletters import delete_newsletter

        nl = _make_newsletter()
        db = AsyncMock()

        with patch("app.api.newsletters.get_or_404", new=AsyncMock(return_value=nl)):
            await delete_newsletter(newsletter_id=nl.id, db=db, user_id=nl.user_id)

        db.delete.assert_awaited_once_with(nl)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.newsletters import delete_newsletter

        db = AsyncMock()

        with patch("app.api.newsletters.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await delete_newsletter(newsletter_id=uuid4(), db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404
