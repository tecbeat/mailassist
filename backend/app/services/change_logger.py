"""Label and folder change logging.

Persists ``LabelChangeLog`` and ``FolderChangeLog`` records from action
strings produced by AI plugins.  Used by both ``mail_processor`` (auto-mode)
and ``approval_executor`` (after user approval).
"""

from __future__ import annotations

from uuid import UUID

import structlog

from app.core.database import get_session
from app.models import FolderChangeLog, LabelChangeLog
from app.services.imap_actions import ActionKind, parse_action

logger = structlog.get_logger()


def _deduplicate(items: list[str]) -> list[str]:
    """Case-insensitive deduplication preserving first occurrence order."""
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def extract_new_labels(actions: list[str]) -> list[str]:
    """Extract label names from ``log_new_labels`` and ``create_and_apply_label`` actions.

    Returns a deduplicated (case-insensitive) list preserving first occurrence.
    """
    new_labels: list[str] = []
    for action in actions:
        pa = parse_action(action)
        if pa.kind is ActionKind.LOG_NEW_LABELS and pa.value:
            new_labels.extend(l.strip() for l in pa.value.split(",") if l.strip())
        elif pa.kind is ActionKind.CREATE_AND_APPLY_LABEL and pa.value:
            stripped = pa.value.strip()
            if stripped:
                new_labels.append(stripped)
    return _deduplicate(new_labels)


def extract_new_folders(actions: list[str]) -> list[str]:
    """Extract folder names from ``log_new_folder`` and ``create_folder`` actions.

    Returns a deduplicated (case-insensitive) list preserving first occurrence.
    """
    new_folders: list[str] = []
    for action in actions:
        pa = parse_action(action)
        if pa.kind in (ActionKind.LOG_NEW_FOLDER, ActionKind.CREATE_FOLDER) and pa.value:
            stripped = pa.value.strip()
            if stripped:
                new_folders.append(stripped)
    return _deduplicate(new_folders)


async def save_new_labels(
    user_id: UUID,
    account_id: UUID,
    actions: list[str],
) -> None:
    """Persist new label records from action strings.

    Opens its own DB session because this typically runs after the main
    transaction has already committed.
    """
    labels = extract_new_labels(actions)
    if not labels:
        return

    async for db in get_session():
        for label in labels:
            db.add(LabelChangeLog(
                user_id=user_id,
                mail_account_id=account_id,
                label=label,
            ))
        try:
            await db.commit()
        except Exception:
            logger.exception(
                "save_new_labels_failed",
                user_id=str(user_id),
                account_id=str(account_id),
                labels=labels,
            )
            return
        logger.info(
            "new_labels_logged",
            user_id=str(user_id),
            account_id=str(account_id),
            labels=labels,
        )


async def save_new_folders(
    user_id: UUID,
    account_id: UUID,
    actions: list[str],
) -> None:
    """Persist new folder records from action strings.

    Opens its own DB session because this typically runs after the main
    transaction has already committed.
    """
    folders = extract_new_folders(actions)
    if not folders:
        return

    async for db in get_session():
        for folder in folders:
            db.add(FolderChangeLog(
                user_id=user_id,
                mail_account_id=account_id,
                folder=folder,
            ))
        try:
            await db.commit()
        except Exception:
            logger.exception(
                "save_new_folders_failed",
                user_id=str(user_id),
                account_id=str(account_id),
                folders=folders,
            )
            return
        logger.info(
            "new_folders_logged",
            user_id=str(user_id),
            account_id=str(account_id),
            folders=folders,
        )
