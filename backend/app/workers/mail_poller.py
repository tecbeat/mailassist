"""Mail polling ARQ worker task.

Polls active mail accounts for new messages via IMAP.
Uses fair queuing to prevent one user from starving others.
Implements exponential backoff on failures.

Polling behaviour depends on the account's initial scan state:

* **Initial scan** (``scan_existing_emails=True``): iterate every folder
  (minus ``excluded_folders``) with ``SEARCH ALL`` once, then mark
  ``initial_scan_done=True``.
* **Initial scan** (``scan_existing_emails=False``): immediately mark
  ``initial_scan_done=True`` and start normal polling.
* **Normal polling** (after initial scan): ``SELECT INBOX`` →
  ``SEARCH ALL`` — fetches all UIDs, then diffs against the database
  to find untracked mails.  This ensures mails marked as read by
  another client are still processed.

Uses ``imap-tools`` which returns real UIDs directly from search,
eliminating the need for sequence-number-to-UID resolution.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_ctx
from app.core.config import get_settings
from app.models import MailAccount, TrackedEmail, TrackedEmailStatus
from app.services.mail import (
    ImapConnection,
    check_circuit_breaker,
    connect_imap,
    fetch_envelopes,
    get_cached_folders,
    list_folders,
    safe_imap_logout,
    search_uids,
    set_cached_folders,
    update_account_sync_status,
)
from app.workers.utils import (
    get_backoff_seconds,
)
from app.workers.health import timed_operation
from app.workers.idle_monitor import is_idle_active

logger = structlog.get_logger()

# Exponential backoff schedule: 30s, 60s, 120s, 300s (max)
POLLER_BACKOFF_SCHEDULE = [30, 60, 120, 300]

# Max UIDs per individual IMAP fetch to avoid server-side timeouts on large mailboxes
_ENVELOPE_SUBBATCH_SIZE = 100


async def poll_mail_accounts(ctx: dict) -> None:
    """Poll all active mail accounts for new messages.

    Fair queuing: processes accounts round-robin across users.

    Uses a short-lived DB session to load the account list, then
    polls each account in its own session so that IMAP timeouts
    on one account don't hold a DB connection for minutes.
    """
    # --- Phase 1: Load account list in a short session ---
    account_ids: list[str] = []
    async with get_session_ctx() as db:
        stmt = (
            select(
                MailAccount.id,
                MailAccount.user_id,
                MailAccount.polling_interval_minutes,
                MailAccount.last_sync_at,
                MailAccount.consecutive_errors,
                MailAccount.last_error_at,
            )
            .where(
                MailAccount.is_paused.is_(False),
                MailAccount.polling_enabled.is_(True),
            )
            .order_by(MailAccount.user_id, MailAccount.last_sync_at.asc().nullsfirst())
        )
        result = await db.execute(stmt)
        rows = result.all()

        if not rows:
            logger.debug("no_accounts_to_poll")
            return

        now = datetime.now(UTC)
        for row in rows:
            account_id = str(row.id)
            interval_seconds = row.polling_interval_minutes * 60

            # Check if enough time has passed since last sync
            if row.last_sync_at:
                elapsed = (now - row.last_sync_at).total_seconds()
                if elapsed < interval_seconds:
                    continue

            # Check backoff for errored accounts
            if row.consecutive_errors > 0 and row.last_error_at:
                backoff = get_backoff_seconds(row.consecutive_errors, POLLER_BACKOFF_SCHEDULE)
                elapsed_since_error = (now - row.last_error_at).total_seconds()
                if elapsed_since_error < backoff:
                    logger.debug(
                        "account_in_backoff",
                        account_id=account_id,
                        backoff_seconds=backoff,
                        elapsed=elapsed_since_error,
                    )
                    continue

            account_ids.append(account_id)

    if not account_ids:
        return

    logger.info("polling_started", account_count=len(account_ids))

    # --- Phase 2: Poll accounts concurrently with bounded parallelism ---
    semaphore = asyncio.Semaphore(get_settings().poll_concurrency)

    async def _poll_with_semaphore(acct_id: str) -> None:
        async with semaphore:
            account = None
            async with get_session_ctx() as db:
                stmt = select(MailAccount).where(MailAccount.id == UUID(acct_id))
                result = await db.execute(stmt)
                account = result.scalar_one_or_none()
                if account is not None:
                    db.expunge(account)
            if account is None or account.is_paused:
                return
            await _poll_single_account(account)

    await asyncio.gather(*[_poll_with_semaphore(aid) for aid in account_ids])


async def _poll_single_account(
    account: MailAccount,
    *,
    force: bool = False,
) -> None:
    """Poll a single mail account and insert new UIDs into tracked_emails.

    DB sessions are opened only for short DB operations so that slow IMAP
    I/O does not hold a database connection checked out from the pool.

    Behaviour depends on ``initial_scan_done``:

    * **Not done + scan_existing_emails**: scan all folders (minus excluded)
      with ``SEARCH ALL``, then mark ``initial_scan_done``.
    * **Not done + not scan_existing_emails**: skip straight to normal mode,
      mark ``initial_scan_done`` immediately.
    * **Done**: poll INBOX only with ``SEARCH ALL`` + DB diff.
    """
    account_id = str(account.id)
    is_initial_scan = not account.initial_scan_done

    # If scan_existing_emails is off, skip the initial scan entirely
    if is_initial_scan and not account.scan_existing_emails:
        async with get_session_ctx() as db:
            stmt = select(MailAccount).where(MailAccount.id == account.id)
            result = await db.execute(stmt)
            acct = result.scalar_one_or_none()
            if acct is not None:
                acct.initial_scan_done = True
                await db.flush()
        logger.info("initial_scan_skipped", account_id=account_id)
        is_initial_scan = False

    # After initial scan is done: INBOX only, SEARCH ALL + DB diff
    # Skip only if IDLE monitor is *actually* running for this account
    if not is_initial_scan:
        if not force and is_idle_active(account_id):
            logger.debug(
                "poll_skipped_idle_active",
                account_id=account_id,
            )
            return
        folders = ["INBOX"]
        search_criterion = "ALL"
    else:
        # Initial scan with scan_existing_emails: all folders, ALL criterion
        search_criterion = "ALL"
        folders = None  # determined below after IMAP connect

    conn: ImapConnection | None = None
    try:
        async with timed_operation("imap_poll", account_id=account_id):
            conn = await connect_imap(account)

            # Resolve folder list for initial scan
            if folders is None:
                all_folders = await get_cached_folders(account.id)
                if all_folders is None:
                    all_folders = await list_folders(conn)
                    await set_cached_folders(account.id, all_folders)
                excluded = set(account.excluded_folders or [])
                folders = [f for f in all_folders if f not in excluded]
                if not folders:
                    logger.debug(
                        "no_folders_to_scan",
                        account_id=account_id,
                        total_folders=len(all_folders),
                        excluded=len(excluded),
                    )
                    async with get_session_ctx() as db:
                        stmt = select(MailAccount).where(MailAccount.id == account.id)
                        result = await db.execute(stmt)
                        acct = result.scalar_one_or_none()
                        if acct is not None:
                            acct.initial_scan_done = True
                            await db.flush()
                    return

            total_inserted = 0
            for folder in folders:
                inserted = await _poll_folder(
                    conn, account, folder,
                    search_criterion=search_criterion,
                    is_initial_scan=is_initial_scan,
                )
                total_inserted += inserted

            # Mark initial scan done after all folders are processed
            if is_initial_scan:
                async with get_session_ctx() as db:
                    stmt = select(MailAccount).where(MailAccount.id == account.id)
                    result = await db.execute(stmt)
                    acct = result.scalar_one_or_none()
                    if acct is not None:
                        acct.initial_scan_done = True
                        await db.flush()
                logger.info(
                    "initial_scan_complete",
                    account_id=account_id,
                    folders_scanned=len(folders),
                    inserted=total_inserted,
                )

        # Success — reset error state in a short session
        async with get_session_ctx() as db:
            await update_account_sync_status(db, account.id)

    except Exception as exc:
        logger.exception("polling_failed", account_id=account_id)
        async with get_session_ctx() as db:
            await update_account_sync_status(db, account.id, error=str(exc))
            await check_circuit_breaker(db, account.id)

    finally:
        if conn is not None:
            await safe_imap_logout(conn.mailbox)


async def _poll_folder(
    conn: ImapConnection,
    account: MailAccount,
    folder: str,
    *,
    search_criterion: str,
    is_initial_scan: bool,
) -> int:
    """Search a single IMAP folder for new messages and insert them.

    Opens short-lived DB sessions for the diff query and insert only.
    Returns the number of rows inserted.
    """
    account_id = str(account.id)

    try:
        uids = await search_uids(conn, folder=folder, criteria=search_criterion)
    except Exception:
        logger.warning(
            "folder_search_failed",
            account_id=account_id,
            folder=folder,
            criterion=search_criterion,
        )
        return 0

    if not uids:
        logger.debug(
            "no_messages_in_folder",
            account_id=account_id,
            folder=folder,
            criterion=search_criterion,
            initial_scan=is_initial_scan,
        )
        return 0

    # Filter out UIDs already tracked (server-side, per-folder)
    # Short DB session for the diff query
    new_uids: list[str] = []
    async with get_session_ctx() as db:
        new_uids = await _get_new_uids(db, account_id, uids, folder=folder)

    logger.info(
        "messages_found",
        account_id=account_id,
        folder=folder,
        total=len(uids),
        already_tracked=len(uids) - len(new_uids),
        new=len(new_uids),
        criterion=search_criterion,
        initial_scan=is_initial_scan,
    )

    if not new_uids:
        return 0

    # Insert new UIDs in batches (respecting initial scan batch limit)
    batch_size = get_settings().poll_initial_scan_batch if is_initial_scan else len(new_uids)
    total_inserted = 0
    total_envelopes_fetched = 0  # cumulative across all outer batches

    for i in range(0, len(new_uids), batch_size):
        batch = new_uids[i : i + batch_size]

        # Fetch envelope metadata for the batch (IMAP I/O — no DB session)
        # Split into sub-batches to avoid IMAP timeouts on large mailboxes
        envelopes: dict[str, tuple[str | None, str | None, datetime | None]] = {}
        for j in range(0, len(batch), _ENVELOPE_SUBBATCH_SIZE):
            subbatch = batch[j : j + _ENVELOPE_SUBBATCH_SIZE]
            sub_envelopes = await fetch_envelopes(conn, subbatch, folder=folder)
            envelopes.update(sub_envelopes)
            total_envelopes_fetched += len(sub_envelopes)

            # Progress logging during initial scan for large mailboxes
            if is_initial_scan:
                progress_pct = (total_envelopes_fetched / len(new_uids)) * 100
                logger.debug(
                    "initial_scan_progress",
                    account_id=account_id,
                    folder=folder,
                    fetched=total_envelopes_fetched,
                    total=len(new_uids),
                    progress_pct=progress_pct,
                )

        # Bulk insert into tracked_emails with correct folder (short DB session)
        async with get_session_ctx() as db:
            inserted = await _insert_tracked_batch(
                db, account.user_id, account.id, batch, envelopes,
                current_folder=folder,
            )
        total_inserted += inserted

    logger.info(
        "poll_tracked_emails_inserted",
        account_id=account_id,
        folder=folder,
        inserted=total_inserted,
        total_new=len(new_uids),
        initial_scan=is_initial_scan,
    )

    return total_inserted


async def _get_new_uids(
    db: AsyncSession,
    account_id: str,
    candidate_uids: list[str],
    folder: str = "INBOX",
) -> list[str]:
    """Filter out UIDs that are already tracked, using a server-side check.

    Instead of loading every tracked UID into Python memory, we send the
    candidate UIDs to PostgreSQL and let the database return only the ones
    that don't exist yet.  This keeps memory usage constant regardless of
    how many emails an account has accumulated.

    The folder is included in the lookup because IMAP UIDs are only unique
    within a single mailbox — the same UID number can refer to completely
    different messages in different folders.
    """
    if not candidate_uids:
        return []

    from sqlalchemy import text
    from sqlalchemy import bindparam, ARRAY, String

    # Use PostgreSQL unnest() to turn the candidate array into a virtual
    # table, then exclude UIDs that already exist in tracked_emails.
    # Batch in groups of 5 000 to stay within parameter limits.
    batch_size = 5_000
    new_uids: list[str] = []
    acct_uuid = UUID(account_id)

    query = text("""
        SELECT u.uid
        FROM unnest(:uids) AS u(uid)
        WHERE NOT EXISTS (
            SELECT 1 FROM tracked_emails te
            WHERE te.mail_account_id = :account_id
              AND te.mail_uid = u.uid
              AND te.current_folder = :folder
        )
    """).bindparams(bindparam("uids", type_=ARRAY(String)))

    for i in range(0, len(candidate_uids), batch_size):
        batch = candidate_uids[i : i + batch_size]
        result = await db.execute(
            query, {"uids": batch, "account_id": acct_uuid, "folder": folder},
        )
        new_uids.extend(row[0] for row in result.all())

    return new_uids


async def _insert_tracked_batch(
    db: AsyncSession,
    user_id: UUID,
    mail_account_id: UUID,
    uids: list[str],
    envelopes: dict[str, tuple[str | None, str | None, datetime | None]],
    *,
    current_folder: str = "INBOX",
) -> int:
    """Bulk-insert tracked_emails rows using INSERT ... ON CONFLICT DO NOTHING.

    Splits into sub-batches to stay under PostgreSQL's 32,767 bind-parameter
    limit (11 columns per row → max ~2,900 rows per statement).

    Returns the number of rows actually inserted (excludes conflicts).
    """
    if not uids:
        return 0

    now = datetime.now(UTC)
    rows = []
    for uid in uids:
        subject, sender, received_at = envelopes.get(uid, (None, None, None))
        rows.append(
            {
                "user_id": user_id,
                "mail_account_id": mail_account_id,
                "mail_uid": uid,
                "status": TrackedEmailStatus.QUEUED,
                "subject": subject,
                "sender": sender,
                "received_at": received_at,
                "retry_count": 0,
                "current_folder": current_folder,
                "created_at": now,
                "updated_at": now,
            }
        )

    # 11 columns per row; 32_767 // 11 = 2978, use 2000 for safety margin
    max_rows_per_insert = 2000
    total_inserted = 0

    for i in range(0, len(rows), max_rows_per_insert):
        batch = rows[i : i + max_rows_per_insert]
        stmt = (
            pg_insert(TrackedEmail)
            .values(batch)
            .on_conflict_do_nothing(constraint="uq_tracked_email_account_uid")
        )
        result = await db.execute(stmt)
        total_inserted += result.rowcount

    await db.flush()
    return total_inserted


async def poll_single_account(ctx: dict, user_id: str, account_id: str) -> None:
    """Poll a specific mail account (manual trigger from API)."""
    uid = UUID(account_id)
    account = None

    async with get_session_ctx() as db:
        stmt = select(MailAccount).where(
            MailAccount.id == uid,
            MailAccount.user_id == UUID(user_id),
            MailAccount.is_paused.is_(False),
        )
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()
        if account is not None:
            db.expunge(account)

    if account is None:
        logger.warning("poll_single_account_not_found", account_id=account_id)
        return

    logger.info("manual_poll_started", account_id=account_id)
    await _poll_single_account(account, force=True)
