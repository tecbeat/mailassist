"""Changelog endpoint.

Serves parsed CHANGELOG.md content as JSON. Controlled by ENABLE_CHANGELOG setting.
"""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings

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
    """Parse Keep a Changelog format into a version-keyed dict of markdown content."""
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


@router.get("/changelog")
async def get_changelog() -> dict[str, object]:
    """Return parsed changelog entries keyed by version.

    Returns 404 when the changelog feature is disabled or the file is missing.
    """
    settings = get_settings()
    if not settings.enable_changelog:
        raise HTTPException(status_code=404, detail="Changelog disabled")

    if not _CHANGELOG_PATH.exists():
        raise HTTPException(status_code=404, detail="Changelog not found")

    content = _CHANGELOG_PATH.read_text(encoding="utf-8")
    entries = _parse_changelog(content)

    return {"version": settings.app_version, "entries": entries}
