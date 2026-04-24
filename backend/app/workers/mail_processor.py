"""Mail processor worker task.

ARQ entry point for email processing.  Delegates the heavy lifting to
:mod:`pipeline_orchestrator` (pipeline phases) and
:mod:`plugin_executor` (per-plugin LLM execution).

This module owns:

* ``process_mail`` — the ARQ task registered in the worker.
* ``_update_tracked_status`` / ``_update_current_folder`` — tracked
  email status bookkeeping (independent DB sessions, non-fatal).
* ``_pause_account`` / ``_pause_provider`` — set pause flags on
  the responsible provider or account on transient errors.

Error classification
--------------------
Instead of re-enqueueing individual mails with exponential backoff,
errors are classified into four categories:

* **provider_imap** — IMAP server unreachable or non-OK response →
  account paused, mail stays ``QUEUED``.
* **provider_ai** — LLM API unreachable → provider paused,
  mail goes back to ``QUEUED``.
* **mail** — permanent mail-specific error (corrupt MIME, missing
  body in IMAP response, etc.) → mail goes to ``FAILED``.

The scheduler handles retry timing via pause cooldowns on accounts
and providers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import asyncio
import time

import structlog
from sqlalchemy import select, update

from app.core.database import get_session
from app.core.events import AIProcessingCompleteEvent, get_event_bus
from app.models import AIProvider, MailAccount, TrackedEmail, TrackedEmailStatus
from app.models.mail import CompletionReason, ErrorType
from app.services.mail import connect_imap, safe_imap_logout, store_flags
from app.workers.pipeline_orchestrator import (
    EmailParseError,
    FetchedMail,
    IMAPFetchError,
    IMAPFolderError,
    PipelineResult,
    _clear_pipeline_progress,
    _set_pipeline_progress,
    execute_post_pipeline,
    fetch_account,
    fetch_raw_mail,
    parse_raw_mail,
    run_ai_pipeline,
)

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Tracked-email status helpers (independent sessions, non-fatal)
# ---------------------------------------------------------------------------

async def _update_tracked_status(
    account_id: str,
    mail_uid: str,
    status: TrackedEmailStatus,
    log: structlog.stdlib.BoundLogger,
    *,
    current_folder: str = "INBOX",
    error: str | None = None,
    error_type: ErrorType | None = None,
    plugins_completed: list[str] | None = None,
    plugins_failed: list[str] | None = None,
    plugins_skipped: list[str] | None = None,
    completion_reason: CompletionReason | None = None,
) -> None:
    """Update the status of a tracked email.

    Uses an independent DB session.  Non-fatal on failure — the health
    worker will eventually reset stale statuses.

    Args:
        current_folder: IMAP folder the mail resides in — needed to
            disambiguate UIDs that are only unique per-folder.
        error_type: Classification of the error — ``"provider_imap"``,
            ``"provider_ai"``, ``"mail"``, or ``None`` to clear.
    """
    try:
        async for db in get_session():
            stmt = select(TrackedEmail).where(
                TrackedEmail.mail_account_id == UUID(account_id),
                TrackedEmail.mail_uid == mail_uid,
                TrackedEmail.current_folder == current_folder,
            )
            result = await db.execute(stmt)
            tracked = result.scalar_one_or_none()
            if tracked is None:
                log.debug("tracked_email_not_found", mail_uid=mail_uid)
                return
            # Increment retry_count when a mail is re-queued after an error
            # so the scheduler can deprioritise previously-failed mails.
            if status == TrackedEmailStatus.QUEUED and tracked.status != TrackedEmailStatus.QUEUED:
                tracked.retry_count = tracked.retry_count + 1
            tracked.status = status
            if error is not None:
                tracked.last_error = error
            if error_type is not None:
                tracked.error_type = error_type
            if plugins_completed is not None:
                tracked.plugins_completed = plugins_completed
            if plugins_failed is not None:
                tracked.plugins_failed = plugins_failed
            if plugins_skipped is not None:
                tracked.plugins_skipped = plugins_skipped
            if completion_reason is not None:
                tracked.completion_reason = completion_reason
            await db.flush()
        log.debug("tracked_status_updated", status=status.value)
    except Exception:
        log.warning("tracked_status_update_failed", status=status.value, exc_info=True)


async def _update_tracked_metadata(
    account_id: str,
    mail_uid: str,
    current_folder: str,
    *,
    subject: str | None,
    sender: str | None,
    received_at: datetime | None,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Back-fill subject, sender, and received_at on the TrackedEmail row.

    Called after the raw email is parsed so that metadata is always
    accurate, even when the mail was discovered by the IDLE monitor
    (which does not fetch IMAP envelopes).
    """
    try:
        async for db in get_session():
            stmt = select(TrackedEmail).where(
                TrackedEmail.mail_account_id == UUID(account_id),
                TrackedEmail.mail_uid == mail_uid,
                TrackedEmail.current_folder == current_folder,
            )
            result = await db.execute(stmt)
            tracked = result.scalar_one_or_none()
            if tracked is None:
                return
            if subject is not None:
                tracked.subject = subject
            if sender is not None:
                tracked.sender = sender
            if received_at is not None:
                tracked.received_at = received_at
            await db.flush()
    except Exception:
        log.warning("tracked_metadata_update_failed", exc_info=True)


