"""Tests for the OTP Codes API endpoints.

Covers list with filters (service, code_type, active_only, sort), detail, and delete.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _make_otp(*, user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        mail_id=uuid4(),
        code="123456",
        service="GitHub",
        code_type="totp",
        is_expired=False,
        expires_at=datetime(2026, 6, 1, tzinfo=UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestListOtpCodes:
    """GET /api/otp-codes"""

    @pytest.mark.asyncio
    async def test_returns_paginated_response(self):
        from app.api.otp import list_otp_codes

        otp = _make_otp()
        paginated = MagicMock(items=[otp], total=1, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.otp.paginate", new=AsyncMock(return_value=paginated)) as mock_paginate,
            patch("app.api.otp.build_paginated_response") as mock_build,
        ):
            mock_build.return_value = MagicMock()
            await list_otp_codes(
                db=db,
                user_id=otp.user_id,
                page=1,
                per_page=20,
                service=None,
                code_type=None,
                active_only=False,
                sort="newest",
            )

        mock_paginate.assert_awaited_once()
        mock_build.assert_called_once()

    @pytest.mark.asyncio
    async def test_service_filter(self):
        from app.api.otp import list_otp_codes

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.otp.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.otp.build_paginated_response", return_value=MagicMock()),
        ):
            await list_otp_codes(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                service="GitHub",
                code_type=None,
                active_only=False,
                sort="newest",
            )

    @pytest.mark.asyncio
    async def test_code_type_filter(self):
        from app.api.otp import list_otp_codes

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.otp.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.otp.build_paginated_response", return_value=MagicMock()),
        ):
            await list_otp_codes(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                service=None,
                code_type="totp",
                active_only=False,
                sort="newest",
            )

    @pytest.mark.asyncio
    async def test_active_only_filter(self):
        from app.api.otp import list_otp_codes

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.otp.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.otp.build_paginated_response", return_value=MagicMock()),
        ):
            await list_otp_codes(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                service=None,
                code_type=None,
                active_only=True,
                sort="newest",
            )

    @pytest.mark.asyncio
    async def test_sort_by_expiry(self):
        from app.api.otp import list_otp_codes

        paginated = MagicMock(items=[], total=0, page=1, per_page=20, pages=1)
        db = AsyncMock()

        with (
            patch("app.api.otp.paginate", new=AsyncMock(return_value=paginated)),
            patch("app.api.otp.build_paginated_response", return_value=MagicMock()),
        ):
            await list_otp_codes(
                db=db,
                user_id=uuid4(),
                page=1,
                per_page=20,
                service=None,
                code_type=None,
                active_only=False,
                sort="expiry",
            )


class TestGetOtpCode:
    """GET /api/otp-codes/{otp_id}"""

    @pytest.mark.asyncio
    async def test_returns_otp(self):
        from app.api.otp import get_otp_code

        otp = _make_otp()
        db = AsyncMock()

        with (
            patch("app.api.otp.get_or_404", new=AsyncMock(return_value=otp)),
            patch("app.api.otp.ExtractedOtpCodeResponse.model_validate", return_value=MagicMock()),
        ):
            await get_otp_code(otp_id=otp.id, db=db, user_id=otp.user_id)

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.otp import get_otp_code

        db = AsyncMock()

        with patch("app.api.otp.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await get_otp_code(otp_id=uuid4(), db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404


class TestDeleteOtpCode:
    """DELETE /api/otp-codes/{otp_id}"""

    @pytest.mark.asyncio
    async def test_deletes_otp(self):
        from app.api.otp import delete_otp_code

        otp = _make_otp()
        db = AsyncMock()

        with patch("app.api.otp.get_or_404", new=AsyncMock(return_value=otp)):
            await delete_otp_code(otp_id=otp.id, db=db, user_id=otp.user_id)

        db.delete.assert_awaited_once_with(otp)
        db.flush.assert_awaited_once()
