from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.workers.utils import get_backoff_seconds, worker_error_handler

SCHEDULE = [5, 10, 30, 60, 120, 300]


# ---------------------------------------------------------------------------
# get_backoff_seconds
# ---------------------------------------------------------------------------


class TestGetBackoffSeconds:
    def test_zero_errors(self) -> None:
        assert get_backoff_seconds(0, SCHEDULE) == 5

    def test_one_error(self) -> None:
        assert get_backoff_seconds(1, SCHEDULE) == 10

    def test_two_errors(self) -> None:
        assert get_backoff_seconds(2, SCHEDULE) == 30

    def test_five_errors(self) -> None:
        assert get_backoff_seconds(5, SCHEDULE) == 300

    def test_ten_errors_capped(self) -> None:
        """Errors beyond schedule length are capped at the last entry."""
        assert get_backoff_seconds(10, SCHEDULE) == 300

    def test_negative_errors_clamped(self) -> None:
        assert get_backoff_seconds(-3, SCHEDULE) == 5

    def test_single_element_schedule(self) -> None:
        assert get_backoff_seconds(5, [42]) == 42


# ---------------------------------------------------------------------------
# worker_error_handler
# ---------------------------------------------------------------------------


@pytest.mark.anyio
class TestWorkerErrorHandler:
    @patch("app.workers.utils.check_circuit_breaker", new_callable=AsyncMock)
    @patch("app.workers.utils.update_account_sync_status", new_callable=AsyncMock)
    async def test_success_resets_error_state(
        self,
        mock_update: AsyncMock,
        mock_breaker: AsyncMock,
    ) -> None:
        db = AsyncMock()
        account_id = uuid4()

        async with worker_error_handler(db, account_id, operation="test_op"):
            pass  # no exception

        mock_update.assert_awaited_once_with(db, account_id)
        mock_breaker.assert_not_awaited()

    @patch("app.workers.utils.check_circuit_breaker", new_callable=AsyncMock)
    @patch("app.workers.utils.update_account_sync_status", new_callable=AsyncMock)
    async def test_failure_increments_error_and_checks_breaker(
        self,
        mock_update: AsyncMock,
        mock_breaker: AsyncMock,
    ) -> None:
        mock_breaker.return_value = False
        db = AsyncMock()
        account_id = uuid4()

        async with worker_error_handler(db, account_id, operation="test_op"):
            raise RuntimeError("connection lost")

        mock_update.assert_awaited_once_with(db, account_id, error="connection lost")
        mock_breaker.assert_awaited_once_with(db, account_id)

    @patch("app.workers.utils.check_circuit_breaker", new_callable=AsyncMock)
    @patch("app.workers.utils.update_account_sync_status", new_callable=AsyncMock)
    async def test_failure_with_propagate_reraises(
        self,
        mock_update: AsyncMock,
        mock_breaker: AsyncMock,
    ) -> None:
        mock_breaker.return_value = False
        db = AsyncMock()
        account_id = uuid4()

        with pytest.raises(RuntimeError, match="boom"):
            async with worker_error_handler(db, account_id, operation="op", propagate=True):
                raise RuntimeError("boom")

        mock_update.assert_awaited_once()
        mock_breaker.assert_awaited_once()

    @patch("app.workers.utils.check_circuit_breaker", new_callable=AsyncMock)
    @patch("app.workers.utils.update_account_sync_status", new_callable=AsyncMock)
    async def test_circuit_breaker_tripped_logs_warning(
        self,
        mock_update: AsyncMock,
        mock_breaker: AsyncMock,
    ) -> None:
        mock_breaker.return_value = True
        db = AsyncMock()
        account_id = uuid4()

        # Should not raise even though breaker tripped (propagate=False)
        async with worker_error_handler(db, account_id, operation="sync"):
            raise ValueError("bad data")

        mock_breaker.assert_awaited_once_with(db, account_id)
