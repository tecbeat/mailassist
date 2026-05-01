"""Contact sync ARQ cron task.

Periodically syncs contacts from CardDAV for all active configurations.
Uses each config's sync_interval to determine whether a sync is due.
Implements error counting with backoff and circuit breaker on repeated failures.
"""

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_ctx
from app.models import CardDAVConfig
from app.services.contacts import sync_contacts

logger = structlog.get_logger()

# Backoff schedule in minutes: 5, 15, 30, 60, 120 (max)
_BACKOFF_MINUTES = [5, 15, 30, 60, 120]


def _get_backoff_minutes(consecutive_errors: int) -> int:
    """Calculate backoff delay in minutes based on error count."""
    index = min(consecutive_errors, len(_BACKOFF_MINUTES) - 1)
    return _BACKOFF_MINUTES[index]


async def sync_all_contacts(ctx: dict[str, Any]) -> None:
    """Sync contacts for all active CardDAV configurations.

    Checks each config's sync_interval against last_sync_at to avoid
    syncing more frequently than configured. Applies exponential backoff
    on failures and disables configs after repeated errors (circuit breaker).
    Failures for one config do not block others.
    """
    now = datetime.now(UTC)

    async with get_session_ctx() as db:
        stmt = select(CardDAVConfig).where(CardDAVConfig.is_active.is_(True))
        result = await db.execute(stmt)
        configs = result.scalars().all()

        if not configs:
            logger.debug("contact_sync_skip", reason="no_active_configs")
            return

        for config in configs:
            # Skip if not due for sync yet
            if config.last_sync_at is not None:
                elapsed_minutes = (now - config.last_sync_at).total_seconds() / 60
                if elapsed_minutes < config.sync_interval:
                    logger.debug(
                        "contact_sync_skip",
                        user_id=str(config.user_id),
                        next_in_minutes=round(config.sync_interval - elapsed_minutes, 1),
                    )
                    continue

            # Backoff check for errored configs
            if config.consecutive_errors > 0 and config.last_error_at:
                backoff = _get_backoff_minutes(config.consecutive_errors)
                elapsed_since_error = (now - config.last_error_at).total_seconds() / 60
                if elapsed_since_error < backoff:
                    logger.debug(
                        "contact_sync_in_backoff",
                        user_id=str(config.user_id),
                        backoff_minutes=backoff,
                        elapsed_minutes=round(elapsed_since_error, 1),
                    )
                    continue

            try:
                stats = await sync_contacts(db, config)

                # Reset error state on success
                config.consecutive_errors = 0
                config.last_error = None
                config.last_error_at = None
                await db.flush()

                logger.info(
                    "contact_sync_cron_complete",
                    user_id=str(config.user_id),
                    **stats,
                )
            except Exception as e:
                config.consecutive_errors += 1
                config.last_error = str(e)[:500]
                config.last_error_at = now

                # Circuit breaker: disable after too many failures
                if config.consecutive_errors >= get_settings().contact_sync_max_errors:
                    config.is_active = False
                    logger.warning(
                        "contact_sync_circuit_breaker_tripped",
                        user_id=str(config.user_id),
                        consecutive_errors=config.consecutive_errors,
                    )
                await db.flush()

                logger.exception(
                    "contact_sync_cron_failed",
                    user_id=str(config.user_id),
                    consecutive_errors=config.consecutive_errors,
                )
