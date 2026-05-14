"""Tests for the Email Summaries API endpoints.

Covers list with filters (urgency, action_required, search, sort),
detail, and delete.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _make_summary(*, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        mail_id=uuid4(),
        summary="Important meeting notes",
        urgency="high",
        action_required=True,
        category="work",
        sentiment="neutral",
        key_points=["deadline Friday"],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestListSummaries:
    """GET /api/summaries"""

    @pytest.mark.asyncio
    async def test_returns_paginated_response(self):
        from app.api.summaries import list_summaries

        summary = _make_summary()
        paginated = MagicMock(items=[summary], total=1, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.summaries.paginate", new=AsyncMock(return_value=paginated)) as mock_paginate,
            patch("app.api.summaries.build_paginated_response") as mock_build,
        ):
            mock_build.return_value = MagicMock()
            await list_summaries(
                db=db,
                user_id=summary.user_id,
                page=1,
                per_page=20,
                urgency=None,
                action_required=None,
                search=None,
                sort="newest",
            )

        mock_paginate.assert_awaited_once()
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_urgency_filter(self):
        from app.api.summaries import list_summaries

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.summaries.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.summaries.build_paginated_response", return_value=MagicMock()),
        ):
            await list_summaries(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                urgency="high",
                action_required=None,
                search=None,
                sort="newest",
            )

    @pytest.mark.asyncio
    async def test_action_required_filter(self):
        from app.api.summaries import list_summaries

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.summaries.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.summaries.build_paginated_response", return_value=MagicMock()),
        ):
            await list_summaries(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                urgency=None,
                action_required=True,
                search=None,
                sort="newest",
            )

    @pytest.mark.asyncio
    async def test_search_filter(self):
        from app.api.summaries import list_summaries

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.summaries.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.summaries.build_paginated_response", return_value=MagicMock()),
        ):
            await list_summaries(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                urgency=None,
                action_required=None,
                search="invoice",
                sort="newest",
            )

    @pytest.mark.asyncio
    async def test_sort_oldest(self):
        from app.api.summaries import list_summaries

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.summaries.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.summaries.build_paginated_response", return_value=MagicMock()),
        ):
            await list_summaries(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                urgency=None,
                action_required=None,
                search=None,
                sort="oldest",
            )


class TestGetSummary:
    """GET /api/summaries/{summary_id}"""

    @pytest.mark.asyncio
    async def test_returns_summary(self):
        from app.api.summaries import get_summary

        summary = _make_summary()
        db = AsyncMock()

        with (
            patch("app.api.summaries.get_or_404", new=AsyncMock(return_value=summary)),
            patch("app.api.summaries.EmailSummaryResponse.model_validate", return_value=MagicMock()),
        ):
            await get_summary(summary_id=summary.id, db=db, user_id=summary.user_id)

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.summaries import get_summary

        db = AsyncMock()

        with patch("app.api.summaries.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await get_summary(summary_id=uuid4(), db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404


class TestDeleteSummary:
    """DELETE /api/summaries/{summary_id}"""

    @pytest.mark.asyncio
    async def test_deletes_summary(self):
        from app.api.summaries import delete_summary

        summary = _make_summary()
        db = AsyncMock()

        with patch("app.api.summaries.get_or_404", new=AsyncMock(return_value=summary)):
            await delete_summary(summary_id=summary.id, db=db, user_id=summary.user_id)

        db.delete.assert_awaited_once_with(summary)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_not_found_raises_404(self):
        from app.api.summaries import delete_summary

        db = AsyncMock()

        with patch("app.api.summaries.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await delete_summary(summary_id=uuid4(), db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404
