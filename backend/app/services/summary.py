"""Email summary service.

Handles summary storage and filter evaluation for notification forwarding.
"""

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailSummary, SummaryFilterConfig

logger = structlog.get_logger()

# Urgency level ordering for threshold comparison
_URGENCY_LEVELS = {"low": 0, "medium": 1, "high": 2, "critical": 3}


async def evaluate_summary_filter(
    db: AsyncSession,
    user_id: Any,
    summary: EmailSummary,
    labels: list[str],
    folder: str | None,
    is_from_contact: bool,
    is_spam: bool,
) -> bool:
    """Evaluate whether a summary should trigger a notification.

    Checks the user's SummaryFilterConfig rules against the email/summary.
    Returns True if the summary matches the filter criteria and notifications
    are enabled, False otherwise.
    """
    stmt = select(SummaryFilterConfig).where(SummaryFilterConfig.user_id == user_id)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if config is None or not config.is_enabled:
        return False

    rules = config.filter_rules or {}

    # Check spam exclusion
    if rules.get("exclude_spam", True) and is_spam:
        return False

    # Check contacts-only filter
    if rules.get("from_contacts_only", False) and not is_from_contact:
        return False

    # Check action_required filter
    if rules.get("action_required_only", False) and not summary.action_required:
        return False

    # Check urgency threshold
    min_urgency = rules.get("min_urgency", "low")
    if _URGENCY_LEVELS.get(summary.urgency, 0) < _URGENCY_LEVELS.get(min_urgency, 0):
        return False

    # Check label filter
    filter_labels = rules.get("labels")
    if filter_labels:
        label_set = {lbl.lower() for lbl in labels}
        filter_set = {lbl.lower() for lbl in filter_labels}
        if not label_set & filter_set:
            return False

    # Check folder filter
    filter_folders = rules.get("folders")
    if filter_folders and folder:
        folder_set = {f.lower() for f in filter_folders}
        if folder.lower() not in folder_set:
            return False

    return True
