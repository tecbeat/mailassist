"""Tests for approval expiry None-check in _get_pending_or_404."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models import ApprovalStatus


def _make_approval(*, status=ApprovalStatus.PENDING, expires_at):
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        expires_at=expires_at,
        resolved_at=None,
    )


@pytest.mark.asyncio
async def test_expires_at_none_does_not_raise():
    """Approval with expires_at=None must not raise TypeError."""
    from app.api.approvals import _get_pending_or_404

    approval = _make_approval(expires_at=None)
    db = AsyncMock()

    with patch("app.api.approvals.get_or_404", return_value=approval):
        result = await _get_pending_or_404(db, approval.id, "user-1")

    assert result is approval


@pytest.mark.asyncio
async def test_expired_approval_raises_410():
    """Approval with expires_at in the past must raise 410."""
    from app.api.approvals import _get_pending_or_404

    past = datetime.now(UTC) - timedelta(hours=1)
    approval = _make_approval(expires_at=past)
    db = AsyncMock()

    with patch("app.api.approvals.get_or_404", return_value=approval), pytest.raises(HTTPException) as exc_info:
        await _get_pending_or_404(db, approval.id, "user-1")

    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_valid_approval_returned():
    """Approval with expires_at in the future must be returned."""
    from app.api.approvals import _get_pending_or_404

    future = datetime.now(UTC) + timedelta(hours=1)
    approval = _make_approval(expires_at=future)
    db = AsyncMock()

    with patch("app.api.approvals.get_or_404", return_value=approval):
        result = await _get_pending_or_404(db, approval.id, "user-1")

    assert result is approval
