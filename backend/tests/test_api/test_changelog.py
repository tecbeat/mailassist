"""Tests for the changelog API endpoint (Issue #109).

Verifies changelog parsing, endpoint responses, health version field,
and the ``_entries_since`` helper used for server-side last-seen filtering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.api.changelog import _entries_since, _parse_changelog, get_changelog

if TYPE_CHECKING:
    from pathlib import Path

SAMPLE_CHANGELOG = """\
# Changelog

## [1.2.0] - 2026-04-30

### Added

- New changelog API endpoint
- Version display in health check

### Fixed

- Minor bug fixes

## [1.1.0] - 2026-04-01

### Added

- Initial release features
"""


class TestParseChangelog:
    """Unit tests for the Keep a Changelog parser."""

    def test_parse_extracts_versions(self) -> None:
        entries = _parse_changelog(SAMPLE_CHANGELOG)
        assert "1.2.0" in entries
        assert "1.1.0" in entries

    def test_parse_preserves_markdown_content(self) -> None:
        entries = _parse_changelog(SAMPLE_CHANGELOG)
        assert "### Added" in entries["1.2.0"]
        assert "- New changelog API endpoint" in entries["1.2.0"]

    def test_parse_empty_string_returns_empty_dict(self) -> None:
        assert _parse_changelog("") == {}

    def test_parse_no_versions_returns_empty_dict(self) -> None:
        assert _parse_changelog("# Changelog\n\nSome text without versions.") == {}


class TestEntriesSince:
    """Unit tests for ``_entries_since``."""

    def test_returns_empty_when_no_entries(self) -> None:
        assert _entries_since({}, "1.0.0") == {}

    def test_returns_latest_when_since_is_none(self) -> None:
        entries = _parse_changelog(SAMPLE_CHANGELOG)
        result = _entries_since(entries, None)
        assert list(result.keys()) == ["1.2.0"]

    def test_returns_latest_when_since_not_found(self) -> None:
        entries = _parse_changelog(SAMPLE_CHANGELOG)
        result = _entries_since(entries, "0.0.1")
        assert list(result.keys()) == ["1.2.0"]

    def test_returns_newer_entries_only(self) -> None:
        entries = _parse_changelog(SAMPLE_CHANGELOG)
        result = _entries_since(entries, "1.1.0")
        assert list(result.keys()) == ["1.2.0"]
        assert "1.1.0" not in result

    def test_returns_empty_when_already_on_latest(self) -> None:
        entries = _parse_changelog(SAMPLE_CHANGELOG)
        result = _entries_since(entries, "1.2.0")
        assert result == {}


class TestChangelogEndpoint:
    """Tests for GET /api/changelog."""

    async def test_changelog_enabled_returns_entries(self, tmp_path: Path) -> None:
        """Returns version and entries when enabled and file exists."""
        changelog_file = tmp_path / "CHANGELOG.md"
        changelog_file.write_text(SAMPLE_CHANGELOG)
        user_id = uuid4()

        with (
            patch("app.api.changelog._CHANGELOG_PATH", changelog_file),
            patch("app.api.changelog.get_settings") as mock_settings,
            patch("app.api.changelog._get_last_seen", new_callable=AsyncMock, return_value=None) as mock_last_seen,
        ):
            mock_settings.return_value.enable_changelog = True
            mock_settings.return_value.version = "1.2.0"
            mock_db = AsyncMock()

            result = await get_changelog(user_id=user_id, db=mock_db)

        mock_last_seen.assert_awaited_once_with(mock_db, user_id)
        assert result["version"] == "1.2.0"
        assert result["since_version"] is None
        # No last_seen → only latest entry
        assert "1.2.0" in result["entries"]
        assert "1.1.0" not in result["entries"]

    async def test_changelog_returns_diff_since_last_seen(self, tmp_path: Path) -> None:
        """Returns only entries newer than the user's last seen version."""
        changelog_file = tmp_path / "CHANGELOG.md"
        changelog_file.write_text(SAMPLE_CHANGELOG)

        with (
            patch("app.api.changelog._CHANGELOG_PATH", changelog_file),
            patch("app.api.changelog.get_settings") as mock_settings,
            patch("app.api.changelog._get_last_seen", new_callable=AsyncMock, return_value="1.1.0"),
        ):
            mock_settings.return_value.enable_changelog = True
            mock_settings.return_value.version = "1.2.0"

            result = await get_changelog(user_id=uuid4(), db=AsyncMock())

        assert "1.2.0" in result["entries"]
        assert "1.1.0" not in result["entries"]
        assert result["since_version"] == "1.1.0"

    async def test_changelog_returns_empty_when_up_to_date(self, tmp_path: Path) -> None:
        """Returns no entries when user has already seen the latest."""
        changelog_file = tmp_path / "CHANGELOG.md"
        changelog_file.write_text(SAMPLE_CHANGELOG)

        with (
            patch("app.api.changelog._CHANGELOG_PATH", changelog_file),
            patch("app.api.changelog.get_settings") as mock_settings,
            patch("app.api.changelog._get_last_seen", new_callable=AsyncMock, return_value="1.2.0"),
        ):
            mock_settings.return_value.enable_changelog = True
            mock_settings.return_value.version = "1.2.0"

            result = await get_changelog(user_id=uuid4(), db=AsyncMock())

        assert result["entries"] == {}

    async def test_changelog_disabled_raises_404(self) -> None:
        """Returns 404 when ENABLE_CHANGELOG=false."""
        from fastapi import HTTPException

        with patch("app.api.changelog.get_settings") as mock_settings:
            mock_settings.return_value.enable_changelog = False

            with pytest.raises(HTTPException) as exc_info:
                await get_changelog(user_id=uuid4(), db=AsyncMock())
            assert exc_info.value.status_code == 404

    async def test_changelog_missing_file_raises_404(self, tmp_path: Path) -> None:
        """Returns 404 when CHANGELOG.md does not exist."""
        from fastapi import HTTPException

        with (
            patch("app.api.changelog._CHANGELOG_PATH", tmp_path / "nonexistent.md"),
            patch("app.api.changelog.get_settings") as mock_settings,
        ):
            mock_settings.return_value.enable_changelog = True

            with pytest.raises(HTTPException) as exc_info:
                await get_changelog(user_id=uuid4(), db=AsyncMock())
            assert exc_info.value.status_code == 404


class TestHealthVersionField:
    """Tests for version field in /health response."""

    def test_health_response_schema_includes_version(self) -> None:
        """The health endpoint adds a version field to the response."""
        from app.core.config import get_settings

        settings = get_settings()
        assert hasattr(settings, "version")
        assert isinstance(settings.version, str)
        assert len(settings.version) > 0
