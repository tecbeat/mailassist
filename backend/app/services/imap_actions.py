"""Shared IMAP action execution.

Provides a single implementation for executing IMAP operations (labels,
flags, folder creation, moves) from action strings produced by AI plugins.

Used by both ``mail_processor`` (auto-mode) and ``approval_executor``
(after user approval).
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field

import structlog

from app.models import MailAccount
from app.services.mail import MoveResult, connect_imap, create_folder, invalidate_folder_cache, move_message, resolve_folder, safe_imap_logout, store_flags

logger = structlog.get_logger()

# Well-known spam folder names, tried in order
SPAM_FOLDERS = ("Junk", "Spam", "INBOX.Junk", "INBOX.Spam")

# Action prefix constants
LABEL_PREFIX = "apply_label:"
CREATE_LABEL_PREFIX = "create_and_apply_label:"
MOVE_TO_PREFIX = "move_to:"
CREATE_FOLDER_PREFIX = "create_folder:"
MOVE_TO_SPAM_PREFIX = "move_to_spam"
MARK_AS_READ = "mark_as_read"

LOG_NEW_LABELS_PREFIX = "log_new_labels:"
LOG_NEW_FOLDER_PREFIX = "log_new_folder:"

# Action prefixes that represent meaningful work (IMAP, CalDAV, drafts)
ACTIONABLE_PREFIXES = (
    LABEL_PREFIX,
    CREATE_LABEL_PREFIX,
    LOG_NEW_LABELS_PREFIX,
    LOG_NEW_FOLDER_PREFIX,
    MOVE_TO_PREFIX,
    CREATE_FOLDER_PREFIX,
    MOVE_TO_SPAM_PREFIX,
    MARK_AS_READ,
    "create_draft_reply",
    "save_to_drafts",
    "create_calendar_event:",
    "store_coupon:",
    "store_summary",
    "store_unsubscribe_url:",
)


# ---------------------------------------------------------------------------
# ParsedAction — structured representation of an action string
# ---------------------------------------------------------------------------

# Regex to strip confidence annotations like " (confidence: 80%)" from action strings.
# Narrowed to the specific format produced by plugins so that folder names containing
# parentheses (e.g. "Projects (2024)") are not corrupted.
_ANNOTATION_RE = re.compile(r"\s*\(confidence:\s*\d+%\)\s*$")


class ActionKind(enum.Enum):
    """Enumeration of all known action types produced by AI plugins."""

    APPLY_LABEL = "apply_label"
    CREATE_AND_APPLY_LABEL = "create_and_apply_label"
    MOVE_TO = "move_to"
    MOVE_TO_SPAM = "move_to_spam"
    CREATE_FOLDER = "create_folder"
    MARK_AS_READ = "mark_as_read"
    LOG_NEW_LABELS = "log_new_labels"
    LOG_NEW_FOLDER = "log_new_folder"
    CREATE_DRAFT_REPLY = "create_draft_reply"
    SAVE_TO_DRAFTS = "save_to_drafts"
    CREATE_CALENDAR_EVENT = "create_calendar_event"
    STORE_COUPON = "store_coupon"
    STORE_SUMMARY = "store_summary"
    STORE_UNSUBSCRIBE_URL = "store_unsubscribe_url"
    UNKNOWN = "unknown"


# Ordered longest-prefix-first so "create_and_apply_label:" matches before
# "apply_label:" when both are checked.
_PREFIX_MAP: list[tuple[str, ActionKind]] = [
    (CREATE_LABEL_PREFIX, ActionKind.CREATE_AND_APPLY_LABEL),
    (LABEL_PREFIX, ActionKind.APPLY_LABEL),
    (MOVE_TO_PREFIX, ActionKind.MOVE_TO),
    (CREATE_FOLDER_PREFIX, ActionKind.CREATE_FOLDER),
    (LOG_NEW_LABELS_PREFIX, ActionKind.LOG_NEW_LABELS),
    (LOG_NEW_FOLDER_PREFIX, ActionKind.LOG_NEW_FOLDER),
    ("create_calendar_event:", ActionKind.CREATE_CALENDAR_EVENT),
    ("store_coupon:", ActionKind.STORE_COUPON),
    ("store_unsubscribe_url:", ActionKind.STORE_UNSUBSCRIBE_URL),
]

_EXACT_MAP: dict[str, ActionKind] = {
    MOVE_TO_SPAM_PREFIX: ActionKind.MOVE_TO_SPAM,
    MARK_AS_READ: ActionKind.MARK_AS_READ,
    "save_to_drafts": ActionKind.SAVE_TO_DRAFTS,
}


@dataclass(frozen=True, slots=True)
class ParsedAction:
    """Structured representation of an action string.

    Attributes:
        kind: The action type.
        value: Extracted parameter (e.g. label name, folder name).
            ``None`` for bare actions like ``mark_as_read``.
        raw: The original (un-normalised) action string.
    """

    kind: ActionKind
    value: str | None
    raw: str

    @property
    def is_imap(self) -> bool:
        """Whether this action requires an IMAP connection."""
        return self.kind in _IMAP_KINDS


_IMAP_KINDS = frozenset({
    ActionKind.APPLY_LABEL,
    ActionKind.CREATE_AND_APPLY_LABEL,
    ActionKind.MOVE_TO,
    ActionKind.MOVE_TO_SPAM,
    ActionKind.CREATE_FOLDER,
    ActionKind.MARK_AS_READ,
})


def parse_action(raw: str) -> ParsedAction:
    """Parse a raw action string into a structured ``ParsedAction``.

    Strips parenthetical annotations (e.g. ``" (confidence: 80%)"``)
    before matching prefixes.

    Args:
        raw: Raw action string as produced by AI plugins.

    Returns:
        A ``ParsedAction`` with ``kind``, ``value``, and the original ``raw``.
    """
    normalised = _ANNOTATION_RE.sub("", raw).strip()

    # Check exact matches first (bare actions)
    kind = _EXACT_MAP.get(normalised)
    if kind is not None:
        return ParsedAction(kind=kind, value=None, raw=raw)

    # Check prefixed actions (includes "create_draft_reply" as a special case)
    for prefix, kind in _PREFIX_MAP:
        if normalised.startswith(prefix):
            return ParsedAction(kind=kind, value=normalised[len(prefix):], raw=raw)

    # "create_draft_reply" may include annotations → bare match after strip
    if normalised.startswith("create_draft_reply"):
        return ParsedAction(kind=ActionKind.CREATE_DRAFT_REPLY, value=None, raw=raw)

    # "store_summary" may include annotations
    if normalised.startswith("store_summary"):
        return ParsedAction(kind=ActionKind.STORE_SUMMARY, value=None, raw=raw)

    return ParsedAction(kind=ActionKind.UNKNOWN, value=None, raw=raw)


def has_actionable_results(actions: list[str]) -> bool:
    """Return True if any action string represents meaningful work.

    Used to decide whether approval mode should gate execution.
    No-op strings like 'spam_check_passed' return False.
    """
    return any(parse_action(a).kind != ActionKind.UNKNOWN for a in actions)


def filter_imap_actions(actions: list[str]) -> list[ParsedAction]:
    """Return parsed actions that require an IMAP connection."""
    return [pa for pa in (parse_action(a) for a in actions) if pa.is_imap]


@dataclass(frozen=True, slots=True)
class MoveOutcome:
    """Result of executing IMAP actions that may include a move.

    Attributes:
        folder: The destination folder if a move occurred, else ``None``.
        new_uid: The UID assigned in the destination folder (from COPYUID),
            or ``None`` if the server did not provide it.
    """

    folder: str | None = None
    new_uid: str | None = None


async def execute_imap_actions(
    account: MailAccount,
    mail_uid: str,
    actions: list[str],
    *,
    source_folder: str = "INBOX",
    select_inbox: bool = False,
    propagate_connect_errors: bool = False,
) -> MoveOutcome:
    """Execute IMAP operations for a list of action strings.

    Opens a single IMAP connection, applies labels/flags first, then
    executes move operations (since moves change the folder context).
    Individual action failures within an established connection are logged
    but do not abort remaining actions (fail-open).

    Args:
        account: The mail account to connect to.
        mail_uid: The IMAP UID of the message to act on.
        actions: Action strings produced by AI plugins.
        source_folder: The IMAP folder the mail currently resides in.
            Used for SELECT before flag/move operations.  Ignored when
            ``select_inbox`` is True (backward compatibility).
        select_inbox: Whether to SELECT INBOX before executing actions.
            Deprecated in favour of ``source_folder``; kept for backward
            compatibility.  When True, overrides ``source_folder``.
        propagate_connect_errors: If True, IMAP connection errors propagate
            to the caller (enabling ARQ retry). If False, they are logged
            and the function returns silently.

    Returns:
        A ``MoveOutcome`` with the destination folder and new UID if the
        mail was moved, or an empty ``MoveOutcome`` if no move occurred.
        Callers should use this to update ``TrackedEmail.current_folder``
        and ``TrackedEmail.mail_uid``.
    """
    parsed = filter_imap_actions(actions)
    if not parsed:
        return MoveOutcome()

    log = logger.bind(mail_uid=mail_uid, account_id=str(account.id))
    log.info("executing_imap_actions", count=len(parsed), actions=[pa.raw for pa in parsed])

    try:
        conn = await connect_imap(account)
    except Exception:
        if propagate_connect_errors:
            raise
        log.exception("imap_connect_failed")
        return MoveOutcome()

    moved_to: str | None = None
    new_uid: str | None = None

    try:
        folder_to_select = "INBOX" if select_inbox else source_folder

        # Process labels and flags first (before moves)
        move_actions: list[ParsedAction] = []
        for pa in parsed:
            try:
                if pa.kind in (ActionKind.CREATE_AND_APPLY_LABEL, ActionKind.APPLY_LABEL):
                    await store_flags(conn, mail_uid, [pa.value], folder=folder_to_select)

                elif pa.kind is ActionKind.MARK_AS_READ:
                    await store_flags(conn, mail_uid, ["\\Seen"], folder=folder_to_select)

                elif pa.kind is ActionKind.CREATE_FOLDER:
                    await create_folder(conn, pa.value)
                    await invalidate_folder_cache(account.id)

                elif pa.kind in (ActionKind.MOVE_TO, ActionKind.MOVE_TO_SPAM):
                    move_actions.append(pa)

            except Exception:
                log.exception("action_execution_failed", action=pa.raw)

        # Execute moves last (only one move should win if multiple exist)
        for pa in move_actions:
            try:
                if pa.kind is ActionKind.MOVE_TO_SPAM:
                    dest = await resolve_folder(
                        conn, SPAM_FOLDERS, create_if_missing=True,
                    )
                    result = await move_message(conn, mail_uid, dest, source=folder_to_select)
                    if result.success:
                        moved_to = dest
                        new_uid = result.new_uid

                elif pa.kind is ActionKind.MOVE_TO:
                    # Skip no-op move when destination equals current folder
                    if pa.value and pa.value.upper() == folder_to_select.upper():
                        log.debug("move_skipped_same_folder", folder=pa.value)
                    else:
                        result = await move_message(conn, mail_uid, pa.value, source=folder_to_select)
                        if result.success:
                            moved_to = pa.value
                            new_uid = result.new_uid

            except Exception:
                log.exception("move_action_failed", action=pa.raw)

    finally:
        await safe_imap_logout(conn.mailbox)

    return MoveOutcome(folder=moved_to, new_uid=new_uid)
