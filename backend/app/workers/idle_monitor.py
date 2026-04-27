"""IMAP IDLE implementation for real-time email notifications.

IDLE is a push-based mechanism where the IMAP server notifies the client
of new messages. This avoids polling and provides near-instant detection.

Each IDLE-enabled account gets a dedicated asyncio task that maintains
a persistent IMAP connection in IDLE mode.

On new-mail notifications, UIDs are inserted into ``tracked_emails`` as
``pending``.  The scheduler cron picks them up and enqueues processing jobs.

Uses ``imap-tools`` for IDLE, wrapped in ``asyncio.to_thread()`` since
the IDLE wait is a blocking call.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models import MailAccount, TrackedEmail, TrackedEmailStatus
from app.services.mail import (
    ImapConnection,
    connect_imap,
    safe_imap_logout,
    search_uids,
    update_account_sync_status,
    check_circuit_breaker,
)
from app.workers.utils import get_backoff_seconds

logger = structlog.get_logger()

# Active IDLE tasks by account_id
_idle_tasks: dict[str, asyncio.Task] = {}

# IDLE timeout: RFC 2177 recommends re-issuing IDLE every 29 minutes.
IDLE_TIMEOUT_SECONDS = 29 * 60

# Force a full reconnect after this many IDLE cycles to prevent
# silently dead TCP connections from blocking mail detection.
MAX_IDLE_CYCLES_BEFORE_RECONNECT = 3  # ~87 minutes

# Exponential backoff for reconnection
RECONNECT_BACKOFF = [5, 10, 30, 60, 120, 300]


async def start_idle_for_account(account: MailAccount) -> None:
    """Start an IDLE monitoring task for a single mail account."""
    account_id = str(account.id)

    if account_id in _idle_tasks and not _idle_tasks[account_id].done():
        logger.debug("idle_already_running", account_id=account_id)
        return

    task = asyncio.create_task(
        _idle_loop(account),
        name=f"idle-{account_id}",
    )
    _idle_tasks[account_id] = task
    logger.info("idle_task_started", account_id=account_id)


def is_idle_active(account_id: str) -> bool:
    """Check whether an IDLE task is currently running for the given account.

    Used by the poller to decide whether to skip polling — the poller should
    only skip when IDLE is *actually* running, not just enabled in config.
    """
    task = _idle_tasks.get(account_id)
    return task is not None and not task.done()


async def stop_idle_for_account(account_id: str) -> None:
    """Stop the IDLE task for an account."""
    if account_id in _idle_tasks:
        task = _idle_tasks.pop(account_id)
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("idle_task_stopped", account_id=account_id)


async def stop_all_idle() -> None:
    """Stop all running IDLE tasks. Called on worker shutdown."""
    for account_id in list(_idle_tasks.keys()):
        await stop_idle_for_account(account_id)


async def check_idle_health() -> None:
    """Check IDLE task health and restart any crashed tasks.

    Iterates through tracked IDLE tasks and restarts any that have
    finished unexpectedly (not cancelled). Called periodically from
    the worker health cron job.
    """
    dead_accounts: list[str] = []
    for account_id, task in list(_idle_tasks.items()):
        if task.done():
            # Collect exception if any
            exc = task.exception() if not task.cancelled() else None
            if exc:
                logger.warning(
                    "idle_task_crashed",
                    account_id=account_id,
                    error=str(exc),
                )
            dead_accounts.append(account_id)

    if not dead_accounts:
        logger.debug("idle_health_ok", active_tasks=len(_idle_tasks))
        return

    # Clean up dead entries and attempt restart
    for account_id in dead_accounts:
        _idle_tasks.pop(account_id, None)

    # Restart dead IDLE tasks for accounts that are still active + idle-enabled
    async for db in get_session():
        for account_id in dead_accounts:
            stmt = select(MailAccount).where(
                MailAccount.id == UUID(account_id),
                MailAccount.is_paused.is_(False),
                MailAccount.idle_enabled.is_(True),
            )
            result = await db.execute(stmt)
            account = result.scalar_one_or_none()
            if account:
                db.expunge(account)
                logger.info("idle_task_restarting", account_id=account_id)
                await start_idle_for_account(account)


async def start_idle_manager() -> None:
    """Start IDLE monitoring for all eligible accounts.

    Called during worker startup. Scans for accounts with idle_enabled=True
    and starts an IDLE task for each.
    """
    async for db in get_session():
        stmt = select(MailAccount).where(
            MailAccount.is_paused.is_(False),
            MailAccount.idle_enabled.is_(True),
        )
        result = await db.execute(stmt)
        accounts = result.scalars().all()
        for account in accounts:
            db.expunge(account)

        logger.info("idle_manager_starting", account_count=len(accounts))

        for account in accounts:
            await start_idle_for_account(account)


async def _idle_loop(account: MailAccount) -> None:
    """Main IDLE loop for a single account.

    Maintains a persistent IMAP connection in IDLE mode on INBOX.
    Reconnects on failure with exponential backoff.
    Reloads account credentials from DB on each reconnect to pick up
    configuration changes and key rotations.

    Uses imap-tools' ``mailbox.idle.wait(timeout=N)`` which handles
    the full IDLE cycle (IDLE command, wait for push, DONE) in a
    single blocking call wrapped in ``asyncio.to_thread()``.
    """
    account_id = str(account.id)
    user_id = str(account.user_id)
    consecutive_failures = 0

    while True:
        conn = None
        try:
            # Reload account from DB to pick up credential rotations / config changes
            async for db in get_session():
                stmt = select(MailAccount).where(
                    MailAccount.id == UUID(account_id),
                    MailAccount.is_paused.is_(False),
                    MailAccount.idle_enabled.is_(True),
                )
                result = await db.execute(stmt)
                account = result.scalar_one_or_none()
                if account is not None:
                    db.expunge(account)

            if account is None:
                logger.info("idle_account_gone", account_id=account_id)
                return

            conn = await connect_imap(account)

            # Check IDLE support
            if conn.capabilities and "IDLE" not in [c.upper() for c in conn.capabilities if isinstance(c, str)]:
                logger.warning("idle_not_supported", account_id=account_id, host=account.imap_host)
                return

            # Select INBOX for IDLE monitoring
            await asyncio.to_thread(conn.mailbox.folder.set, "INBOX")

            # Reset failure counter on successful connection
            consecutive_failures = 0

            logger.info("idle_connected", account_id=account_id)

            # Catch-up: pick up any new mails already in INBOX
            # that were missed while IDLE was disconnected.
            inserted = await _search_and_insert_new(conn, account_id, user_id)
            if inserted:
                logger.info(
                    "idle_catchup_inserted",
                    account_id=account_id,
                    inserted=inserted,
                )

            idle_cycles = 0
            while True:
                # Force full reconnect after N cycles to avoid silently
                # dead TCP connections that never deliver push data.
                if idle_cycles >= MAX_IDLE_CYCLES_BEFORE_RECONNECT:
                    logger.info(
                        "idle_forcing_reconnect",
                        account_id=account_id,
                        cycles=idle_cycles,
                    )
                    break  # breaks inner loop → finally → reconnect

                # imap-tools idle.wait() handles the full IDLE cycle:
                # sends IDLE command, waits for server push or timeout,
                # sends DONE. Returns list of response bytes.
                responses = await asyncio.to_thread(
                    conn.mailbox.idle.wait,
                    timeout=IDLE_TIMEOUT_SECONDS,
                )

                idle_cycles += 1

                if not responses:
                    # Timeout with no activity — re-issue IDLE
                    logger.debug("idle_timeout_refresh", account_id=account_id)
                    continue

                # Check for new mail (EXISTS response)
                logger.debug(
                    "idle_push_received",
                    account_id=account_id,
                    responses=[
                        r.decode(errors="replace") if isinstance(r, bytes) else str(r)
                        for r in responses
                    ],
                )

                has_new_mail = any(
                    (b"EXISTS" in r if isinstance(r, bytes)
                     else "EXISTS" in str(r))
                    for r in responses
                )

                if has_new_mail:
                    logger.info("idle_new_mail", account_id=account_id)
                    await _search_and_insert_new(
                        conn, account_id, user_id,
                    )

        except asyncio.CancelledError:
            logger.info("idle_cancelled", account_id=account_id)
            return

        except Exception as e:
            consecutive_failures += 1
            backoff = get_backoff_seconds(consecutive_failures - 1, RECONNECT_BACKOFF)

            logger.error(
                "idle_connection_failed",
                account_id=account_id,
                error=str(e),
                consecutive_failures=consecutive_failures,
                retry_in=backoff,
            )

            # Update error status
            async for db in get_session():
                await update_account_sync_status(db, UUID(account_id), error=str(e))

                # Check circuit breaker
                if await check_circuit_breaker(db, UUID(account_id)):
                    logger.warning("idle_circuit_breaker_tripped", account_id=account_id)
                    return

            await asyncio.sleep(backoff)

        finally:
            if conn is not None:
                await safe_imap_logout(conn.mailbox)


async def _search_and_insert_new(
    conn: ImapConnection, account_id: str, user_id: str,
) -> int:
    """Find untracked UIDs in INBOX and insert them into tracked_emails.

    Strategy: ``SEARCH ALL`` to get every UID in the mailbox, then diff
    against the DB to find UIDs not yet tracked.  This catches mails
    regardless of their ``\\Seen`` flag — any mail missing from the
    database will be queued for processing.

    Returns the number of newly inserted rows.
    """
    try:
        uids = await search_uids(conn, folder="INBOX", criteria="ALL")
    except Exception:
        logger.warning("idle_search_failed", account_id=account_id)
        return 0

    if not uids:
        logger.debug("idle_inbox_empty", account_id=account_id)
        return 0

    # Filter out UIDs already tracked (server-side DB diff)
    async for db in get_session():
        uid_set = set(uids)
        stmt = (
            select(TrackedEmail.mail_uid)
            .where(
                TrackedEmail.mail_account_id == UUID(account_id),
                TrackedEmail.current_folder == "INBOX",
                TrackedEmail.mail_uid.in_(uids),
            )
        )
        result = await db.execute(stmt)
        existing = {row[0] for row in result.all()}
        new_uids = [u for u in uids if u not in existing]

    logger.debug(
        "idle_search_result",
        account_id=account_id,
        total_in_inbox=len(uids),
        already_tracked=len(existing),
        new=len(new_uids),
    )

    if not new_uids:
        return 0

    inserted = 0
    async for db in get_session():
        inserted = await _insert_tracked_uids(
            db, UUID(user_id), UUID(account_id), new_uids,
        )

    if inserted:
        async for db in get_session():
            await update_account_sync_status(db, UUID(account_id))

    return inserted


async def _insert_tracked_uids(
    db: AsyncSession,
    user_id: UUID,
    mail_account_id: UUID,
    uids: list[str],
) -> int:
    """Insert new UIDs into tracked_emails as pending.

    Uses INSERT ... ON CONFLICT DO NOTHING for deduplication.
    Returns the number of rows actually inserted.
    """
    if not uids:
        return 0

    now = datetime.now(UTC)
    rows = [
        {
            "user_id": user_id,
            "mail_account_id": mail_account_id,
            "mail_uid": uid,
            "status": TrackedEmailStatus.QUEUED,
            "retry_count": 0,
            "current_folder": "INBOX",
            "created_at": now,
            "updated_at": now,
        }
        for uid in uids
    ]

    stmt = (
        pg_insert(TrackedEmail)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_tracked_email_account_uid")
    )
    result = await db.execute(stmt)
    await db.flush()

    inserted = result.rowcount
    if inserted > 0:
        logger.info(
            "idle_tracked_emails_inserted",
            mail_account_id=str(mail_account_id),
            inserted=inserted,
            total_uids=len(uids),
        )
    return inserted
