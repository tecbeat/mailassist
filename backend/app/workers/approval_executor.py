"""Approval executor worker task.

Executes IMAP actions for approved approvals. For spam approvals,
moves the email to spam. For spam rejections, re-queues the email
for processing through the remaining AI plugins.

Also persists email summaries, detected newsletters, and extracted
coupons to the database when their respective approvals are executed.
"""

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session_ctx
from app.models import (
    Approval,
    ApprovalStatus,
    MailAccount,
    TrackedEmail,
)
from app.services.change_logger import save_new_folders, save_new_labels
from app.services.imap_actions import execute_imap_actions
from app.services.persistence import (
    save_applied_labels,
    save_assigned_folder,
    save_auto_reply,
    save_calendar_event,
    save_contact_assignment,
    save_coupons,
    save_email_summary,
    save_newsletter,
)

logger = structlog.get_logger()


def _rebuild_actions(function_type: str, source: dict) -> list[str]:
    """Rebuild IMAP action strings from structured approval data.

    When plugins run in approval mode they return ``requires_approval=True``
    *before* generating IMAP commands, so ``proposed_action["actions"]`` is
    empty.  This helper reconstructs the action list from the semantic
    fields (e.g. ``folder``, ``label_name``) so the executor can actually
    perform the work.
    """
    actions: list[str] = []

    if function_type == "smart_folder":
        folder = source.get("folder") or source.get("destination")
        if folder:
            actions.append(f"create_folder:{folder}")
            actions.append(f"log_new_folder:{folder}")
            actions.append(f"move_to:{folder}")

    elif function_type == "labeling":
        # Multi-label: the labeling plugin stores a list of labels
        labels = source.get("labels", [])
        if not labels:
            # Backward compat: single-label fallback
            label = source.get("label_name") or source.get("label")
            if label:
                labels = [label]
        for label in labels:
            actions.append(f"apply_label:{label}")

    elif function_type == "spam_detection":
        if source.get("is_spam"):
            actions.append("move_to:Spam")

    return actions


