"""Tests for email summary filter evaluation (test area 14).

Covers: filter rules evaluation (urgency threshold, spam exclusion,
contacts-only, action-required, label/folder filters), disabled config,
and notification forwarding triggers.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.summary import _URGENCY_LEVELS, evaluate_summary_filter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db_with_config(config):
    """Create a mock DB that returns a SummaryFilterConfig."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = config
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _make_summary(urgency="medium", action_required=False):
    """Create a mock EmailSummary."""
    s = MagicMock()
    s.urgency = urgency
    s.action_required = action_required
    s.summary = "Test summary text"
    return s


def _make_filter_config(is_enabled=True, filter_rules=None):
    """Create a mock SummaryFilterConfig."""
    cfg = MagicMock()
    cfg.is_enabled = is_enabled
    cfg.user_id = uuid4()
    cfg.filter_rules = filter_rules or {}
    return cfg


# ---------------------------------------------------------------------------
# Test Area 14: Email Summary Filter Evaluation
# ---------------------------------------------------------------------------


class TestSummaryFilterEvaluation:
    """Tests for evaluate_summary_filter."""

    @pytest.mark.asyncio
    async def test_no_config_returns_false(self):
        """No SummaryFilterConfig means notifications are disabled."""
        db = _mock_db_with_config(None)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, False)
        assert result is False

    @pytest.mark.asyncio
    async def test_disabled_config_returns_false(self):
        """Disabled config returns False."""
        config = _make_filter_config(is_enabled=False)
        db = _mock_db_with_config(config)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, False)
        assert result is False

    @pytest.mark.asyncio
    async def test_enabled_no_rules_passes(self):
        """Enabled config with empty filter rules allows everything."""
        config = _make_filter_config(is_enabled=True, filter_rules={})
        db = _mock_db_with_config(config)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, False)
        assert result is True

    @pytest.mark.asyncio
    async def test_spam_excluded(self):
        """Spam emails are excluded when exclude_spam=True (default)."""
        config = _make_filter_config(filter_rules={"exclude_spam": True})
        db = _mock_db_with_config(config)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, is_spam=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_spam_not_excluded_when_disabled(self):
        """Spam emails pass when exclude_spam=False."""
        config = _make_filter_config(filter_rules={"exclude_spam": False})
        db = _mock_db_with_config(config)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, is_spam=True)
        assert result is True

    @pytest.mark.asyncio
    async def test_contacts_only_with_contact(self):
        """from_contacts_only passes when sender is a contact."""
        config = _make_filter_config(filter_rules={"from_contacts_only": True})
        db = _mock_db_with_config(config)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, is_from_contact=True, is_spam=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_contacts_only_without_contact(self):
        """from_contacts_only blocks when sender is not a contact."""
        config = _make_filter_config(filter_rules={"from_contacts_only": True})
        db = _mock_db_with_config(config)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, is_from_contact=False, is_spam=False)
        assert result is False

    @pytest.mark.asyncio
    async def test_action_required_only_with_action(self):
        """action_required_only passes when summary has action_required=True."""
        config = _make_filter_config(filter_rules={"action_required_only": True})
        db = _mock_db_with_config(config)
        summary = _make_summary(action_required=True)
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, False)
        assert result is True

    @pytest.mark.asyncio
    async def test_action_required_only_without_action(self):
        """action_required_only blocks when summary has action_required=False."""
        config = _make_filter_config(filter_rules={"action_required_only": True})
        db = _mock_db_with_config(config)
        summary = _make_summary(action_required=False)
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, False)
        assert result is False

    @pytest.mark.asyncio
    async def test_urgency_threshold_met(self):
        """Summary urgency >= threshold passes."""
        config = _make_filter_config(filter_rules={"min_urgency": "medium"})
        db = _mock_db_with_config(config)
        summary = _make_summary(urgency="high")
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, False)
        assert result is True

    @pytest.mark.asyncio
    async def test_urgency_threshold_not_met(self):
        """Summary urgency < threshold fails."""
        config = _make_filter_config(filter_rules={"min_urgency": "high"})
        db = _mock_db_with_config(config)
        summary = _make_summary(urgency="low")
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, False)
        assert result is False

    @pytest.mark.asyncio
    async def test_urgency_critical_always_passes(self):
        """Critical urgency always passes any threshold."""
        config = _make_filter_config(filter_rules={"min_urgency": "critical"})
        db = _mock_db_with_config(config)
        summary = _make_summary(urgency="critical")
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, False)
        assert result is True

    @pytest.mark.asyncio
    async def test_label_filter_match(self):
        """Label filter passes when email has a matching label."""
        config = _make_filter_config(filter_rules={"labels": ["important", "urgent"]})
        db = _mock_db_with_config(config)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, ["Important", "work"], None, False, False)
        assert result is True  # case-insensitive match on "important"

    @pytest.mark.asyncio
    async def test_label_filter_no_match(self):
        """Label filter fails when email has no matching label."""
        config = _make_filter_config(filter_rules={"labels": ["important"]})
        db = _mock_db_with_config(config)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, ["work", "project"], None, False, False)
        assert result is False

    @pytest.mark.asyncio
    async def test_folder_filter_match(self):
        """Folder filter passes when email folder matches."""
        config = _make_filter_config(filter_rules={"folders": ["Work", "Urgent"]})
        db = _mock_db_with_config(config)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, [], "work", False, False)
        assert result is True  # case-insensitive

    @pytest.mark.asyncio
    async def test_folder_filter_no_match(self):
        """Folder filter fails when email folder does not match."""
        config = _make_filter_config(filter_rules={"folders": ["Urgent"]})
        db = _mock_db_with_config(config)
        summary = _make_summary()
        result = await evaluate_summary_filter(db, uuid4(), summary, [], "Archive", False, False)
        assert result is False

    @pytest.mark.asyncio
    async def test_combined_filters(self):
        """Multiple filter rules are AND-combined (all must pass)."""
        config = _make_filter_config(
            filter_rules={
                "exclude_spam": True,
                "min_urgency": "medium",
                "action_required_only": True,
            }
        )
        db = _mock_db_with_config(config)
        summary = _make_summary(urgency="high", action_required=True)
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, is_spam=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_combined_filters_one_fails(self):
        """One failing filter in AND-combination blocks the notification."""
        config = _make_filter_config(
            filter_rules={
                "exclude_spam": True,
                "min_urgency": "critical",
                "action_required_only": True,
            }
        )
        db = _mock_db_with_config(config)
        # urgency=medium < critical -> fails
        summary = _make_summary(urgency="medium", action_required=True)
        result = await evaluate_summary_filter(db, uuid4(), summary, [], None, False, is_spam=False)
        assert result is False


class TestUrgencyLevels:
    """Urgency level ordering consistency."""

    def test_level_ordering(self):
        assert _URGENCY_LEVELS["low"] < _URGENCY_LEVELS["medium"]
        assert _URGENCY_LEVELS["medium"] < _URGENCY_LEVELS["high"]
        assert _URGENCY_LEVELS["high"] < _URGENCY_LEVELS["critical"]

    def test_all_levels_present(self):
        for level in ("low", "medium", "high", "critical"):
            assert level in _URGENCY_LEVELS
