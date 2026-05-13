"""Tests for the Coupons API endpoints.

Covers list with filters (store, active_only, sort), detail, update, and delete.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _make_coupon(*, user_id=None, is_used=False):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        mail_id=uuid4(),
        store="Amazon",
        code="SAVE20",
        discount="20%",
        description="20% off electronics",
        expires_at=datetime(2026, 12, 31, tzinfo=UTC),
        is_used=is_used,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestListCoupons:
    """GET /api/coupons"""

    @pytest.mark.asyncio
    async def test_returns_paginated_response(self):
        from app.api.coupons import list_coupons

        coupon = _make_coupon()
        paginated = MagicMock(items=[coupon], total=1, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.coupons.paginate", new=AsyncMock(return_value=paginated)) as mock_paginate,
            patch("app.api.coupons.build_paginated_response") as mock_build,
        ):
            mock_build.return_value = MagicMock()
            await list_coupons(
                db=db,
                user_id=coupon.user_id,
                page=1,
                per_page=20,
                store=None,
                active_only=False,
                sort="newest",
            )

        mock_paginate.assert_awaited_once()
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_filter(self):
        from app.api.coupons import list_coupons

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.coupons.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.coupons.build_paginated_response", return_value=MagicMock()),
        ):
            await list_coupons(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                store="Amazon",
                active_only=False,
                sort="newest",
            )

    @pytest.mark.asyncio
    async def test_active_only_filter(self):
        from app.api.coupons import list_coupons

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.coupons.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.coupons.build_paginated_response", return_value=MagicMock()),
        ):
            await list_coupons(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                store=None,
                active_only=True,
                sort="newest",
            )

    @pytest.mark.asyncio
    async def test_sort_by_expiry(self):
        from app.api.coupons import list_coupons

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.coupons.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.coupons.build_paginated_response", return_value=MagicMock()),
        ):
            await list_coupons(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                store=None,
                active_only=False,
                sort="expiry",
            )

    @pytest.mark.asyncio
    async def test_sort_by_store(self):
        from app.api.coupons import list_coupons

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.coupons.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.coupons.build_paginated_response", return_value=MagicMock()),
        ):
            await list_coupons(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                store=None,
                active_only=False,
                sort="store",
            )


class TestGetCoupon:
    """GET /api/coupons/{coupon_id}"""

    @pytest.mark.asyncio
    async def test_returns_coupon(self):
        from app.api.coupons import get_coupon

        coupon = _make_coupon()
        db = AsyncMock()

        with (
            patch("app.api.coupons.get_or_404", new=AsyncMock(return_value=coupon)),
            patch("app.api.coupons.ExtractedCouponResponse.model_validate", return_value=MagicMock()),
        ):
            await get_coupon(coupon_id=coupon.id, db=db, user_id=coupon.user_id)

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.coupons import get_coupon

        db = AsyncMock()

        with patch("app.api.coupons.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await get_coupon(coupon_id=uuid4(), db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404


class TestUpdateCoupon:
    """PATCH /api/coupons/{coupon_id}"""

    @pytest.mark.asyncio
    async def test_marks_coupon_as_used(self):
        from app.api.coupons import update_coupon
        from app.schemas.coupon import CouponUpdate

        coupon = _make_coupon(is_used=False)
        db = AsyncMock()
        data = CouponUpdate(is_used=True)

        with (
            patch("app.api.coupons.get_or_404", new=AsyncMock(return_value=coupon)),
            patch("app.api.coupons.ExtractedCouponResponse.model_validate", return_value=MagicMock()),
        ):
            await update_coupon(coupon_id=coupon.id, data=data, db=db, user_id=coupon.user_id)

        assert coupon.is_used is True
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_not_found_raises_404(self):
        from app.api.coupons import update_coupon
        from app.schemas.coupon import CouponUpdate

        db = AsyncMock()
        data = CouponUpdate(is_used=True)

        with patch("app.api.coupons.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await update_coupon(coupon_id=uuid4(), data=data, db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404


class TestDeleteCoupon:
    """DELETE /api/coupons/{coupon_id}"""

    @pytest.mark.asyncio
    async def test_deletes_coupon(self):
        from app.api.coupons import delete_coupon

        coupon = _make_coupon()
        db = AsyncMock()

        with patch("app.api.coupons.get_or_404", new=AsyncMock(return_value=coupon)):
            await delete_coupon(coupon_id=coupon.id, db=db, user_id=coupon.user_id)

        db.delete.assert_awaited_once_with(coupon)
        db.flush.assert_awaited_once()
