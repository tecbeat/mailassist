"""Tests for app.services.spam."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.spam import BlocklistEntryType
from app.services.spam import _extract_domain, get_blocklist_context, is_blocked

# ---------------------------------------------------------------------------
# _extract_domain
# ---------------------------------------------------------------------------


class TestExtractDomain:
    def test_normal_email(self):
        assert _extract_domain("user@example.com") == "example.com"

    def test_no_at_sign(self):
        assert _extract_domain("nope") is None

    def test_uppercase_domain(self):
        assert _extract_domain("user@EXAMPLE.COM") == "example.com"

    def test_multiple_at_signs(self):
        # rsplit ensures only last @ is used
        assert _extract_domain("weird@name@example.com") == "example.com"


# ---------------------------------------------------------------------------
# is_blocked
# ---------------------------------------------------------------------------


class TestIsBlocked:
    @pytest.mark.asyncio
    async def test_blocked_by_email(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1
        mock_db.execute.return_value = mock_result

        result = await is_blocked(mock_db, uuid4(), "spam@evil.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_blocked_by_domain(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1
        mock_db.execute.return_value = mock_result

        result = await is_blocked(mock_db, uuid4(), "user@evil.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_not_blocked(self):
        mock_db = AsyncMock()
        # First call: count query returns 0
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_db.execute.return_value = count_result

        result = await is_blocked(mock_db, uuid4(), "legit@good.com")
        assert result is False

    @pytest.mark.asyncio
    async def test_blocked_by_subject_pattern(self):
        mock_db = AsyncMock()
        # First call: count query returns 0
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        # Second call: pattern query
        pattern_result = MagicMock()
        pattern_result.scalars.return_value.all.return_value = ["free money"]

        mock_db.execute.side_effect = [count_result, pattern_result]

        result = await is_blocked(mock_db, uuid4(), "someone@example.com", subject="Get Free Money Now!")
        assert result is True

    @pytest.mark.asyncio
    async def test_subject_pattern_no_match(self):
        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        pattern_result = MagicMock()
        pattern_result.scalars.return_value.all.return_value = ["buy now"]

        mock_db.execute.side_effect = [count_result, pattern_result]

        result = await is_blocked(mock_db, uuid4(), "someone@example.com", subject="Meeting tomorrow")
        assert result is False

    @pytest.mark.asyncio
    async def test_no_subject_skips_pattern_check(self):
        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        mock_db.execute.return_value = count_result

        result = await is_blocked(mock_db, uuid4(), "someone@example.com")
        assert result is False
        # Only one DB call (the count query), no pattern query
        assert mock_db.execute.call_count == 1


# ---------------------------------------------------------------------------
# get_blocklist_context
# ---------------------------------------------------------------------------


class TestGetBlocklistContext:
    @pytest.mark.asyncio
    async def test_returns_compact_list(self):
        mock_db = AsyncMock()
        row1 = MagicMock()
        row1.entry_type = BlocklistEntryType.EMAIL
        row1.value = "spam@evil.com"
        row2 = MagicMock()
        row2.entry_type = BlocklistEntryType.DOMAIN
        row2.value = "evil.com"

        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([row1, row2]))
        mock_db.execute.return_value = mock_result

        result = await get_blocklist_context(mock_db, uuid4())
        assert result == [
            {"type": "email", "value": "spam@evil.com"},
            {"type": "domain", "value": "evil.com"},
        ]

    @pytest.mark.asyncio
    async def test_empty_blocklist(self):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        mock_db.execute.return_value = mock_result

        result = await get_blocklist_context(mock_db, uuid4())
        assert result == []
