"""Draft cleanup ARQ cron worker task.

Periodically checks all active AI drafts and cleans up stale ones.
Runs every 5 minutes (offset from other cron tasks).
Tracks per-account errors and applies circuit breaker on repeated failures.
"""

import structlog
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_ctx
from app.models import AIDraft, DraftStatus, MailAccount
from app.services.draft_cleanup import cleanup_drafts_for_account
from app.workers.utils import worker_error_handler

logger = structlog.get_logger()


async def cleanup_all_drafts(ctx: dict) -> None:
    """Clean up stale AI drafts across all mail accounts.

    Checks each account that has active AI drafts.
    Updates account sync status on success/failure and checks
    circuit breaker after failures. Failures for one account
    do not block others.
    """
    settings = get_settings()
    expiry_days = settings.draft_expiry_days

    async with get_session_ctx() as db:
        # Find accounts with active drafts
        stmt = (
            select(AIDraft.mail_account_id)
            .where(AIDraft.status == DraftStatus.ACTIVE)
            .distinct()
        )
        result = await db.execute(stmt)
        account_ids = [row[0] for row in result.all()]

        if not account_ids:
            logger.debug("draft_cleanup_skip", reason="no_active_drafts")
            return

        for account_id in account_ids:
            account_stmt = select(MailAccount).where(
                MailAccount.id == account_id,
                MailAccount.is_paused.is_(False),
            )
            account_result = await db.execute(account_stmt)
            account = account_result.scalar_one_or_none()

            if account is None:
                continue

            async with worker_error_handler(db, account_id, operation="draft_cleanup"):
                stats = await cleanup_drafts_for_account(db, account, expiry_days)
                if any(v > 0 for v in stats.values()):
                    logger.info(
                        "draft_cleanup_complete",
                        account_id=str(account_id),
                        **stats,
                    )