async def execute_approved_actions(ctx: dict, approval_id: str) -> None:
    """Execute IMAP actions stored in an approved approval record.

    Raises on IMAP failure so ARQ retries the job (max_tries=3).
    If all retries exhaust, ARQ marks the job as failed.
    """
    log = logger.bind(approval_id=approval_id)

    async with get_session_ctx() as db:
        stmt = select(Approval).where(Approval.id == UUID(approval_id))
        result = await db.execute(stmt)
        approval = result.scalar_one_or_none()

        if approval is None:
            log.error("approval_not_found")
            return

        if approval.status != ApprovalStatus.APPROVED:
            log.warning("approval_not_approved", status=approval.status.value)
            return

        # Prefer user-edited actions over AI-proposed actions.
        # When the user edited structured fields (e.g. folder name),
        # always rebuild IMAP actions from those fields so the commands
        # match what the user actually approved.
        source = approval.edited_actions or approval.proposed_action

        if approval.edited_actions:
            # User edited — rebuild actions from structured fields
            raw_actions = _rebuild_actions(approval.function_type, source)
        else:
            raw_actions = source.get("actions", [])

        # Fallback: rebuild from structured fields if actions were empty
        # (approval-mode plugins return requires_approval before building
        # IMAP commands).
        if not raw_actions:
            raw_actions = _rebuild_actions(approval.function_type, source)

        if not raw_actions:
            log.info("no_actions_to_execute")
            return

        # parse_action (used inside execute_imap_actions and change_logger)
        # handles annotation stripping, so pass raw strings directly.
        actions = raw_actions

        account = await _get_account(db, approval.mail_account_id)
        if account is None:
            log.error("mail_account_not_found", account_id=str(approval.mail_account_id))
            return

        # Load current folder from tracked email so IMAP actions
        # target the correct mailbox (the mail may have been moved).
        # Use scalars().first() rather than scalar_one_or_none()
        # because the same UID number can exist in different folders.
        current_folder = "INBOX"
        tracked_stmt = select(TrackedEmail.current_folder).where(
            TrackedEmail.mail_account_id == approval.mail_account_id,
            TrackedEmail.mail_uid == approval.mail_uid,
        )
        tracked_result = await db.execute(tracked_stmt)
        tracked_folder = tracked_result.scalars().first()
        if tracked_folder:
            current_folder = tracked_folder

        log.info(
            "executing_approved_actions",
            function_type=approval.function_type,
            mail_uid=approval.mail_uid,
            actions=actions,
            used_edited_actions=approval.edited_actions is not None,
            source_folder=current_folder,
        )

        # Raise on IMAP failure so ARQ retries the job automatically
        move_outcome = await execute_imap_actions(
            account, approval.mail_uid, actions,
            source_folder=current_folder,
            propagate_connect_errors=True,
        )

        # Update current_folder (and mail_uid) if the mail was moved
        if move_outcome.folder:
            tracked_update_stmt = select(TrackedEmail).where(
                TrackedEmail.mail_account_id == approval.mail_account_id,
                TrackedEmail.mail_uid == approval.mail_uid,
                TrackedEmail.current_folder == current_folder,
            )
            tracked_update_result = await db.execute(tracked_update_stmt)
            tracked = tracked_update_result.scalar_one_or_none()
            if tracked:
                tracked.current_folder = move_outcome.folder
                if move_outcome.new_uid:
                    tracked.mail_uid = move_outcome.new_uid
                await db.flush()
                log.info(
                    "current_folder_updated", folder=move_outcome.folder,
                    new_uid=move_outcome.new_uid,
                )

        await save_new_labels(approval.user_id, approval.mail_account_id, actions)
        await save_new_folders(approval.user_id, approval.mail_account_id, actions)
        await _persist_plugin_data(approval)
        log.info("approved_actions_complete", mail_uid=approval.mail_uid)


async def handle_spam_rejection(ctx: dict, user_id: str, account_id: str, mail_uid: str) -> None:
    """Re-process an email through the AI pipeline, skipping spam detection.

    Called when a spam approval is rejected (user says it is NOT spam).
    """
    from app.workers.mail_processor import process_mail

    log = logger.bind(user_id=user_id, account_id=account_id, mail_uid=mail_uid)
    log.info("reprocessing_after_spam_rejection")

    # Resolve current_folder from tracked email
    current_folder = "INBOX"
    async with get_session_ctx() as db:
        stmt = select(TrackedEmail.current_folder).where(
            TrackedEmail.mail_account_id == UUID(account_id),
            TrackedEmail.mail_uid == mail_uid,
        )
        result = await db.execute(stmt)
        folder = result.scalars().first()
        if folder:
            current_folder = folder

    await process_mail(
        ctx, user_id, account_id, mail_uid,
        current_folder=current_folder,
        skip_plugins=["spam_detection"],
    )