async def _update_current_folder(
    account_id: str,
    mail_uid: str,
    old_folder: str,
    new_folder: str,
    log: structlog.stdlib.BoundLogger,
    new_mail_uid: str | None = None,
) -> None:
    """Update the current_folder (and optionally mail_uid) of a tracked email after a move.

    After an IMAP MOVE, the destination folder assigns a new UID.  If the
    caller provides ``new_mail_uid`` (parsed from the COPYUID response), we
    update both ``current_folder`` and ``mail_uid`` so that the dedup
    constraint ``(mail_account_id, mail_uid, current_folder)`` correctly
    identifies the message in its new location.

    Uses an independent DB session.  Non-fatal on failure.
    """
    try:
        async for db in get_session():
            stmt = select(TrackedEmail).where(
                TrackedEmail.mail_account_id == UUID(account_id),
                TrackedEmail.mail_uid == mail_uid,
                TrackedEmail.current_folder == old_folder,
            )
            result = await db.execute(stmt)
            tracked = result.scalar_one_or_none()
            if tracked is None:
                log.debug("tracked_email_not_found_for_folder_update", mail_uid=mail_uid)
                return
            tracked.current_folder = new_folder
            if new_mail_uid:
                tracked.mail_uid = new_mail_uid
            await db.flush()
        log.info(
            "current_folder_updated", folder=new_folder,
            old_uid=mail_uid, new_uid=new_mail_uid,
        )
    except Exception:
        log.warning("current_folder_update_failed", folder=new_folder, exc_info=True)


