"""Tests for DB-based job queue historical metrics (Issue #25).

Verifies that the _count_tracked helper returns correct counts and
that the job queue endpoint includes persistent DB-based metrics
alongside transient Valkey data.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import TrackedEmailStatus


# ---------------------------------------------------------------------------
# _count_tracked helper
# ---------------------------------------------------------------------------


class TestCountTracked:
    """_count_tracked returns correct counts for various status/time filters."""

    @pytest.mark.asyncio
    async def test_count_completed_total(self):
        """Counts all COMPLETED emails for a user."""
        user_id = uuid4()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.api.dashboard import _count_tracked

        result = await _count_tracked(mock_db, user_id, TrackedEmailStatus.COMPLETED)
        assert result == 42
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_count_completed_with_since(self):
        """Counts COMPLETED emails since a specific time."""
        user_id = uuid4()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 10
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.api.dashboard import _count_tracked

        since = datetime.now(UTC) - timedelta(hours=1)
        result = await _count_tracked(
            mock_db, user_id, TrackedEmailStatus.COMPLETED, since=since,
        )
        assert result == 10

    @pytest.mark.asyncio
    async def test_count_failed_total(self):
        """Counts all FAILED emails for a user."""
        user_id = uuid4()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 3
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.api.dashboard import _count_tracked

        result = await _count_tracked(mock_db, user_id, TrackedEmailStatus.FAILED)
        assert result == 3

    @pytest.mark.asyncio
    async def test_count_returns_zero(self):
        """Returns 0 when no matching emails exist."""
        user_id = uuid4()
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        from app.api.dashboard import _count_tracked

        result = await _count_tracked(mock_db, user_id, TrackedEmailStatus.COMPLETED)
        assert result == 0


# ---------------------------------------------------------------------------
# JobQueueStatusResponse schema
# ---------------------------------------------------------------------------


class TestJobQueueStatusResponseSchema:
    """New fields are present and default correctly."""

    def test_defaults(self):
        from app.schemas.dashboard import JobQueueStatusResponse

        resp = JobQueueStatusResponse()
        assert resp.completed_total == 0
        assert resp.completed_today == 0
        assert resp.completed_last_hour == 0
        assert resp.failed_total == 0
        # Legacy field still present
        assert resp.results_stored == 0

    def test_with_values(self):
        from app.schemas.dashboard import JobQueueStatusResponse

        resp = JobQueueStatusResponse(
            queued=5,
            in_progress=2,
            results_stored=3,
            completed_total=100,
            completed_today=40,
            completed_last_hour=10,
            failed_total=5,
        )
        assert resp.completed_total == 100
        assert resp.completed_today == 40
        assert resp.completed_last_hour == 10
        assert resp.failed_total == 5
        assert resp.results_stored == 3

    def test_error_preserves_db_metrics(self):
        """Even when Valkey fails, DB metrics should be available."""
        from app.schemas.dashboard import JobQueueStatusResponse

        resp = JobQueueStatusResponse(
            error="Could not query job queue",
            completed_total=50,
            completed_today=20,
            completed_last_hour=5,
            failed_total=2,
        )
        assert resp.error == "Could not query job queue"
        assert resp.completed_total == 50
        assert resp.completed_today == 20
