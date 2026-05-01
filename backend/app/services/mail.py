"""Mail service for IMAP operations.

Handles IMAP connections, folder operations, and email fetching.
Credentials are decrypted just-in-time and held only for the
duration of the connection.

Uses ``imap-tools`` for all IMAP operations, wrapped in
``asyncio.to_thread()`` to avoid blocking the event loop.
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import structlog
from imap_tools import AND, MailBox
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import decrypt_credentials
from app.core.types import ConnectionTestResult
from app.models import MailAccount

logger = structlog.get_logger()


@dataclass
class ImapConnection:
    """Wrapper for an active IMAP connection with context."""

    mailbox: MailBox
    account_id: UUID
    host: str
    separator: str = "/"
    capabilities: list[str] | None = None


@dataclass
class ParsedEmail:
    """Parsed email with extracted headers and body parts."""

    uid: str
    message_id: str
    sender: str
    sender_name: str
    recipient: str
    cc: str
    subject: str
    date: datetime | None
    body_plain: str
    body_html: str
    headers: dict[str, str]
    has_attachments: bool
    attachment_names: list[str]
    size: int
    is_reply: bool
    is_forwarded: bool
    in_reply_to: str | None
    references: list[str]


async def safe_imap_logout(mailbox: object) -> None:
    """Log out from an IMAP connection, suppressing and logging errors.

    Args:
        mailbox: An ``imap_tools.MailBox`` instance (typed as ``object``
              for flexibility).
    """
    try:
        await asyncio.to_thread(mailbox.logout)  # type: ignore[union-attr]
    except Exception:
        # Benign: connection may already be closed by server.
        logger.debug("imap_logout_failed", exc_info=True)


def _get_credentials(account: MailAccount) -> dict[str, str]:
    """Decrypt credentials from a mail account. Held only briefly."""
    return decrypt_credentials(account.encrypted_credentials)


async def connect_imap(account: MailAccount) -> ImapConnection:
    """Establish an IMAP connection for the given account.

    Decrypts credentials just-in-time. The caller is responsible for
    closing the connection (via logout).
    """
    credentials = _get_credentials(account)

    if not account.imap_use_ssl:
        raise ValueError("Unencrypted IMAP connections are not allowed (SSL/TLS required)")

    timeout = get_settings().imap_timeout_seconds

    def _connect() -> MailBox:
        mb = MailBox(
            host=account.imap_host,
            port=account.imap_port,
            timeout=timeout,
        )
        mb.login(credentials["username"], credentials["password"], initial_folder=None)
        return mb

    mailbox = await asyncio.to_thread(_connect)

    # Detect folder separator from folder list
    separator = "/"
    try:
        def _detect_separator() -> str:
            folders = list(mailbox.folder.list())
            if folders:
                return folders[0].delim
            return "/"
        separator = await asyncio.to_thread(_detect_separator)
    except Exception:
        logger.warning("separator_detection_failed", account_id=str(account.id), host=account.imap_host)

    # Detect capabilities via low-level imaplib client
    capabilities: list[str] = []
    try:
        def _detect_capabilities() -> list[str]:
            status, caps = mailbox.client.capability()
            if status == "OK" and caps:
                raw = caps[0]
                text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                return text.split()
            return []
        capabilities = await asyncio.to_thread(_detect_capabilities)
    except Exception:
        logger.warning("capability_detection_failed", account_id=str(account.id), host=account.imap_host)

    logger.info(
        "imap_connected",
        account_id=str(account.id),
        host=account.imap_host,
        separator=separator,
        capabilities_count=len(capabilities),
    )

    return ImapConnection(
        mailbox=mailbox,
        account_id=account.id,
        host=account.imap_host,
        separator=separator,
        capabilities=capabilities,
    )


@asynccontextmanager
async def imap_connection(account: MailAccount) -> AsyncIterator[ImapConnection]:
    """Async context manager for IMAP connections.

    Guarantees logout even when exceptions occur, preventing
    connection leaks.

    Usage::

        async with imap_connection(account) as conn:
            await asyncio.to_thread(conn.mailbox.folder.set, "INBOX")
            ...
    """
    conn = await connect_imap(account)
    try:
        yield conn
    finally:
        await safe_imap_logout(conn.mailbox)


async def list_folders(conn: ImapConnection) -> list[str]:
    """List all selectable IMAP folders for the connection.

    Folders flagged ``\\Noselect`` (container-only) are excluded because
    they cannot be opened with SELECT/EXAMINE.
    """
    def _list() -> list[str]:
        folders = list(conn.mailbox.folder.list())
        return [
            f.name for f in folders
            if "\\Noselect" not in f.flags
        ]
    return await asyncio.to_thread(_list)


# ---------------------------------------------------------------------------
# IMAP folder cache (Valkey DB 2)
# ---------------------------------------------------------------------------

_FOLDER_CACHE_KEY = "imap_folders:{account_id}"


async def get_cached_folders(account_id: UUID) -> list[str] | None:
    """Return cached folder list for *account_id*, or ``None`` on miss."""
    from app.core.redis import get_cache_client

    cache = get_cache_client()
    raw = await cache.get(_FOLDER_CACHE_KEY.format(account_id=account_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


async def set_cached_folders(account_id: UUID, folders: list[str]) -> None:
    """Store folder list in cache with configured TTL."""
    from app.core.redis import get_cache_client

    cache = get_cache_client()
    ttl = get_settings().imap_folder_cache_ttl_seconds
    await cache.setex(
        _FOLDER_CACHE_KEY.format(account_id=account_id),
        ttl,
        json.dumps(folders),
    )


async def invalidate_folder_cache(account_id: UUID) -> None:
    """Remove cached folder list for *account_id*."""
    from app.core.redis import get_cache_client

    cache = get_cache_client()
    await cache.delete(_FOLDER_CACHE_KEY.format(account_id=account_id))


async def resolve_folder(
    conn: ImapConnection,
    candidates: tuple[str, ...] | list[str],
    *,
    fallback: str | None = None,
    create_if_missing: bool = False,
) -> str | None:
    """Find the first matching folder from a list of candidates.

    Useful for resolving special-use folders (Spam, Drafts, Sent, etc.)
    where different IMAP servers use different names.
    """
    existing = await list_folders(conn)
    for name in candidates:
        if name in existing:
            return name
    if create_if_missing and candidates:
        first = candidates[0]
        await create_folder(conn, first)
        return first
    return fallback


async def get_permanent_flags(conn: ImapConnection, folder: str = "INBOX") -> list[str]:
    """Get PERMANENTFLAGS for a folder to check custom keyword support.

    Reads PERMANENTFLAGS from the SELECT response that folder.set() issues
    internally, avoiding a second round-trip to the IMAP server.
    """
    def _get_flags() -> list[str]:
        try:
            conn.mailbox.folder.set(folder)
        except Exception:
            return []
        flags: list[str] = []
        for resp in conn.mailbox.client.untagged_responses.get("PERMANENTFLAGS", []):
            text = resp.decode("utf-8", errors="replace") if isinstance(resp, bytes) else str(resp)
            # Extract flags between parentheses
            match = re.search(r"\(([^)]*)\)", text)
            if match:
                flags = match.group(1).split()
        return flags
    return await asyncio.to_thread(_get_flags)


async def create_folder(conn: ImapConnection, folder_path: str) -> bool:
    """Create an IMAP folder, including parent folders if needed.

    Handles different folder separators per server.
    """
    def _create() -> bool:
        parts = folder_path.split(conn.separator)
        current_path = ""

        for part in parts:
            if current_path:
                current_path += conn.separator + part
            else:
                current_path = part

            try:
                conn.mailbox.folder.create(current_path)
            except Exception as e:
                # Folder may already exist, which is fine
                if "ALREADYEXISTS" not in str(e):
                    logger.warning(
                        "folder_create_failed",
                        folder=current_path,
                        error=str(e),
                    )
                    return False

        logger.info("folder_created", folder=folder_path, account_id=str(conn.account_id))
        return True

    return await asyncio.to_thread(_create)


async def update_account_sync_status(
    db: AsyncSession,
    account_id: UUID,
    error: str | None = None,
) -> None:
    """Update account sync status after a poll/sync operation."""
    now = datetime.now(UTC)
    if error:
        stmt = (
            update(MailAccount)
            .where(MailAccount.id == account_id)
            .values(
                last_error=error,
                last_error_at=now,
                consecutive_errors=MailAccount.consecutive_errors + 1,
                updated_at=now,
            )
        )
    else:
        stmt = (
            update(MailAccount)
            .where(MailAccount.id == account_id)
            .values(
                last_sync_at=now,
                last_error=None,
                last_error_at=None,
                consecutive_errors=0,
                updated_at=now,
            )
        )
    await db.execute(stmt)
    await db.commit()


async def check_circuit_breaker(
    db: AsyncSession,
    account_id: UUID,
    max_errors: int = 10,
) -> bool:
    """Check if an account should be disabled due to repeated failures.

    Returns True if the account was disabled (circuit breaker tripped).
    """
    stmt = select(MailAccount).where(MailAccount.id == account_id)
    result = await db.execute(stmt)
    account = result.scalar_one_or_none()

    if account and account.consecutive_errors >= max_errors and not account.is_paused:
        account.is_paused = True
        account.paused_reason = "circuit_breaker"
        account.paused_at = datetime.now(UTC)
        await db.commit()
        logger.warning(
            "circuit_breaker_tripped",
            account_id=str(account_id),
            consecutive_errors=account.consecutive_errors,
        )
        return True

    return False


async def store_flags(
    conn: ImapConnection,
    mail_uid: str,
    flags: list[str],
    folder: str = "INBOX",
) -> bool:
    """Add flags/keywords to a message via IMAP STORE.

    Use standard flags like \\Seen, \\Flagged, \\Deleted or custom
    IMAP keywords (labels) like 'newsletter', 'coupon'.
    """
    def _store() -> bool:
        conn.mailbox.folder.set(folder)
        conn.mailbox.flag(mail_uid, flags, True)
        return True

    try:
        await asyncio.to_thread(_store)
        logger.info("flags_stored", mail_uid=mail_uid, flags=flags)
        return True
    except Exception as e:
        logger.warning(
            "store_flags_failed",
            mail_uid=mail_uid,
            flags=flags,
            error=str(e),
        )
        return False


@dataclass(frozen=True, slots=True)
class MoveResult:
    """Result of an IMAP MOVE/COPY operation.

    Attributes:
        success: Whether the move succeeded.
        new_uid: The UID assigned to the message in the destination folder,
            parsed from the COPYUID response code.  ``None`` if the server
            did not return COPYUID (rare, but possible on old servers).
    """

    success: bool
    new_uid: str | None = None


_COPYUID_RE = re.compile(r"\[COPYUID\s+\d+\s+\d+\s+(\d+)\]", re.IGNORECASE)


def _parse_copyuid(data: list) -> str | None:
    """Extract the destination UID from an IMAP COPYUID response code.

    Works with both imaplib response data (list of bytes) and string data.
    """
    for item in data:
        text = item.decode("utf-8", errors="replace") if isinstance(item, bytes) else str(item)
        m = _COPYUID_RE.search(text)
        if m:
            return m.group(1)
    return None


async def move_message(
    conn: ImapConnection,
    mail_uid: str,
    destination: str,
    source: str = "INBOX",
) -> MoveResult:
    """Move a message to a different IMAP folder.

    Uses UID MOVE if the server supports it, otherwise falls back
    to COPY + STORE \\Deleted + EXPUNGE.

    Uses low-level imaplib client to capture the COPYUID response
    for tracking the new UID in the destination folder.
    """
    def _move() -> MoveResult:
        conn.mailbox.folder.set(source)
        client = conn.mailbox.client

        supports_move = conn.capabilities and any(
            cap.upper() == "MOVE" for cap in conn.capabilities
        )

        if supports_move:
            try:
                status, data = client.uid("MOVE", mail_uid, destination)
                if status == "OK":
                    new_uid = _parse_copyuid(data)
                    logger.info(
                        "message_moved", mail_uid=mail_uid,
                        destination=destination, new_uid=new_uid,
                    )
                    return MoveResult(success=True, new_uid=new_uid)
            except Exception:
                logger.warning(
                    "move_failed_fallback_to_copy",
                    mail_uid=mail_uid,
                )

        # Fallback: COPY + DELETE
        status, data = client.uid("COPY", mail_uid, destination)
        if status != "OK":
            logger.warning(
                "copy_failed",
                mail_uid=mail_uid,
                destination=destination,
                status=status,
            )
            return MoveResult(success=False)

        new_uid = _parse_copyuid(data)

        status, _ = client.uid("STORE", mail_uid, "+FLAGS", "(\\Deleted)")
        if status != "OK":
            logger.warning(
                "delete_flag_failed_after_copy",
                mail_uid=mail_uid,
                status=status,
            )
            return MoveResult(success=False)

        client.expunge()
        logger.info(
            "message_moved", mail_uid=mail_uid,
            destination=destination, method="copy+delete", new_uid=new_uid,
        )
        return MoveResult(success=True, new_uid=new_uid)

    return await asyncio.to_thread(_move)


async def move_all_to_inbox(conn: ImapConnection, folder_path: str) -> list[str]:
    """Move every message in *folder_path* back to INBOX.

    Returns the list of UIDs that were successfully moved.
    """
    def _get_uids() -> list[str]:
        conn.mailbox.folder.set(folder_path)
        return conn.mailbox.uids("ALL")
    try:
        uid_list = await asyncio.to_thread(_get_uids)
    except Exception:
        logger.warning("select_failed_for_move_all", folder=folder_path)
        return []

    if not uid_list:
        logger.info("folder_already_empty", folder=folder_path)
        return []

    moved: list[str] = []

    def _batch_move() -> list[str]:
        """Move all UIDs in a single batch to avoid per-message expunge.

        Uses UID MOVE if supported, otherwise falls back to
        COPY + STORE \\Deleted + single EXPUNGE for the whole batch.
        """
        conn.mailbox.folder.set(folder_path)
        client = conn.mailbox.client
        uid_set = ",".join(uid_list)

        supports_move = conn.capabilities and any(
            cap.upper() == "MOVE" for cap in conn.capabilities
        )

        if supports_move:
            try:
                status, _data = client.uid("MOVE", uid_set, "INBOX")
                if status == "OK":
                    return list(uid_list)
            except Exception:
                logger.warning("batch_move_failed_fallback_to_copy", folder=folder_path)

        # Fallback: batch COPY, then batch flag + single EXPUNGE
        status, _data = client.uid("COPY", uid_set, "INBOX")
        if status != "OK":
            logger.warning("batch_copy_failed", folder=folder_path, status=status)
            return []

        status, _ = client.uid("STORE", uid_set, "+FLAGS", "(\\Deleted)")
        if status != "OK":
            logger.warning("batch_delete_flag_failed", folder=folder_path, status=status)
            return []

        client.expunge()
        return list(uid_list)

    try:
        moved = await asyncio.to_thread(_batch_move)
    except Exception:
        logger.exception("batch_move_to_inbox_failed", folder=folder_path)

    logger.info(
        "moved_all_to_inbox",
        folder=folder_path,
        total=len(uid_list),
        moved=len(moved),
    )
    return moved


async def delete_folder(conn: ImapConnection, folder_path: str) -> bool:
    """Delete an IMAP folder.

    Only deletes if the folder exists and is empty (no sub-folders).
    The caller should move or handle emails before calling this.
    """
    try:
        await asyncio.to_thread(conn.mailbox.folder.delete, folder_path)
        logger.info("folder_deleted", folder=folder_path, account_id=str(conn.account_id))
        return True
    except Exception as e:
        logger.warning(
            "folder_delete_failed",
            folder=folder_path,
            error=str(e),
        )
        return False


async def rename_folder(conn: ImapConnection, old_name: str, new_name: str) -> bool:
    """Rename an IMAP folder."""
    try:
        await asyncio.to_thread(conn.mailbox.folder.rename, old_name, new_name)
        logger.info(
            "folder_renamed",
            old_name=old_name,
            new_name=new_name,
            account_id=str(conn.account_id),
        )
        return True
    except Exception as e:
        logger.warning(
            "folder_rename_failed",
            old_name=old_name,
            new_name=new_name,
            error=str(e),
        )
        return False


async def get_folder_status(conn: ImapConnection, folder: str) -> dict:
    """Get message count for a folder via IMAP STATUS command."""
    def _status() -> dict:
        stat = conn.mailbox.folder.status(folder)
        return {
            "messages": stat.get("MESSAGES", 0),
            "unseen": stat.get("UNSEEN", 0),
        }
    try:
        return await asyncio.to_thread(_status)
    except Exception:
        return {"messages": 0, "unseen": 0}


async def list_folders_with_counts(conn: ImapConnection) -> list[dict]:
    """List all IMAP folders with message counts.

    Returns a list of dicts: [{"name": "INBOX", "messages": 42, "unseen": 5}, ...]
    """
    folders = await list_folders(conn)
    result = []
    for folder in folders:
        try:
            status = await get_folder_status(conn, folder)
            result.append({
                "name": folder,
                "messages": status["messages"],
                "unseen": status["unseen"],
            })
        except Exception:
            # Some folders may not support STATUS (e.g. \Noselect)
            result.append({
                "name": folder,
                "messages": 0,
                "unseen": 0,
            })
    return result


async def fetch_raw_message(
    conn: ImapConnection,
    mail_uid: str,
    folder: str = "INBOX",
) -> bytes:
    """Fetch the raw RFC822 bytes of a single message by UID.

    Uses the low-level imaplib client to get exact raw bytes
    (avoids re-serialization from parsed email objects).

    Raises:
        ValueError: If the message body is not found in the response.
    """
    def _fetch() -> bytes:
        conn.mailbox.folder.set(folder)
        status, data = conn.mailbox.client.uid("FETCH", mail_uid, "(RFC822)")
        if status != "OK":
            raise ValueError(f"imap_fetch_failed: {status}")
        # imaplib response: [(b'UID FETCH ...', b'raw message bytes'), b')']
        for item in data:
            if isinstance(item, tuple) and len(item) == 2:
                return item[1]
        raise ValueError("no_message_body_in_response")

    return await asyncio.to_thread(_fetch)


async def search_uids(
    conn: ImapConnection,
    folder: str = "INBOX",
    criteria: str = "UNSEEN",
) -> list[str]:
    """Search for message UIDs in a folder.

    Returns a list of UID strings matching the criteria.
    Uses imap-tools' native UID search which returns real UIDs directly
    (no sequence-number-to-UID resolution needed).
    """
    def _search() -> list[str]:
        conn.mailbox.folder.set(folder)
        if criteria == "UNSEEN":
            return conn.mailbox.uids(AND(seen=False))
        elif criteria == "ALL":
            return conn.mailbox.uids("ALL")
        else:
            # Pass raw IMAP search criteria string
            return conn.mailbox.uids(criteria)

    return await asyncio.to_thread(_search)


async def fetch_envelopes(
    conn: ImapConnection,
    uids: list[str],
    folder: str = "INBOX",
) -> dict[str, tuple[str | None, str | None, datetime | None]]:
    """Fetch envelope metadata (subject, sender, date) for a batch of UIDs.

    Returns a dict mapping UID -> (subject, sender_display, received_at).
    imap-tools handles all ENVELOPE parsing automatically.
    """
    if not uids:
        return {}

    def _fetch() -> dict[str, tuple[str | None, str | None, datetime | None]]:
        conn.mailbox.folder.set(folder)
        uid_str = ",".join(uids)
        envelopes: dict[str, tuple[str | None, str | None, datetime | None]] = {}
        try:
            for msg in conn.mailbox.fetch(AND(uid=uid_str), headers_only=True, mark_seen=False):
                sender = None
                if msg.from_values:
                    if msg.from_values.name:
                        sender = f"{msg.from_values.name} <{msg.from_values.email}>"
                    else:
                        sender = msg.from_values.email
                envelopes[msg.uid] = (msg.subject, sender, msg.date)
        except Exception:
            logger.exception("envelope_fetch_failed", uid_count=len(uids))
            return {uid: (None, None, None) for uid in uids}

        # Fill in any UIDs that weren't in the response
        for uid in uids:
            if uid not in envelopes:
                envelopes[uid] = (None, None, None)

        return envelopes

    return await asyncio.to_thread(_fetch)
