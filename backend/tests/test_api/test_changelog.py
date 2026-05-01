"""Tests for the changelog API endpoint (Issue #109).

Verifies changelog parsing, endpoint responses, and health version field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from app.api.changelog import _parse_changelog

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


class TestChangelogEndpoint:
    """Tests for GET /api/changelog."""

    def test_changelog_enabled_returns_entries(self, tmp_path: Path) -> None:
        """Returns version and entries when enabled and file exists."""
        changelog_file = tmp_path / "CHANGELOG.md"
        changelog_file.write_text(SAMPLE_CHANGELOG)

        with (
            patch("app.api.changelog._CHANGELOG_PATH", changelog_file),
            patch("app.api.changelog.get_settings") as mock_settings,
        ):
            mock_settings.return_value.enable_changelog = True
            mock_settings.return_value.app_version = "1.2.0"

            import asyncio

            from app.api.changelog import get_changelog

            result = asyncio.get_event_loop().run_until_complete(get_changelog())

        assert result["version"] == "1.2.0"
        assert "1.2.0" in result["entries"]
        assert "1.1.0" in result["entries"]

    def test_changelog_disabled_raises_404(self) -> None:
        """Returns 404 when ENABLE_CHANGELOG=false."""
        from fastapi import HTTPException

        with patch("app.api.changelog.get_settings") as mock_settings:
            mock_settings.return_value.enable_changelog = False

            import asyncio

            from app.api.changelog import get_changelog

            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(get_changelog())
            assert exc_info.value.status_code == 404

    def test_changelog_missing_file_raises_404(self, tmp_path: Path) -> None:
        """Returns 404 when CHANGELOG.md does not exist."""
        from fastapi import HTTPException

        with (
            patch("app.api.changelog._CHANGELOG_PATH", tmp_path / "nonexistent.md"),
            patch("app.api.changelog.get_settings") as mock_settings,
        ):
            mock_settings.return_value.enable_changelog = True

            import asyncio

            from app.api.changelog import get_changelog

            with pytest.raises(HTTPException) as exc_info:
                asyncio.get_event_loop().run_until_complete(get_changelog())
            assert exc_info.value.status_code == 404


class TestHealthVersionField:
    """Tests for version field in /health response."""

    def test_health_response_schema_includes_version(self) -> None:
        """The health endpoint adds a version field to the response."""
        from app.core.config import get_settings

        settings = get_settings()
        assert hasattr(settings, "app_version")
        assert isinstance(settings.app_version, str)
        assert len(settings.app_version) > 0
