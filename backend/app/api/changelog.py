"""Changelog endpoint.

Serves parsed CHANGELOG.md content as JSON. Controlled by ENABLE_CHANGELOG setting.
The user's ``last_seen_version`` is stored in ``user_settings`` so the
What's New dialog works consistently across browsers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUserId, DbSession  # noqa: TC001
from app.core.config import get_settings
from app.models.user import UserSettings

if TYPE_CHECKING:
    from uuid import UUID

router = APIRouter(prefix="/api", tags=["changelog"])


def _find_changelog() -> Path:
    """Locate CHANGELOG.md by walking up from the module file."""
    current = Path(__file__).resolve().parent
    for _ in range(5):
        candidate = current / "CHANGELOG.md"
        if candidate.exists():
            return candidate
        current = current.parent
    # Fallback: CWD
    return Path.cwd() / "CHANGELOG.md"


_CHANGELOG_PATH = _find_changelog()


def _parse_changelog(text: str) -> dict[str, str]:
    """Parse Keep a Changelog format into a version-keyed dict of markdown content.

    Returns entries in file order (newest first).
    """
    entries: dict[str, str] = {}
    current_version: str | None = None
    lines: list[str] = []

    for line in text.splitlines():
        match = re.match(r"^## \[(.+?)]", line)
        if match:
            if current_version and lines:
                entries[current_version] = "\n".join(lines).strip()
            current_version = match.group(1)
            lines = []
        elif current_version is not None:
            lines.append(line)

    if current_version and lines:
        entries[current_version] = "\n".join(lines).strip()

    return entries


def _entries_since(entries: dict[str, str], since_version: str | None) -> dict[str, str]:
    """Return only entries newer than ``since_version``.

    Entries are ordered newest-first in the changelog.  Returns all entries
    up to (but not including) ``since_version``.  If ``since_version`` is
    None or not found, returns only the latest entry.
    """
    if not entries:
        return {}

    if since_version is None or since_version not in entries:
        # First visit or unknown version — show only the latest
        first_key = next(iter(entries))
        return {first_key: entries[first_key]}

    result: dict[str, str] = {}
    for version, content in entries.items():
        if version == since_version:
            break
        result[version] = content

    return result


async def _get_last_seen(db: DbSession, user_id: UUID) -> str | None:
    """Read the user's last seen changelog version from the database."""
    stmt = select(UserSettings.last_seen_version).where(UserSettings.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _set_last_seen(db: DbSession, user_id: UUID, version: str) -> None:
    """Update the user's last seen changelog version in the database."""
    stmt = select(UserSettings).where(UserSettings.user_id == user_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings:
        settings.last_seen_version = version
    else:
        settings = UserSettings(user_id=user_id, last_seen_version=version)
        db.add(settings)
    await db.commit()


@router.get("/changelog")
async def get_changelog(
    user_id: CurrentUserId,
    db: DbSession,
) -> dict[str, object]:
    """Return parsed changelog entries since the user's last seen version.

    Returns 404 when the changelog feature is disabled or the file is missing.
    """
    settings = get_settings()
    if not settings.enable_changelog:
        raise HTTPException(status_code=404, detail="Changelog disabled")

    if not _CHANGELOG_PATH.exists():
        raise HTTPException(status_code=404, detail="Changelog not found")

    since_version = await _get_last_seen(db, user_id)
    content = _CHANGELOG_PATH.read_text(encoding="utf-8")
    all_entries = _parse_changelog(content)
    entries = _entries_since(all_entries, since_version)

    return {"version": settings.version, "entries": entries}


@router.post("/changelog/dismiss")
async def dismiss_changelog(
    user_id: CurrentUserId,
    db: DbSession,
) -> dict[str, str]:
    """Mark the current version as seen by the user."""
    settings = get_settings()
    await _set_last_seen(db, user_id, settings.version)
    return {"status": "ok"}
