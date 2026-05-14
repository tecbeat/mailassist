"""Tests for the Auto-Replies API endpoints.

Covers list with filters, detail, update, and delete.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _make_auto_reply(*, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        mail_id=uuid4(),
        draft_body="Thank you for your email.",
        status="draft",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestListAutoReplies:
    """GET /api/auto-replies"""

    @pytest.mark.asyncio
    async def test_returns_paginated_response(self):
        from app.api.auto_replies import list_auto_replies

        reply = _make_auto_reply()
        paginated = MagicMock(items=[reply], total=1, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.auto_replies.paginate", new=AsyncMock(return_value=paginated)) as mock_paginate,
            patch("app.api.auto_replies.build_paginated_response") as mock_build,
        ):
            mock_build.return_value = MagicMock()
            await list_auto_replies(db=db, user_id=reply.user_id, page=1, per_page=20, search=None, sort="newest")

        mock_paginate.assert_awaited_once()
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_filter(self):
        from app.api.auto_replies import list_auto_replies

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.auto_replies.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.auto_replies.build_paginated_response", return_value=MagicMock()),
        ):
            await list_auto_replies(db=db, user_id=uuid4(), page=1, per_page=20, search="invoice", sort="newest")

    @pytest.mark.asyncio
    async def test_sort_oldest(self):
        from app.api.auto_replies import list_auto_replies

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.auto_replies.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.auto_replies.build_paginated_response", return_value=MagicMock()),
        ):
            await list_auto_replies(db=db, user_id=uuid4(), page=1, per_page=20, search=None, sort="oldest")


class TestGetAutoReply:
    """GET /api/auto-replies/{reply_id}"""

    @pytest.mark.asyncio
    async def test_returns_auto_reply(self):
        from app.api.auto_replies import get_auto_reply

        reply = _make_auto_reply()
        db = AsyncMock()

        with (
            patch("app.api.auto_replies.get_or_404", new=AsyncMock(return_value=reply)),
            patch("app.api.auto_replies.AutoReplyRecordResponse.model_validate", return_value=MagicMock()),
        ):
            await get_auto_reply(reply_id=reply.id, db=db, user_id=reply.user_id)

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.auto_replies import get_auto_reply

        db = AsyncMock()

        with patch("app.api.auto_replies.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await get_auto_reply(reply_id=uuid4(), db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404


class TestUpdateAutoReply:
    """PATCH /api/auto-replies/{reply_id}"""

    @pytest.mark.asyncio
    async def test_updates_auto_reply(self):
        from app.api.auto_replies import update_auto_reply
        from app.schemas.auto_reply import AutoReplyRecordUpdate

        reply = _make_auto_reply()
        db = AsyncMock()
        data = AutoReplyRecordUpdate(draft_body="Updated reply body")

        with (
            patch("app.api.auto_replies.get_or_404", new=AsyncMock(return_value=reply)),
            patch("app.api.auto_replies.AutoReplyRecordResponse.model_validate", return_value=MagicMock()),
        ):
            await update_auto_reply(reply_id=reply.id, data=data, db=db, user_id=reply.user_id)

        assert reply.draft_body == "Updated reply body"
        db.flush.assert_awaited_once()


class TestDeleteAutoReply:
    """DELETE /api/auto-replies/{reply_id}"""

    @pytest.mark.asyncio
    async def test_deletes_auto_reply(self):
        from app.api.auto_replies import delete_auto_reply

        reply = _make_auto_reply()
        db = AsyncMock()

        with patch("app.api.auto_replies.get_or_404", new=AsyncMock(return_value=reply)):
            await delete_auto_reply(reply_id=reply.id, db=db, user_id=reply.user_id)

        db.delete.assert_awaited_once_with(reply)
        db.flush.assert_awaited_once()
