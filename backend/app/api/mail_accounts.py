"""Mail account CRUD API endpoints.

Provides CRUD operations for mail accounts with credential encryption.
Credentials are write-only -- GET endpoints never return plaintext passwords.
"""

import contextlib
import json
from datetime import UTC, datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import CurrentUserId, DbSession, get_or_404, get_or_create
from app.core.security import get_encryption
from app.models import MailAccount, UserSettings
from app.schemas.mail_account import (
    ConnectionTestResult,
    ExcludedFoldersRequest,
    ExcludedFoldersResponse,
    FolderDeletedResponse,
    FolderRenamedResponse,
    FolderRenameRequest,
    ImapFolderListResponse,
    JobEnqueuedResponse,
    MailAccountCreate,
    MailAccountResponse,
    MailAccountUpdate,
    PauseUpdate,
    PollJobStatusResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/mail-accounts", tags=["mail-accounts"])

# Fields that may be updated via the PATCH endpoint.  Sensitive columns
# (id, user_id, encrypted_credentials, …) are intentionally excluded as
# a defense-in-depth measure on top of the Pydantic schema validation.
_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "email_address",
        "imap_host",
        "imap_port",
        "imap_use_ssl",
        "polling_enabled",
        "polling_interval_minutes",
        "idle_enabled",
        "scan_existing_emails",
        "excluded_folders",
    }
)


@router.get("")
async def list_mail_accounts(
    db: DbSession,
    user_id: CurrentUserId,
) -> list[MailAccountResponse]:
    """List all mail accounts for the current user."""
    stmt = select(MailAccount).where(MailAccount.user_id == user_id).order_by(MailAccount.created_at)
    result = await db.execute(stmt)
    accounts = result.scalars().all()
    return [MailAccountResponse.model_validate(a) for a in accounts]


