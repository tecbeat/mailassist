"""Shared worker utilities.

Common helpers used across mail_poller, idle_monitor, and other worker modules.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog

from app.services.mail import check_circuit_breaker, update_account_sync_status

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Worker error handler context manager
# ---------------------------------------------------------------------------


@asynccontextmanager
async def worker_error_handler(
    db: AsyncSession,
    account_id: UUID,
    *,
    operation: str = "worker_operation",
    propagate: bool = False,
) -> AsyncIterator[None]:
    """Context manager for the common worker error-handling pattern.

    On success: clears the account's error state via ``update_account_sync_status``.
    On failure: logs the exception, increments the error counter, and
    checks the circuit breaker to disable the account if the threshold
    is exceeded.

    Args:
        db: Active database session (the caller must manage its lifecycle).
        account_id: The ``MailAccount.id`` being operated on.
        operation: Label for structured log messages.
        propagate: If ``True``, re-raise the exception after recording it.
            Useful when the caller needs to handle the error (e.g. for
            backoff/retry decisions).

    Yields:
        Control to the caller's operation code.
    """
    try:
        yield
        # Success — reset error state
        await update_account_sync_status(db, account_id)
    except Exception as exc:
        logger.exception(
            f"{operation}_failed",
            account_id=str(account_id),
        )
        await update_account_sync_status(db, account_id, error=str(exc))
        tripped = await check_circuit_breaker(db, account_id)
        if tripped:
            logger.warning(
                f"{operation}_circuit_breaker_tripped",
                account_id=str(account_id),
            )
        if propagate:
            raise


def get_backoff_seconds(consecutive_errors: int, schedule: Sequence[int]) -> int:
    """Calculate backoff delay from a schedule based on consecutive error count.

    Args:
        consecutive_errors: Number of consecutive failures (0-based or 1-based).
        schedule: Ascending list of delay values in seconds.

    Returns:
        Delay in seconds, capped at the last schedule entry.
    """
    index = min(max(consecutive_errors, 0), len(schedule) - 1)
    return schedule[index]
