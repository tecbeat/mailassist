"""Upload AI-generated draft replies to IMAP Drafts folder.

Composes a valid RFC 2822 reply message from the stored draft body
and original mail headers, appends it to the Drafts folder via IMAP,
and tracks the draft in the ``ai_drafts`` table for later cleanup.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import TYPE_CHECKING

import structlog

from app.core.config import get_settings
from app.core.database import get_session_ctx
from app.models.mail import AIDraft
from app.services.mail import (
    ImapConnection,
    connect_imap,
    resolve_folder,
    safe_imap_logout,
)

if TYPE_CHECKING:
    from uuid import UUID

    from app.models import MailAccount

logger = structlog.get_logger()


def _compose_reply(
    *,
    draft_body: str,
    original_subject: str | None,
    original_from: str | None,
    original_message_id: str | None,
    original_references: list[str] | None,
    account_email: str,
) -> tuple[EmailMessage, str]:
    """Compose an RFC 2822 reply message.

    Returns the composed message and its Message-ID (without angle brackets).
    """
    msg = EmailMessage()
    msg_id = make_msgid()

    # Subject
    subject = original_subject or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    msg["Subject"] = subject

    # Addresses
    msg["From"] = account_email
    if original_from:
        msg["To"] = original_from

    # Threading headers
    if original_message_id:
        msg["In-Reply-To"] = f"<{original_message_id.strip('<>')}>"
        refs = list(original_references or [])
        refs.append(original_message_id.strip("<>"))
        msg["References"] = " ".join(f"<{r.strip('<>')}>" for r in refs)

    msg["Message-ID"] = msg_id
    msg["Date"] = format_datetime(datetime.now(UTC))
    msg["X-Mailer"] = "mailassist-ai-draft"

    msg.set_content(draft_body)

    # Return Message-ID without angle brackets for DB storage
    return msg, msg_id.strip("<>")


async def _append_to_drafts(
    conn: ImapConnection,
    drafts_folder: str,
    message_bytes: bytes,
) -> str | None:
    """Append a message to the Drafts folder and return the assigned UID.

    Returns None if the server does not provide the UID (APPENDUID).
    """

    def _append() -> str | None:
        import imaplib

        conn.mailbox.folder.set(drafts_folder)
        # Use low-level client APPEND with \\Draft flag
        status, data = conn.mailbox.client.append(
            drafts_folder,
            "\\Seen \\Draft",
            imaplib.Time2Internaldate(datetime.now(UTC)),
            message_bytes,
        )
        if status != "OK":
            raise RuntimeError(f"IMAP APPEND failed: {status} {data}")

        # Try to extract UID from APPENDUID response
        # Format: [APPENDUID <uidvalidity> <uid>]
        if data:
            import re

            for item in data:
                text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
                match = re.search(r"APPENDUID\s+\d+\s+(\d+)", text)
                if match:
                    return match.group(1)
        return None

    return await asyncio.to_thread(_append)


async def upload_draft_to_imap(
    *,
    account: MailAccount,
    user_id: UUID,
    mail_uid: str,
    draft_body: str,
    original_subject: str | None = None,
    original_from: str | None = None,
    original_message_id: str | None = None,
    original_references: list[str] | None = None,
) -> str | None:
    """Upload an AI draft reply to the account's IMAP Drafts folder.

    Composes the reply, appends it to Drafts, and tracks it in the
    ``ai_drafts`` table so the cleanup service can manage its lifecycle.

    Returns the draft UID if successful, None on failure.
    """
    log = logger.bind(
        mail_uid=mail_uid,
        account_id=str(account.id),
    )

    if not draft_body:
        log.warning("draft_upload_skipped_empty_body")
        return None

    settings = get_settings()
    draft_candidates = [f.strip() for f in settings.draft_folder_names.split(",") if f.strip()]

    # Compose the reply message
    msg, draft_message_id = _compose_reply(
        draft_body=draft_body,
        original_subject=original_subject,
        original_from=original_from,
        original_message_id=original_message_id,
        original_references=original_references,
        account_email=account.email_address,
    )
    message_bytes = msg.as_bytes()

    try:
        conn = await connect_imap(account)
    except Exception:
        log.exception("draft_upload_imap_connect_failed")
        return None

    draft_uid: str | None = None
    try:
        # Resolve the Drafts folder
        drafts_folder = await resolve_folder(
            conn,
            draft_candidates,
            create_if_missing=True,
        )
        if not drafts_folder:
            log.error("draft_upload_no_drafts_folder")
            return None

        # Append the message
        draft_uid = await _append_to_drafts(conn, drafts_folder, message_bytes)

        log.info(
            "draft_uploaded_to_imap",
            drafts_folder=drafts_folder,
            draft_uid=draft_uid,
        )

    except Exception:
        log.exception("draft_upload_append_failed")
        return None
    finally:
        await safe_imap_logout(conn.mailbox)

    # Track the draft in the database
    if draft_uid and original_message_id:
        try:
            async with get_session_ctx() as db:
                # Look up the TrackedEmail to get mail_id
                from sqlalchemy import select

                from app.models.mail import TrackedEmail

                te_stmt = select(TrackedEmail.id).where(
                    TrackedEmail.mail_account_id == account.id,
                    TrackedEmail.mail_uid == mail_uid,
                )
                te_result = await db.execute(te_stmt)
                tracked_email_id = te_result.scalar_one_or_none()

                if tracked_email_id is None:
                    log.warning("ai_draft_tracking_skipped_no_tracked_email")
                else:
                    ai_draft = AIDraft(
                        user_id=user_id,
                        mail_id=tracked_email_id,
                        original_message_id=original_message_id.strip("<>"),
                        draft_uid=draft_uid,
                        draft_message_id=draft_message_id,
                    )
                    db.add(ai_draft)
                    await db.commit()
                    log.info("ai_draft_tracked", draft_id=str(ai_draft.id))
        except Exception:
            # Non-fatal: draft was uploaded but tracking failed.
            # Cleanup service won't manage it, but user still sees it.
            log.exception("ai_draft_tracking_failed")

    return draft_uid