@router.post("", status_code=201)
async def create_mail_account(
    data: MailAccountCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> MailAccountResponse:
    """Create a new mail account with encrypted credentials.

    If the client does not supply ``polling_interval_minutes``, the
    global ``default_polling_interval_minutes`` from user settings is
    used instead of the hard-coded schema default.
    """
    uid = user_id
    encryption = get_encryption()

    # Use user's global default when no explicit interval was provided.
    # Pydantic marks field as "set" only if the client included it in
    # the JSON body, so we can detect the implicit schema default.
    polling_interval = data.polling_interval_minutes
    if "polling_interval_minutes" not in data.model_fields_set:
        settings = await get_or_create(db, UserSettings, uid)
        polling_interval = settings.default_polling_interval_minutes

    # Encrypt credentials (username + password as JSON)
    credentials_json = json.dumps({"username": data.username, "password": data.password})
    encrypted = encryption.encrypt(credentials_json)

    account = MailAccount(
        user_id=uid,
        name=data.name,
        email_address=data.email_address,
        imap_host=data.imap_host,
        imap_port=data.imap_port,
        imap_use_ssl=data.imap_use_ssl,
        encrypted_credentials=encrypted,
        polling_enabled=data.polling_enabled,
        polling_interval_minutes=polling_interval,
        idle_enabled=data.idle_enabled,
        scan_existing_emails=data.scan_existing_emails,
    )
    db.add(account)
    await db.flush()

    logger.info("mail_account_created", account_id=str(account.id), user_id=user_id)

    # Trigger an immediate first sync so the user doesn't have to wait
    # for the next cron cycle.
    from app.core.redis import get_arq_client

    arq = get_arq_client()
    await arq.enqueue_job("poll_single_account", str(user_id), str(account.id))

    return MailAccountResponse.model_validate(account)


@router.get("/{account_id}")
async def get_mail_account(
    account_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> MailAccountResponse:
    """Get a single mail account (credentials excluded)."""
    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")
    return MailAccountResponse.model_validate(account)


@router.put("/{account_id}")
async def update_mail_account(
    account_id: UUID,
    data: MailAccountUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> MailAccountResponse:
    """Update a mail account. Only provided fields are updated."""
    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")
    encryption = get_encryption()

    update_data = data.model_dump(exclude_unset=True)

    # Handle credential update separately
    if "username" in update_data or "password" in update_data:
        # Decrypt existing credentials to merge partial updates
        try:
            existing_creds = json.loads(encryption.decrypt(account.encrypted_credentials))
        except Exception:
            logger.error("credential_decryption_failed", account_id=str(account_id))
            raise HTTPException(
                status_code=500,
                detail="Failed to decrypt existing credentials. Please re-enter both username and password.",
            ) from None
        if "username" in update_data:
            existing_creds["username"] = update_data.pop("username")
        if "password" in update_data:
            existing_creds["password"] = update_data.pop("password")
        account.encrypted_credentials = encryption.encrypt(json.dumps(existing_creds))

    # Apply remaining field updates (only whitelisted columns)
    for field, value in update_data.items():
        if field not in _UPDATABLE_FIELDS:
            continue
        # Convert enum values to their string representation for DB storage
        if hasattr(value, "value"):
            value = value.value
        setattr(account, field, value)

    await db.flush()
    logger.info("mail_account_updated", account_id=str(account_id), user_id=user_id)
    return MailAccountResponse.model_validate(account)


@router.delete("/{account_id}", status_code=204)
async def delete_mail_account(
    account_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a mail account."""
    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")
    await db.delete(account)
    logger.info("mail_account_deleted", account_id=str(account_id), user_id=user_id)


@router.post("/{account_id}/test")
async def test_connection(
    account_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ConnectionTestResult:
    """Test IMAP connectivity for a mail account.

    Decrypts credentials just-in-time, connects, and reports results.
    """
    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")
    encryption = get_encryption()
    credentials = json.loads(encryption.decrypt(account.encrypted_credentials))

    imap_success = False
    imap_message = ""
    imap_capabilities: list[str] = []
    idle_supported = False
    email_count: int | None = None

    # Test IMAP
    try:
        from imap_tools import MailBox

        def _test_imap() -> tuple[bool, str, list[str], bool, int | None]:
            mb = MailBox(host=account.imap_host, port=account.imap_port, timeout=15)
            mb.login(credentials["username"], credentials["password"], initial_folder=None)

            _imap_caps: list[str] = []
            _idle: bool = False
            _count: int | None = None

            # Check capabilities (best-effort)
            try:
                status, caps = mb.client.capability()
                if status == "OK" and caps:
                    raw = caps[0]
                    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                    _imap_caps = text.split()
                    _idle = "IDLE" in [c.upper() for c in _imap_caps]
            except Exception:
                pass

            # Count emails in INBOX (best-effort)
            try:
                mb.folder.set("INBOX")
                _count = len(mb.uids("ALL"))
            except Exception:
                pass

            with contextlib.suppress(Exception):
                mb.logout()

            return True, "IMAP connection successful", _imap_caps, _idle, _count

        import asyncio as _asyncio

        imap_success, imap_message, imap_capabilities, idle_supported, email_count = await _asyncio.to_thread(
            _test_imap
        )
    except Exception as e:
        imap_success = False
        imap_message = f"IMAP connection failed: {e}"

    return ConnectionTestResult(
        imap_success=imap_success,
        imap_message=imap_message,
        imap_capabilities=imap_capabilities,
        idle_supported=idle_supported,
        email_count=email_count,
    )


@router.post("/{account_id}/reset-health")
async def reset_account_health(
    account_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> MailAccountResponse:
    """Reset a mail account's health status (clear circuit breaker).

    Re-enables an account that was disabled due to consecutive errors.
    Use this after fixing the underlying issue (e.g. corrected credentials,
    restored network connectivity).
    """
    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")
    account.consecutive_errors = 0
    account.last_error = None
    account.last_error_at = None
    account.is_paused = False
    account.manually_paused = False
    account.paused_reason = None
    account.paused_at = None
    await db.flush()
    logger.info(
        "mail_account_health_reset",
        account_id=str(account_id),
        user_id=user_id,
    )

    # Immediately trigger the scheduler so queued mails are dispatched.
    from app.core.redis import get_arq_client
    from app.workers.scheduler import schedule_now

    await schedule_now(get_arq_client())

    return MailAccountResponse.model_validate(account)


@router.patch("/{account_id}/pause")
async def update_pause_state(
    account_id: UUID,
    data: PauseUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> MailAccountResponse:
    """Update the pause state of a mail account.

    When ``paused`` is true the account is paused — the scheduler will
    skip it until it is unpaused.  When ``paused`` is false the pause
    flag, error counters and the error history are cleared and the
    scheduler is triggered immediately.
    """
    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")

    if data.paused:
        account.is_paused = True
        account.manually_paused = True
        account.paused_reason = data.pause_reason
        account.paused_at = datetime.now(UTC)
        await db.flush()
        logger.info("mail_account_paused", account_id=str(account_id), user_id=user_id, reason=data.pause_reason)
    else:
        account.is_paused = False
        account.manually_paused = False
        account.paused_reason = None
        account.paused_at = None
        account.consecutive_errors = 0
        account.last_error = None
        account.last_error_at = None
        await db.flush()
        logger.info("mail_account_unpaused", account_id=str(account_id), user_id=user_id)

        from app.core.redis import get_arq_client
        from app.workers.scheduler import schedule_now

        await schedule_now(get_arq_client())

    return MailAccountResponse.model_validate(account)


@router.get("/{account_id}/folders")
async def list_folders(
    account_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
    counts: bool = Query(default=False, description="Include message counts per folder"),
) -> ImapFolderListResponse:
    """List IMAP folders for a mail account.

    Reuses the service-layer IMAP connection and folder listing to avoid
    duplicating parsing logic. When ``counts=true``, includes per-folder
    message and unseen counts (slower due to IMAP STATUS per folder).
    """
    from app.services.mail import (
        connect_imap,
        get_cached_folders,
        list_folders_with_counts,
        safe_imap_logout,
        set_cached_folders,
    )
    from app.services.mail import list_folders as svc_list_folders

    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")

    try:
        conn = await connect_imap(account)
        try:
            if counts:
                folder_data = await list_folders_with_counts(conn)
                # Update folder name cache from the counts data
                await set_cached_folders(account_id, [f["name"] for f in folder_data])
                return ImapFolderListResponse(
                    folders=folder_data,
                    separator=conn.separator,
                    excluded_folders=account.excluded_folders or [],
                )
            else:
                folders = await get_cached_folders(account_id)
                if folders is None:
                    folders = await svc_list_folders(conn)
                    await set_cached_folders(account_id, folders)
                return ImapFolderListResponse(
                    folders=folders,
                    separator=conn.separator,
                    excluded_folders=account.excluded_folders or [],
                )
        finally:
            with contextlib.suppress(Exception):
                await safe_imap_logout(conn.mailbox)
    except Exception as e:
        logger.error("list_folders_failed", account_id=str(account_id), error=str(e))
        raise HTTPException(status_code=502, detail="Failed to list folders") from None


@router.post("/{account_id}/poll")
async def poll_account_now(
    account_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> JobEnqueuedResponse:
    """Manually trigger polling for a specific mail account.

    Enqueues an ARQ task that polls the account for new UNSEEN messages
    and feeds them into the AI processing pipeline.
    """
    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")
    if account.is_paused:
        raise HTTPException(status_code=400, detail="Account is paused")

    from app.core.redis import get_arq_client

    arq = get_arq_client()
    job = await arq.enqueue_job(
        "poll_single_account",
        str(user_id),
        str(account_id),
    )

    logger.info("poll_triggered_manually", account_id=str(account_id), user_id=user_id)
    return JobEnqueuedResponse(status="queued", job_id=job.job_id if job else None)


@router.get("/{account_id}/poll-status")
async def get_poll_job_status(
    account_id: UUID,
    job_id: str,
    db: DbSession,
    user_id: CurrentUserId,
) -> PollJobStatusResponse:
    """Check the status of a poll job in the ARQ task queue."""
    await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")

    from arq.jobs import Job, JobStatus

    from app.core.redis import get_arq_client

    arq = get_arq_client()
    job = Job(job_id=job_id, redis=arq)
    status = await job.status()

    if status == JobStatus.not_found:
        return PollJobStatusResponse(status="not_found")
    if status in (JobStatus.queued, JobStatus.deferred):
        return PollJobStatusResponse(status="queued")
    if status == JobStatus.in_progress:
        return PollJobStatusResponse(status="in_progress")

    # complete — check if it succeeded or failed
    info = await job.result_info()
    if info and not info.success:
        error = str(info.result) if info.result else None
        return PollJobStatusResponse(status="failed", error=error)
    return PollJobStatusResponse(status="complete")


@router.delete("/{account_id}/folders/{folder_path:path}")
async def delete_imap_folder(
    account_id: UUID,
    folder_path: str,
    db: DbSession,
    user_id: CurrentUserId,
    move_to_inbox: bool = Query(default=False, description="Move all emails to INBOX before deleting the folder"),
) -> FolderDeletedResponse:
    """Delete an IMAP folder on the mail server.

    When ``move_to_inbox`` is True, all emails in the folder are moved
    back to INBOX before the folder is deleted.  Otherwise emails in
    the folder may be lost.
    """
    from app.services.mail import (
        connect_imap,
        delete_folder,
        invalidate_folder_cache,
        move_all_to_inbox,
        safe_imap_logout,
    )

    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")

    try:
        conn = await connect_imap(account)
        try:
            if move_to_inbox:
                await move_all_to_inbox(conn, folder_path)
            success = await delete_folder(conn, folder_path)
            if not success:
                raise HTTPException(status_code=400, detail=f"Failed to delete folder: {folder_path}")
            await invalidate_folder_cache(account_id)
            return FolderDeletedResponse(status="deleted", folder=folder_path)
        finally:
            with contextlib.suppress(Exception):
                await safe_imap_logout(conn.mailbox)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("delete_imap_folder_failed", account_id=str(account_id), folder=folder_path, error=str(e))
        raise HTTPException(status_code=502, detail="IMAP operation failed") from None


@router.post("/{account_id}/folders/rename")
async def rename_imap_folder(
    account_id: UUID,
    data: FolderRenameRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> FolderRenamedResponse:
    """Rename/move an IMAP folder on the mail server."""
    from app.services.mail import connect_imap, invalidate_folder_cache, rename_folder, safe_imap_logout

    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")

    try:
        conn = await connect_imap(account)
        try:
            success = await rename_folder(conn, data.old_name, data.new_name)
            if not success:
                raise HTTPException(
                    status_code=400, detail=f"Failed to rename folder: {data.old_name} -> {data.new_name}"
                )
            await invalidate_folder_cache(account_id)
            return FolderRenamedResponse(status="renamed", old_name=data.old_name, new_name=data.new_name)
        finally:
            with contextlib.suppress(Exception):
                await safe_imap_logout(conn.mailbox)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("rename_imap_folder_failed", account_id=str(account_id), error=str(e))
        raise HTTPException(status_code=502, detail="IMAP operation failed") from None


@router.put("/{account_id}/excluded-folders")
async def update_excluded_folders(
    account_id: UUID,
    data: ExcludedFoldersRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ExcludedFoldersResponse:
    """Update the excluded folders list for a mail account."""
    account = await get_or_404(db, MailAccount, account_id, user_id, "Mail account not found")

    account.excluded_folders = data.excluded_folders
    await db.flush()
    logger.info("excluded_folders_updated", account_id=str(account_id), folders=data.excluded_folders)
    return ExcludedFoldersResponse(excluded_folders=data.excluded_folders)