async def _fail_queued_mails_for_folder(
    account_id: str,
    folder: str,
    error: str,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Mark all QUEUED tracked emails for a missing folder as FAILED.

    Prevents the scheduler from re-dispatching mails that will always
    fail because their folder no longer exists on the IMAP server.
    """
    try:
        async for db in get_session():
            from sqlalchemy import update

            stmt = (
                update(TrackedEmail)
                .where(
                    TrackedEmail.mail_account_id == UUID(account_id),
                    TrackedEmail.current_folder == folder,
                    TrackedEmail.status == TrackedEmailStatus.QUEUED,
                )
                .values(
                    status=TrackedEmailStatus.FAILED,
                    last_error=error,
                    error_type=ErrorType.MAIL,
                )
            )
            result = await db.execute(stmt)
            await db.flush()
            if result.rowcount:
                log.info(
                    "bulk_failed_mails_for_missing_folder",
                    folder=folder,
                    count=result.rowcount,
                )
    except Exception:
        log.warning("bulk_fail_for_folder_failed", folder=folder, exc_info=True)


# ---------------------------------------------------------------------------
# Pause helpers (independent sessions, non-fatal)
# ---------------------------------------------------------------------------

async def _pause_account(
    account_id: str,
    reason: str,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Set ``is_paused=True`` on a MailAccount.

    Uses an independent DB session.  Non-fatal on failure — the
    scheduler will simply not dispatch new mails for this account
    until the health worker detects the issue.
    """
    try:
        now = datetime.now(UTC)
        async for db in get_session():
            stmt = (
                update(MailAccount)
                .where(MailAccount.id == UUID(account_id))
                .values(
                    is_paused=True,
                    paused_reason=reason[:200],
                    paused_at=now,
                    last_error=reason[:200],
                    last_error_at=now,
                    consecutive_errors=MailAccount.consecutive_errors + 1,
                )
            )
            await db.execute(stmt)
            await db.commit()
        log.warning("account_paused", account_id=account_id, reason=reason)
    except Exception:
        log.warning("account_pause_failed", account_id=account_id, exc_info=True)


async def _pause_provider(
    provider_id: str,
    reason: str,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Set ``is_paused=True`` on an AIProvider.

    Uses an independent DB session.  Non-fatal on failure.
    """
    try:
        now = datetime.now(UTC)
        async for db in get_session():
            stmt = (
                update(AIProvider)
                .where(AIProvider.id == UUID(provider_id))
                .values(
                    is_paused=True,
                    paused_reason=reason[:200],
                    paused_at=now,
                )
            )
            await db.execute(stmt)
            await db.commit()
        log.warning("provider_paused", provider_id=provider_id, reason=reason)
    except Exception:
        log.warning("provider_pause_failed", provider_id=provider_id, exc_info=True)


# ---------------------------------------------------------------------------
# ARQ task entry point
# ---------------------------------------------------------------------------

async def process_mail(
    ctx: dict,
    user_id: str,
    account_id: str,
    mail_uid: str,
    current_folder: str = "INBOX",
    skip_plugins: list[str] | None = None,
) -> None:
    """Process a single email through the full pipeline.

    Pipeline: Fetch -> Parse -> Contact Match -> AI Plugins -> Notify

    Error classification:

    * **IMAP server errors** (non-OK response, connection failures) →
      account is paused, mail stays ``QUEUED``.
    * **IMAP per-mail errors** (``no_message_body_in_response``) →
      mail goes to ``FAILED`` (permanent, no account pause).
    * **Parse errors** (``EmailParseError``) →
      mail goes to ``FAILED`` (permanent, no retry).
    * **AI provider errors** (transient LLM errors from pipeline) →
      provider is paused, mail goes back to ``QUEUED``.

    Uses short-lived DB sessions to avoid holding a connection open
    during long-running IMAP and LLM operations.
    """
    correlation_id = f"process-{account_id}-{mail_uid}"
    log = logger.bind(
        user_id=user_id, account_id=account_id,
        mail_uid=mail_uid, current_folder=current_folder,
        correlation_id=correlation_id,
    )

    start_time = time.monotonic()

    try:
        await _process_mail_inner(
            user_id=user_id,
            account_id=account_id,
            mail_uid=mail_uid,
            current_folder=current_folder,
            skip_plugins=skip_plugins,
            log=log,
        )
    except (TimeoutError, asyncio.CancelledError):
        elapsed = time.monotonic() - start_time
        log.warning(
            "process_mail_timeout",
            elapsed_seconds=round(elapsed, 1),
        )
        # Reset to QUEUED so the scheduler can retry without waiting
        # for the stale-processing watchdog.
        await _update_tracked_status(
            account_id, mail_uid, TrackedEmailStatus.QUEUED, log,
            current_folder=current_folder,
            error=f"timeout after {round(elapsed)}s",
            error_type=ErrorType.TIMEOUT,
        )
        await _clear_pipeline_progress(account_id, mail_uid, current_folder)


async def _process_mail_inner(
    user_id: str,
    account_id: str,
    mail_uid: str,
    current_folder: str,
    skip_plugins: list[str] | None,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Inner implementation of process_mail, separated for timeout handling."""

    # --- Phase 1: Fetch account ---
    account = await fetch_account(user_id, account_id, log)
    if account is None:
        log.error("account_not_found")
        return

    # --- Phase 2: IMAP fetch + parse ---
    await _set_pipeline_progress(
        account_id, mail_uid, current_folder=current_folder, phase="imap_fetch",
    )
    try:
        raw_bytes, imap_folders, folder_sep = await fetch_raw_mail(
            account, mail_uid, current_folder, log,
        )
    except IMAPFolderError as e:
        # Folder was deleted or renamed on the server — this is permanent
        # for this mail. Mark FAILED, do NOT pause the account.
        error_msg = str(e)
        log.warning("imap_folder_missing", error=error_msg, folder=current_folder)
        await _update_tracked_status(
            account_id, mail_uid, TrackedEmailStatus.FAILED, log,
            current_folder=current_folder,
            error=error_msg,
            error_type=ErrorType.MAIL,
        )
        # Also fail all other queued mails for this folder in bulk
        await _fail_queued_mails_for_folder(account_id, current_folder, error_msg, log)
        return
    except IMAPFetchError as e:
        error_msg = str(e)
        if "no_message_body_in_response" in error_msg:
            # Per-mail issue: IMAP server responded OK but the message
            # has no downloadable body (deleted, corrupt, metadata-only).
            # This is permanent for this specific mail — mark FAILED,
            # do NOT pause the account so other mails continue processing.
            log.warning("imap_fetch_no_body", error=error_msg)
            await _update_tracked_status(
                account_id, mail_uid, TrackedEmailStatus.FAILED, log,
                current_folder=current_folder,
                error=error_msg,
                error_type=ErrorType.MAIL,
            )
        else:
            # Genuine IMAP-level error (non-OK response) — account paused
            log.error("imap_fetch_error", error=error_msg)
            await _pause_account(account_id, f"imap_fetch_error: {e}", log)
            await _update_tracked_status(
                account_id, mail_uid, TrackedEmailStatus.QUEUED, log,
                current_folder=current_folder,
                error=error_msg,
                error_type=ErrorType.PROVIDER_IMAP,
            )
        return
    except Exception as e:
        # IMAP connection failure (timeout, auth, network) — account paused
        log.warning("imap_connection_failed", error=str(e))
        await _pause_account(account_id, f"imap_connection_failed: {e}", log)
        await _update_tracked_status(
            account_id, mail_uid, TrackedEmailStatus.QUEUED, log,
            current_folder=current_folder,
            error=f"imap_connection_failed: {e}",
            error_type=ErrorType.PROVIDER_IMAP,
        )
        return

    try:
        parsed = parse_raw_mail(raw_bytes, mail_uid, log)
    except EmailParseError as e:
        # Permanent mail-specific error — no retry
        log.exception("email_parse_failed")
        await _update_tracked_status(
            account_id, mail_uid, TrackedEmailStatus.FAILED, log,
            current_folder=current_folder,
            error=str(e),
            error_type=ErrorType.MAIL,
        )
        return

    fetched = FetchedMail(
        parsed=parsed,
        raw_bytes=raw_bytes,
        imap_folders=imap_folders,
        folder_separator=folder_sep,
    )

    # Back-fill TrackedEmail metadata from the parsed email so that
    # notifications and the dashboard always have accurate subject/sender,
    # regardless of whether the mail was discovered by the poller (with
    # envelope) or the IDLE monitor (without).
    await _update_tracked_metadata(
        account_id, mail_uid, current_folder,
        subject=parsed.subject,
        sender=parsed.sender,
        received_at=parsed.date,
        log=log,
    )

    # --- Phase 3: AI pipeline ---
    # Status is already PROCESSING (set by the scheduler before ARQ dispatch).

    pipeline_result: PipelineResult
    async for db in get_session():
        pipeline_result = await run_ai_pipeline(
            db=db,
            user_id=user_id,
            account_id=account_id,
            mail_uid=mail_uid,
            current_folder=current_folder,
            account=account,
            fetched=fetched,
            skip_plugins=skip_plugins,
            log=log,
        )

    # Handle provider error — the pipeline encountered a transient LLM
    # error or provider unavailability.  All plugin results have been
    # rolled back.  Pause the responsible provider (if known) and
    # return mail to QUEUED.
    if pipeline_result.provider_error:
        await _clear_pipeline_progress(account_id, mail_uid, current_folder)
        if pipeline_result.failed_provider_id:
            reason = pipeline_result.transient_reenqueue_reason or "provider_error"
            await _pause_provider(
                pipeline_result.failed_provider_id,
                reason,
                log,
            )
        await _update_tracked_status(
            account_id, mail_uid, TrackedEmailStatus.QUEUED, log,
            current_folder=current_folder,
            error=pipeline_result.transient_reenqueue_reason or "provider_error",
            error_type=ErrorType.PROVIDER_AI,
        )
        return

    # --- Phase 4: IMAP actions ---
    if pipeline_result.auto_actions:
        await _set_pipeline_progress(
            account_id, mail_uid, current_folder=current_folder, phase="imap_actions",
        )
        try:
            new_folder, new_mail_uid = await execute_post_pipeline(
                account=account,
                account_id=account_id,
                mail_uid=mail_uid,
                current_folder=current_folder,
                auto_actions=pipeline_result.auto_actions,
                user_id=user_id,
                log=log,
            )
            if new_folder != current_folder:
                await _update_current_folder(
                    account_id, mail_uid, current_folder, new_folder, log,
                    new_mail_uid=new_mail_uid,
                )
                # Track the new coordinates so the COMPLETED status update
                # below can find the record (folder/uid changed in DB).
                current_folder = new_folder
                if new_mail_uid is not None:
                    mail_uid = new_mail_uid
        except Exception as e:
            # Phase 4 IMAP error — treat as provider error.
            # Pause the account and return mail to QUEUED so the
            # scheduler retries once the IMAP server recovers.
            log.exception(
                "phase4_imap_actions_failed",
                mail_uid=mail_uid,
                actions=pipeline_result.auto_actions,
            )
            await _pause_account(account_id, f"phase4_imap_error: {e}", log)
            await _update_tracked_status(
                account_id, mail_uid, TrackedEmailStatus.QUEUED, log,
                current_folder=current_folder,
                error=f"phase4_imap_error: {e}",
                error_type=ErrorType.PROVIDER_IMAP,
            )
            await _clear_pipeline_progress(account_id, mail_uid, current_folder)
            return

    # --- Mark \Seen on IMAP so SEARCH UNSEEN no longer returns this UID ---
    try:
        conn = await connect_imap(account)
        try:
            await store_flags(conn, mail_uid, ["\\Seen"], folder=current_folder)
        finally:
            await safe_imap_logout(conn.mailbox)
    except Exception:
        log.warning("mark_seen_failed", mail_uid=mail_uid, folder=current_folder, exc_info=True)

    # --- Mark completed ---
    _mark_completed(pipeline_result, log)

    pipeline_ran = bool(
        pipeline_result.plugins_executed
        or pipeline_result.approvals_created
        or pipeline_result.auto_actions
        or pipeline_result.plugins_skipped
    )

    if pipeline_ran:
        await _update_tracked_status(
            account_id, mail_uid, TrackedEmailStatus.COMPLETED, log,
            current_folder=current_folder,
            plugins_completed=pipeline_result.plugins_completed or None,
            plugins_failed=pipeline_result.plugins_failed or None,
            plugins_skipped=pipeline_result.plugins_skipped or None,
            completion_reason=pipeline_result.completion_reason,
        )
    else:
        # No plugins executed (e.g. all disabled, rule set skip_ai, or
        # duplicate mail).  Mark COMPLETED so the mail does not stay in
        # PROCESSING and get reset to QUEUED by the stale-processing
        # watchdog — which would create an infinite loop.
        await _update_tracked_status(
            account_id, mail_uid, TrackedEmailStatus.COMPLETED, log,
            current_folder=current_folder,
            completion_reason=CompletionReason.PIPELINE_DID_NOT_RUN,
        )
        log.info("marked_completed_pipeline_did_not_run")

    # Emit completion event
    event_bus = get_event_bus()
    await event_bus.emit(AIProcessingCompleteEvent(
        user_id=UUID(user_id),
        account_id=UUID(account_id),
        mail_uid=mail_uid,
        current_folder=current_folder,
        plugins_executed=pipeline_result.plugins_executed,
        approvals_created=pipeline_result.approvals_created,
    ))

    await _clear_pipeline_progress(account_id, mail_uid, current_folder)

    log.info(
        "mail_processing_complete",
        plugins_executed=len(pipeline_result.plugins_executed),
        approvals_created=pipeline_result.approvals_created,
    )


def _mark_completed(result: PipelineResult, log: structlog.stdlib.BoundLogger) -> None:
    """Determine the completion reason if not already set."""
    if result.completion_reason is not None:
        return

    pipeline_ran = bool(
        result.plugins_executed or result.approvals_created
        or result.auto_actions or result.plugins_skipped,
    )

    if not pipeline_ran:
        result.completion_reason = CompletionReason.PIPELINE_DID_NOT_RUN
    elif result.plugins_failed and not result.plugins_completed:
        result.completion_reason = CompletionReason.ALL_PLUGINS_FAILED
    elif result.plugins_failed:
        result.completion_reason = CompletionReason.PARTIAL_WITH_ERRORS
    else:
        result.completion_reason = CompletionReason.FULL_PIPELINE
