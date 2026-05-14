"""Tests for the Applied Labels API endpoints.

Covers list with filters, label summary, and delete.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _make_label(*, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        mail_id=uuid4(),
        label="important",
        confidence=0.95,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestListAppliedLabels:
    """GET /api/labels"""

    @pytest.mark.asyncio
    async def test_returns_paginated_response(self):
        from app.api.labels import list_applied_labels

        label = _make_label()
        paginated = MagicMock(items=[label], total=1, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.labels.paginate", new=AsyncMock(return_value=paginated)) as mock_paginate,
            patch("app.api.labels.build_paginated_response") as mock_build,
        ):
            mock_build.return_value = MagicMock()
            await list_applied_labels(db=db, user_id=label.user_id, page=1, per_page=20, label=None, sort="newest")

        mock_paginate.assert_awaited_once()
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_label_filter(self):
        from app.api.labels import list_applied_labels

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.labels.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.labels.build_paginated_response", return_value=MagicMock()),
        ):
            await list_applied_labels(db=db, user_id=uuid4(), page=1, per_page=20, label="urgent", sort="newest")

    @pytest.mark.asyncio
    async def test_sort_by_label(self):
        from app.api.labels import list_applied_labels

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.labels.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.labels.build_paginated_response", return_value=MagicMock()),
        ):
            await list_applied_labels(db=db, user_id=uuid4(), page=1, per_page=20, label=None, sort="label")


class TestGetLabelSummary:
    """GET /api/labels/summary"""

    @pytest.mark.asyncio
    async def test_returns_summary(self):
        from app.api.labels import get_label_summary

        db = AsyncMock()
        row = SimpleNamespace(label="important", count=5)
        result = MagicMock()
        result.all.return_value = [row]
        db.execute.return_value = result

        resp = await get_label_summary(db=db, user_id=uuid4())
        assert resp.total == 1
        assert resp.items[0].label == "important"
        assert resp.items[0].count == 5

    @pytest.mark.asyncio
    async def test_empty_summary(self):
        from app.api.labels import get_label_summary

        db = AsyncMock()
        result = MagicMock()
        result.all.return_value = []
        db.execute.return_value = result

        resp = await get_label_summary(db=db, user_id=uuid4())
        assert resp.total == 0
        assert resp.items == []


class TestDeleteAppliedLabel:
    """DELETE /api/labels/{label_id}"""

    @pytest.mark.asyncio
    async def test_deletes_label(self):
        from app.api.labels import delete_applied_label

        label = _make_label()
        db = AsyncMock()

        with patch("app.api.labels.get_or_404", new=AsyncMock(return_value=label)):
            await delete_applied_label(label_id=label.id, db=db, user_id=label.user_id)

        db.delete.assert_awaited_once_with(label)
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.labels import delete_applied_label

        db = AsyncMock()

        with patch("app.api.labels.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await delete_applied_label(label_id=uuid4(), db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404
