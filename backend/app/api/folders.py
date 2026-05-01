"""Assigned folder API endpoints.

Provides listing, folder summary, delete, and full smart-folder reset
views for folders assigned by the AI smart folder plugin.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy import update as sa_update

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import UnaryExpression

from app.api.deps import CurrentUserId, DbSession, build_paginated_response, get_or_404, paginate, sanitize_like
from app.models import AssignedFolder, FolderChangeLog, MailAccount, TrackedEmail, TrackedEmailStatus
from app.schemas.assigned_folder import (
    AssignedFolderListResponse,
    AssignedFolderResponse,
    FolderSummary,
    FolderSummaryListResponse,
    SmartFolderReprocessResponse,
    SmartFolderResetAccountResult,
    SmartFolderResetResponse,
)
from app.services.mail import connect_imap, delete_folder, invalidate_folder_cache, move_all_to_inbox, safe_imap_logout

logger = structlog.get_logger()

router = APIRouter(prefix="/api/folders", tags=["folders"])


@router.get("")
async def list_assigned_folders(
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    folder: str | None = None,
    sort: Literal["newest", "oldest", "folder"] = Query(default="newest", description="Sort order"),
) -> AssignedFolderListResponse:
    """List assigned folders with pagination and optional folder filter."""
    uid = user_id

    base_stmt = select(AssignedFolder).where(AssignedFolder.user_id == uid)

    if folder:
        base_stmt = base_stmt.where(AssignedFolder.folder.ilike(f"%{sanitize_like(folder)}%"))

    order_col: UnaryExpression[Any]
    if sort == "oldest":
        order_col = AssignedFolder.created_at.asc()
    elif sort == "folder":
        order_col = AssignedFolder.folder.asc()
    else:
        order_col = AssignedFolder.created_at.desc()

    base_stmt = base_stmt.order_by(order_col)
    result = await paginate(db, base_stmt, page, per_page)

    return build_paginated_response(result, AssignedFolderResponse, AssignedFolderListResponse)


@router.get("/summary")
async def get_folder_summary(
    db: DbSession,
    user_id: CurrentUserId,
) -> FolderSummaryListResponse:
    """Get a summary of unique folders with usage counts."""
    uid = user_id

    stmt = (
        select(AssignedFolder.folder, func.count().label("count"))
        .where(AssignedFolder.user_id == uid)
        .group_by(AssignedFolder.folder)
        .order_by(func.count().desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    items = [FolderSummary(folder=row.folder, count=row.count) for row in rows]
    return FolderSummaryListResponse(items=items, total=len(items))


@router.delete("/by-name/{folder_name:path}")
async def reset_smart_folder(
    folder_name: str,
    db: DbSession,
    user_id: CurrentUserId,
) -> SmartFolderResetResponse:
    """Fully reset a smart folder.

    1. For each mail account the user owns, connect via IMAP, move all
       messages in *folder_name* back to INBOX, then delete the folder.
    2. Delete all ``assigned_folders`` records for this folder name.
    3. Delete all ``folder_change_logs`` records for this folder name.
    4. Reset ``tracked_emails`` entries for the affected mail UIDs back to
       ``pending`` so the next scheduler cycle re-processes them through the
       AI pipeline.

    Returns a summary of what happened per account.
    """
    uid = user_id

    # Gather affected mail UIDs *before* deleting the assigned_folders rows
    af_stmt = select(AssignedFolder.mail_account_id, AssignedFolder.mail_uid).where(
        AssignedFolder.user_id == uid,
        AssignedFolder.folder == folder_name,
    )
    af_rows = (await db.execute(af_stmt)).all()

    if not af_rows:
        raise HTTPException(status_code=404, detail=f"No records found for folder: {folder_name}")

    # Build per-account UID sets for tracked_emails reset
    account_uids: dict[UUID, set[str]] = {}
    for row in af_rows:
        account_uids.setdefault(row.mail_account_id, set()).add(row.mail_uid)

    # Fetch user's mail accounts (only those that actually have assigned mails)
    acct_ids = list(account_uids.keys())
    acct_stmt = select(MailAccount).where(
        MailAccount.id.in_(acct_ids),
        MailAccount.user_id == uid,
    )
    accounts = (await db.execute(acct_stmt)).scalars().all()

    # --- IMAP operations: move mails back + delete folder ---
    results: list[SmartFolderResetAccountResult] = []
    for account in accounts:
        entry = SmartFolderResetAccountResult(
            account_id=str(account.id),
            account_name=account.name,
        )
        try:
            conn = await connect_imap(account)
            try:
                moved = await move_all_to_inbox(conn, folder_name)
                entry.moved_to_inbox = len(moved)
                # Delete the now-empty folder (best-effort)
                deleted = await delete_folder(conn, folder_name)
                entry.imap_folder_deleted = deleted
            finally:
                await safe_imap_logout(conn.mailbox)
            # Invalidate folder cache after IMAP mutation
            await invalidate_folder_cache(account.id)
        except Exception as exc:
            logger.warning(
                "smart_folder_reset_imap_error",
                account_id=str(account.id),
                folder=folder_name,
                error=str(exc),
            )
            entry.error = "IMAP operation failed"
        results.append(entry)

    # --- DB cleanup ---
    # 1) Delete assigned_folders records
    del_af = sa_delete(AssignedFolder).where(
        AssignedFolder.user_id == uid,
        AssignedFolder.folder == folder_name,
    )
    af_result = await db.execute(del_af)
    deleted_af = af_result.rowcount  # type: ignore[attr-defined]

    # 2) Delete folder_change_logs records
    del_fcl = sa_delete(FolderChangeLog).where(
        FolderChangeLog.user_id == uid,
        FolderChangeLog.folder == folder_name,
    )
    fcl_result = await db.execute(del_fcl)
    deleted_fcl = fcl_result.rowcount  # type: ignore[attr-defined]

    # 3) Reset tracked_emails for affected UIDs to pending (triggers reprocessing)
    #
    # The unique constraint is (mail_account_id, mail_uid, current_folder).
    # If a UID already has a tracked_email row with current_folder='INBOX'
    # (e.g. the original record before the smart folder plugin moved it),
    # we cannot UPDATE the smart-folder row to current_folder='INBOX' — that
    # would violate the constraint.  Instead we:
    #   a) Delete the smart-folder rows whose UID already exists in INBOX.
    #   b) UPDATE the remaining rows to current_folder='INBOX' + QUEUED.
    reset_tracked = 0
    for acct_id, uids in account_uids.items():
        uid_list = list(uids)

        # Find UIDs that already have a row in INBOX
        existing_inbox = select(TrackedEmail.mail_uid).where(
            TrackedEmail.user_id == uid,
            TrackedEmail.mail_account_id == acct_id,
            TrackedEmail.mail_uid.in_(uid_list),
            TrackedEmail.current_folder == "INBOX",
        )
        existing_rows = (await db.execute(existing_inbox)).scalars().all()
        existing_set = set(existing_rows)

        # a) Delete smart-folder rows that would collide
        if existing_set:
            colliding = list(existing_set)
            del_dup = sa_delete(TrackedEmail).where(
                TrackedEmail.user_id == uid,
                TrackedEmail.mail_account_id == acct_id,
                TrackedEmail.mail_uid.in_(colliding),
                TrackedEmail.current_folder == folder_name,
            )
            await db.execute(del_dup)

            # Re-queue the existing INBOX rows so they get reprocessed
            upd_inbox = (
                sa_update(TrackedEmail)
                .where(
                    TrackedEmail.user_id == uid,
                    TrackedEmail.mail_account_id == acct_id,
                    TrackedEmail.mail_uid.in_(colliding),
                    TrackedEmail.current_folder == "INBOX",
                )
                .values(
                    status=TrackedEmailStatus.QUEUED,
                    retry_count=0,
                    last_error=None,
                    error_type=None,
                    plugins_completed=None,
                    plugins_failed=None,
                    plugins_skipped=None,
                    completion_reason=None,
                    updated_at=datetime.now(UTC),
                )
            )
            inbox_result = await db.execute(upd_inbox)
            reset_tracked += inbox_result.rowcount  # type: ignore[attr-defined]

        # b) Update remaining rows (no collision) to INBOX + QUEUED
        safe_uids = [u for u in uid_list if u not in existing_set]
        if safe_uids:
            upd = (
                sa_update(TrackedEmail)
                .where(
                    TrackedEmail.user_id == uid,
                    TrackedEmail.mail_account_id == acct_id,
                    TrackedEmail.mail_uid.in_(safe_uids),
                    TrackedEmail.status == TrackedEmailStatus.COMPLETED,
                )
                .values(
                    status=TrackedEmailStatus.QUEUED,
                    retry_count=0,
                    last_error=None,
                    error_type=None,
                    current_folder="INBOX",
                    plugins_completed=None,
                    plugins_failed=None,
                    plugins_skipped=None,
                    completion_reason=None,
                    updated_at=datetime.now(UTC),
                )
            )
            upd_result = await db.execute(upd)
            reset_tracked += upd_result.rowcount  # type: ignore[attr-defined]

    await db.flush()

    logger.info(
        "smart_folder_reset",
        folder=folder_name,
        user_id=user_id,
        deleted_assigned_folders=deleted_af,
        deleted_folder_change_logs=deleted_fcl,
        reset_tracked_emails=reset_tracked,
    )

    return SmartFolderResetResponse(
        folder=folder_name,
        accounts=results,
        deleted_assigned_folders=deleted_af,
        deleted_folder_change_logs=deleted_fcl,
        reset_tracked_emails=reset_tracked,
    )


@router.post("/by-name/{folder_name:path}/reprocess")
async def reprocess_smart_folder(
    folder_name: str,
    db: DbSession,
    user_id: CurrentUserId,
) -> SmartFolderReprocessResponse:
    """Re-queue all emails in a folder for AI reprocessing.

    Unlike ``reset_smart_folder``, this keeps the IMAP folder intact and
    does **not** delete ``AssignedFolder`` or ``FolderChangeLog`` records.
    Emails stay where they are; only their ``TrackedEmail`` status is set
    back to ``QUEUED`` so the AI pipeline re-analyses them.

    Works for both smart folders (looks up via ``AssignedFolder`` records)
    and regular IMAP folders (falls back to ``TrackedEmail.current_folder``).

    Useful when AI prompts or smart folder rules have changed and the
    user wants to re-evaluate existing folder assignments without losing the
    current folder structure.
    """
    uid = user_id

    # Try smart folder lookup first (via AssignedFolder records)
    af_stmt = select(AssignedFolder.mail_account_id, AssignedFolder.mail_uid).where(
        AssignedFolder.user_id == uid,
        AssignedFolder.folder == folder_name,
    )
    af_rows = (await db.execute(af_stmt)).all()

    requeued = 0

    if af_rows:
        # Smart folder path: re-queue by specific mail UIDs
        account_uids: dict[UUID, set[str]] = {}
        for row in af_rows:
            account_uids.setdefault(row.mail_account_id, set()).add(row.mail_uid)

        for acct_id, uids in account_uids.items():
            upd = (
                sa_update(TrackedEmail)
                .where(
                    TrackedEmail.user_id == uid,
                    TrackedEmail.mail_account_id == acct_id,
                    TrackedEmail.mail_uid.in_(uids),
                    TrackedEmail.status == TrackedEmailStatus.COMPLETED,
                )
                .values(
                    status=TrackedEmailStatus.QUEUED,
                    retry_count=0,
                    last_error=None,
                    error_type=None,
                    plugins_completed=None,
                    plugins_failed=None,
                    plugins_skipped=None,
                    completion_reason=None,
                    updated_at=datetime.now(UTC),
                )
            )
            upd_result = await db.execute(upd)
            requeued += upd_result.rowcount  # type: ignore[attr-defined]
    else:
        # Regular folder path: re-queue by current_folder
        upd = (
            sa_update(TrackedEmail)
            .where(
                TrackedEmail.user_id == uid,
                TrackedEmail.current_folder == folder_name,
                TrackedEmail.status == TrackedEmailStatus.COMPLETED,
            )
            .values(
                status=TrackedEmailStatus.QUEUED,
                retry_count=0,
                last_error=None,
                error_type=None,
                plugins_completed=None,
                plugins_failed=None,
                plugins_skipped=None,
                completion_reason=None,
                updated_at=datetime.now(UTC),
            )
        )
        upd_result = await db.execute(upd)
        requeued = upd_result.rowcount  # type: ignore[attr-defined]

    await db.flush()

    logger.info(
        "smart_folder_reprocess",
        folder=folder_name,
        user_id=user_id,
        requeued_emails=requeued,
    )

    return SmartFolderReprocessResponse(
        folder=folder_name,
        requeued_emails=requeued,
    )


@router.delete("/{folder_id}", status_code=204)
async def delete_assigned_folder(
    folder_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete an assigned folder record."""
    record = await get_or_404(db, AssignedFolder, folder_id, user_id, "Folder record not found")
    await db.delete(record)
    await db.flush()
    logger.info("assigned_folder_deleted", folder_id=str(folder_id))