async def _get_account(db: AsyncSession, account_id: UUID) -> MailAccount | None:
    """Fetch a mail account by ID."""
    stmt = select(MailAccount).where(MailAccount.id == account_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _persist_plugin_data(approval: Approval) -> None:
    """Persist plugin-specific data from the approval's stored AI response.

    When plugins run in approval mode, their results (summaries,
    newsletters, coupons) are only saved after the user approves.
    The AI response is stored on the approval as ai_response_data.

    If the user edited the action, relevant fields from edited_actions
    override the original ai_response_data so the persisted record
    reflects what the user actually approved.
    """
    if not approval.ai_response_data:
        logger.warning(
            "no_ai_response_data",
            function_type=approval.function_type,
            approval_id=str(approval.id),
        )
        return

    data = approval.ai_response_data
    # Merge user edits into data so persistence uses the approved values
    if approval.edited_actions:
        data = {**data, **approval.edited_actions}
    fn = approval.function_type

    try:
        if fn == "email_summary":
            await save_email_summary(
                user_id=approval.user_id,
                account_id=approval.mail_account_id,
                mail_uid=approval.mail_uid,
                mail_subject=approval.mail_subject,
                mail_from=approval.mail_from,
                mail_date=approval.mail_date,
                summary=data.get("summary", ""),
                key_points=data.get("key_points", []),
                urgency=data.get("urgency", "medium"),
                action_required=data.get("action_required", False),
                action_description=data.get("action_description"),
                own_session=True,
            )
        elif fn == "newsletter_detection":
            await save_newsletter(
                user_id=approval.user_id,
                account_id=approval.mail_account_id,
                mail_uid=approval.mail_uid,
                is_newsletter=data.get("is_newsletter", False),
                newsletter_name=data.get("newsletter_name", "Unknown"),
                sender_address=approval.mail_from or "unknown",
                mail_subject=approval.mail_subject,
                unsubscribe_url=data.get("unsubscribe_url"),
                has_unsubscribe=data.get("has_unsubscribe", False),
                own_session=True,
            )
        elif fn == "coupon_extraction":
            await save_coupons(
                user_id=approval.user_id,
                account_id=approval.mail_account_id,
                mail_uid=approval.mail_uid,
                has_coupons=data.get("has_coupons", False),
                coupons=data.get("coupons", []),
                sender_email=approval.mail_from,
                mail_subject=approval.mail_subject,
                own_session=True,
            )
        elif fn == "labeling":
            await save_applied_labels(
                user_id=approval.user_id,
                account_id=approval.mail_account_id,
                mail_uid=approval.mail_uid,
                mail_subject=approval.mail_subject,
                mail_from=approval.mail_from,
                labels=data.get("labels", []),
                own_session=True,
            )
        elif fn == "smart_folder":
            await save_assigned_folder(
                user_id=approval.user_id,
                account_id=approval.mail_account_id,
                mail_uid=approval.mail_uid,
                mail_subject=approval.mail_subject,
                mail_from=approval.mail_from,
                folder=data.get("folder", "INBOX"),
                confidence=data.get("confidence"),
                reason=data.get("reason"),
                own_session=True,
            )
        elif fn == "calendar_extraction":
            await save_calendar_event(
                user_id=approval.user_id,
                account_id=approval.mail_account_id,
                mail_uid=approval.mail_uid,
                mail_subject=approval.mail_subject,
                mail_from=approval.mail_from,
                has_event=data.get("has_event", False),
                title=data.get("title"),
                start=data.get("start"),
                end=data.get("end"),
                location=data.get("location"),
                description=data.get("description"),
                is_all_day=data.get("is_all_day", False),
                own_session=True,
            )
        elif fn == "auto_reply":
            await save_auto_reply(
                user_id=approval.user_id,
                account_id=approval.mail_account_id,
                mail_uid=approval.mail_uid,
                mail_subject=approval.mail_subject,
                mail_from=approval.mail_from,
                should_reply=data.get("should_reply", False),
                draft_body=data.get("draft_body"),
                tone=data.get("tone"),
                reasoning=data.get("reasoning"),
                own_session=True,
            )
        elif fn == "contacts":
            await save_contact_assignment(
                user_id=approval.user_id,
                account_id=approval.mail_account_id,
                mail_uid=approval.mail_uid,
                mail_subject=approval.mail_subject,
                mail_from=approval.mail_from,
                contact_id=data.get("contact_id"),
                contact_name=data.get("contact_name", "Unknown"),
                confidence=data.get("confidence", 0.0),
                reasoning=data.get("reasoning"),
                is_new_contact_suggestion=data.get("is_new_contact_suggestion", False),
                auto_writeback=True,
                own_session=True,
            )
    except Exception:
        logger.exception(
            "plugin_data_persist_failed",
            function_type=fn,
            approval_id=str(approval.id),
        )
        raise
