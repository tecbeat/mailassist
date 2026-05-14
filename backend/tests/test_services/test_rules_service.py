"""Tests for the rule engine service.

Covers: _rule_action_to_imap, _resolve_field, _compare (all operators),
_compare_bool, _compare_numeric, _match_regex, _is_empty, _to_bool,
_evaluate_group (AND/OR nesting), and evaluate_rules (DB integration).
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.plugins.base import MailContext
from app.schemas.rules import ConditionGroup, FieldOperator, RuleAction
from app.services.rules import (
    RuleEvaluationResult,
    _compare,
    _compare_bool,
    _compare_numeric,
    _is_empty,
    _match_regex,
    _resolve_field,
    _rule_action_to_imap,
    _to_bool,
    evaluate_conditions,
    evaluate_rules,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context(**overrides) -> MailContext:
    """Build a MailContext with sensible defaults."""
    defaults = {
        "user_id": "user-1",
        "account_id": "acct-1",
        "mail_uid": "uid-1",
        "sender": "alice@example.com",
        "sender_name": "Alice",
        "recipient": "me@example.com",
        "subject": "Hello World",
        "body": "This is the body text.",
        "body_plain": "This is the body text.",
        "body_html": "<p>Hello</p>",
        "headers": {"From": "alice@example.com", "Cc": "bob@example.com", "X-Custom": "val"},
        "date": "2026-01-15T10:00:00Z",
        "has_attachments": False,
        "attachment_names": [],
        "account_name": "Main",
        "account_email": "me@example.com",
        "existing_labels": [],
        "existing_folders": ["INBOX"],
        "excluded_folders": [],
        "folder_separator": "/",
        "mail_size": 1024,
        "thread_length": 1,
        "is_reply": False,
        "is_forwarded": False,
        "contact": {"display_name": "Alice Smith", "organization": "Acme Corp"},
    }
    defaults.update(overrides)
    return MailContext(**defaults)


def _cond(field: str, op: str, value=None) -> dict:
    return {"field": field, "op": op, "value": value}


def _group(operator: str, rules: list) -> dict:
    return {"operator": operator, "rules": rules}


# ---------------------------------------------------------------------------
# _rule_action_to_imap
# ---------------------------------------------------------------------------


class TestRuleActionToImap:
    """Test conversion of RuleAction to IMAP action strings."""

    def test_move_action(self):
        action = RuleAction(type="move", target="Archive")
        assert _rule_action_to_imap(action) == "move_to:Archive"

    def test_label_action(self):
        action = RuleAction(type="label", value="important")
        assert _rule_action_to_imap(action) == "label:important"

    def test_mark_read_action(self):
        action = RuleAction(type="mark_read")
        assert _rule_action_to_imap(action) == "mark_as_read"

    def test_delete_action(self):
        action = RuleAction(type="delete")
        assert _rule_action_to_imap(action) == "move_to_spam"

    def test_unsupported_action_returns_none(self):
        action = RuleAction(type="flag")
        assert _rule_action_to_imap(action) is None

    def test_move_without_target_returns_none(self):
        action = MagicMock()
        action.type = MagicMock()
        action.type.value = "move"
        # Simulate ActionType.MOVE lookup returning "move_to:"
        from app.schemas.rules import ActionType

        action.type = ActionType.MOVE
        action.target = None
        action.value = None
        assert _rule_action_to_imap(action) is None


# ---------------------------------------------------------------------------
# _resolve_field
# ---------------------------------------------------------------------------


class TestResolveField:
    """Test field name resolution from MailContext."""

    def test_from_field(self):
        ctx = _make_context(sender="test@example.com")
        assert _resolve_field("from", ctx) == "test@example.com"

    def test_subject_field(self):
        ctx = _make_context(subject="Test Subject")
        assert _resolve_field("subject", ctx) == "Test Subject"

    def test_header_field(self):
        ctx = _make_context(headers={"X-Custom": "custom-value"})
        assert _resolve_field("header:X-Custom", ctx) == "custom-value"

    def test_missing_header_returns_empty(self):
        ctx = _make_context(headers={})
        assert _resolve_field("header:X-Missing", ctx) == ""

    def test_contact_name(self):
        ctx = _make_context(contact={"display_name": "Jane Doe"})
        assert _resolve_field("contact_name", ctx) == "Jane Doe"

    def test_contact_org(self):
        ctx = _make_context(contact={"organization": "Acme"})
        assert _resolve_field("contact_org", ctx) == "Acme"

    def test_contact_name_no_contact(self):
        ctx = _make_context(contact=None)
        assert _resolve_field("contact_name", ctx) == ""

    def test_has_attachment(self):
        ctx = _make_context(has_attachments=True)
        assert _resolve_field("has_attachment", ctx) is True

    def test_unknown_field_returns_empty(self):
        ctx = _make_context()
        assert _resolve_field("nonexistent", ctx) == ""

    def test_size_field(self):
        ctx = _make_context(mail_size=5000)
        assert _resolve_field("size", ctx) == 5000

    def test_is_reply(self):
        ctx = _make_context(is_reply=True)
        assert _resolve_field("is_reply", ctx) is True

    def test_cc_field(self):
        ctx = _make_context(headers={"Cc": "bob@example.com"})
        assert _resolve_field("cc", ctx) == "bob@example.com"


# ---------------------------------------------------------------------------
# _compare
# ---------------------------------------------------------------------------


class TestCompare:
    """Test comparison operators."""

    def test_equals(self):
        assert _compare("hello", FieldOperator.EQUALS, "hello") is True
        assert _compare("hello", FieldOperator.EQUALS, "HELLO") is True
        assert _compare("hello", FieldOperator.EQUALS, "world") is False

    def test_not_equals(self):
        assert _compare("hello", FieldOperator.NOT_EQUALS, "world") is True
        assert _compare("hello", FieldOperator.NOT_EQUALS, "hello") is False

    def test_contains(self):
        assert _compare("hello world", FieldOperator.CONTAINS, "world") is True
        assert _compare("hello world", FieldOperator.CONTAINS, "xyz") is False

    def test_not_contains(self):
        assert _compare("hello world", FieldOperator.NOT_CONTAINS, "xyz") is True
        assert _compare("hello world", FieldOperator.NOT_CONTAINS, "world") is False

    def test_starts_with(self):
        assert _compare("hello world", FieldOperator.STARTS_WITH, "hello") is True
        assert _compare("hello world", FieldOperator.STARTS_WITH, "world") is False

    def test_ends_with(self):
        assert _compare("hello world", FieldOperator.ENDS_WITH, "world") is True
        assert _compare("hello world", FieldOperator.ENDS_WITH, "hello") is False

    def test_is_empty(self):
        assert _compare("", FieldOperator.IS_EMPTY, None) is True
        assert _compare("hello", FieldOperator.IS_EMPTY, None) is False
        assert _compare(None, FieldOperator.IS_EMPTY, None) is True
        assert _compare([], FieldOperator.IS_EMPTY, None) is True

    def test_is_not_empty(self):
        assert _compare("hello", FieldOperator.IS_NOT_EMPTY, None) is True
        assert _compare("", FieldOperator.IS_NOT_EMPTY, None) is False

    def test_greater_than(self):
        assert _compare(100, FieldOperator.GREATER_THAN, 50) is True
        assert _compare(10, FieldOperator.GREATER_THAN, 50) is False

    def test_less_than(self):
        assert _compare(10, FieldOperator.LESS_THAN, 50) is True
        assert _compare(100, FieldOperator.LESS_THAN, 50) is False

    def test_matches_regex(self):
        assert _compare("hello123", FieldOperator.MATCHES_REGEX, r"\d+") is True
        assert _compare("hello", FieldOperator.MATCHES_REGEX, r"\d+") is False

    def test_list_field_any_match(self):
        assert _compare(["report.pdf", "image.png"], FieldOperator.CONTAINS, "report") is True
        assert _compare(["report.pdf", "image.png"], FieldOperator.CONTAINS, "missing") is False


# ---------------------------------------------------------------------------
# _compare_bool
# ---------------------------------------------------------------------------


class TestCompareBool:
    """Test boolean comparison."""

    def test_equals_true(self):
        assert _compare_bool(True, FieldOperator.EQUALS, True) is True
        assert _compare_bool(True, FieldOperator.EQUALS, "true") is True

    def test_equals_false(self):
        assert _compare_bool(False, FieldOperator.EQUALS, False) is True

    def test_not_equals(self):
        assert _compare_bool(True, FieldOperator.NOT_EQUALS, False) is True

    def test_unsupported_op(self):
        assert _compare_bool(True, FieldOperator.CONTAINS, True) is False


# ---------------------------------------------------------------------------
# _compare_numeric
# ---------------------------------------------------------------------------


class TestCompareNumeric:
    """Test numeric comparisons with type coercion."""

    def test_greater_than(self):
        assert _compare_numeric(100, FieldOperator.GREATER_THAN, 50) is True
        assert _compare_numeric(10, FieldOperator.GREATER_THAN, 50) is False

    def test_less_than(self):
        assert _compare_numeric(10, FieldOperator.LESS_THAN, 50) is True

    def test_string_coercion(self):
        assert _compare_numeric("100", FieldOperator.GREATER_THAN, "50") is True

    def test_invalid_value_returns_false(self):
        assert _compare_numeric("abc", FieldOperator.GREATER_THAN, 50) is False

    def test_unsupported_op(self):
        assert _compare_numeric(10, FieldOperator.EQUALS, 10) is False


# ---------------------------------------------------------------------------
# _match_regex
# ---------------------------------------------------------------------------


class TestMatchRegex:
    """Test regex matching with safety limits."""

    def test_basic_match(self):
        assert _match_regex("hello123", r"\d+") is True

    def test_no_match(self):
        assert _match_regex("hello", r"\d+") is False

    def test_empty_pattern(self):
        assert _match_regex("hello", "") is False

    def test_none_pattern(self):
        assert _match_regex("hello", None) is False

    @patch("app.services.rules.get_settings")
    def test_too_long_pattern_rejected(self, mock_settings):
        settings = MagicMock()
        settings.rules_max_pattern_length = 10
        settings.rules_max_text_length = 1000
        mock_settings.return_value = settings
        assert _match_regex("hello", "a" * 20) is False

    def test_invalid_regex(self):
        assert _match_regex("hello", "[invalid") is False


# ---------------------------------------------------------------------------
# _is_empty / _to_bool
# ---------------------------------------------------------------------------


class TestIsEmpty:
    def test_none(self):
        assert _is_empty(None) is True

    def test_empty_string(self):
        assert _is_empty("") is True

    def test_whitespace_string(self):
        assert _is_empty("   ") is True

    def test_non_empty_string(self):
        assert _is_empty("hello") is False

    def test_empty_list(self):
        assert _is_empty([]) is True

    def test_non_empty_list(self):
        assert _is_empty(["a"]) is False

    def test_false_bool(self):
        assert _is_empty(False) is True

    def test_true_bool(self):
        assert _is_empty(True) is False


class TestToBool:
    def test_bool_passthrough(self):
        assert _to_bool(True) is True
        assert _to_bool(False) is False

    def test_string_true_values(self):
        assert _to_bool("true") is True
        assert _to_bool("1") is True
        assert _to_bool("yes") is True
        assert _to_bool("True") is True

    def test_string_false_values(self):
        assert _to_bool("false") is False
        assert _to_bool("no") is False
        assert _to_bool("0") is False

    def test_int_coercion(self):
        assert _to_bool(1) is True
        assert _to_bool(0) is False


# ---------------------------------------------------------------------------
# evaluate_conditions (AND/OR nesting)
# ---------------------------------------------------------------------------


class TestEvaluateConditions:
    """Test nested condition group evaluation."""

    def test_simple_and_all_match(self):
        ctx = _make_context(sender="alice@example.com", subject="Newsletter")
        cond = ConditionGroup.model_validate(
            _group("AND", [_cond("from", "contains", "alice"), _cond("subject", "contains", "news")])
        )
        assert evaluate_conditions(cond, ctx) is True

    def test_simple_and_partial_match(self):
        ctx = _make_context(sender="alice@example.com", subject="Hello")
        cond = ConditionGroup.model_validate(
            _group("AND", [_cond("from", "contains", "alice"), _cond("subject", "contains", "news")])
        )
        assert evaluate_conditions(cond, ctx) is False

    def test_simple_or_one_matches(self):
        ctx = _make_context(sender="alice@example.com", subject="Hello")
        cond = ConditionGroup.model_validate(
            _group("OR", [_cond("from", "contains", "alice"), _cond("subject", "contains", "news")])
        )
        assert evaluate_conditions(cond, ctx) is True

    def test_simple_or_none_match(self):
        ctx = _make_context(sender="bob@example.com", subject="Hello")
        cond = ConditionGroup.model_validate(
            _group("OR", [_cond("from", "contains", "alice"), _cond("subject", "contains", "news")])
        )
        assert evaluate_conditions(cond, ctx) is False

    def test_nested_groups(self):
        ctx = _make_context(sender="alice@example.com", subject="Newsletter", has_attachments=True)
        cond = ConditionGroup.model_validate(
            _group(
                "AND",
                [
                    _cond("from", "contains", "alice"),
                    _group("OR", [_cond("subject", "contains", "news"), _cond("has_attachment", "equals", True)]),
                ],
            )
        )
        assert evaluate_conditions(cond, ctx) is True


# ---------------------------------------------------------------------------
# evaluate_rules (async, DB integration)
# ---------------------------------------------------------------------------


class TestEvaluateRules:
    """Test full rule evaluation with mocked DB."""

    @pytest.mark.asyncio
    @patch("app.services.rules._increment_match", new_callable=AsyncMock)
    @patch("app.services.rules._fetch_active_rules", new_callable=AsyncMock)
    async def test_no_rules_returns_empty(self, mock_fetch, mock_inc):
        mock_fetch.return_value = []
        ctx = _make_context()
        result = await evaluate_rules(AsyncMock(), uuid4(), uuid4(), ctx)
        assert isinstance(result, RuleEvaluationResult)
        assert len(result.actions_taken) == 0

    @pytest.mark.asyncio
    @patch("app.services.rules._increment_match", new_callable=AsyncMock)
    @patch("app.services.rules._fetch_active_rules", new_callable=AsyncMock)
    async def test_matching_rule_collects_actions(self, mock_fetch, mock_inc):
        rule = MagicMock()
        rule.id = uuid4()
        rule.name = "Test Rule"
        rule.conditions = {"operator": "AND", "rules": [{"field": "from", "op": "contains", "value": "alice"}]}
        rule.actions = [{"type": "move", "target": "Archive"}]
        rule.stop_processing = False
        mock_fetch.return_value = [rule]

        ctx = _make_context(sender="alice@example.com")
        result = await evaluate_rules(AsyncMock(), uuid4(), uuid4(), ctx)

        assert len(result.matched_rule_ids) == 1
        assert "move_to:Archive" in result.imap_actions

    @pytest.mark.asyncio
    @patch("app.services.rules._increment_match", new_callable=AsyncMock)
    @patch("app.services.rules._fetch_active_rules", new_callable=AsyncMock)
    async def test_stop_processing_halts_evaluation(self, mock_fetch, mock_inc):
        rule1 = MagicMock()
        rule1.id = uuid4()
        rule1.name = "Rule 1"
        rule1.conditions = {"operator": "AND", "rules": [{"field": "from", "op": "contains", "value": "alice"}]}
        rule1.actions = [{"type": "mark_read"}]
        rule1.stop_processing = True

        rule2 = MagicMock()
        rule2.id = uuid4()
        rule2.name = "Rule 2"
        rule2.conditions = {"operator": "AND", "rules": [{"field": "from", "op": "contains", "value": "alice"}]}
        rule2.actions = [{"type": "delete"}]
        rule2.stop_processing = False

        mock_fetch.return_value = [rule1, rule2]

        ctx = _make_context(sender="alice@example.com")
        result = await evaluate_rules(AsyncMock(), uuid4(), uuid4(), ctx)

        assert len(result.matched_rule_ids) == 1
        assert result.matched_rule_ids[0] == rule1.id

    @pytest.mark.asyncio
    @patch("app.services.rules._increment_match", new_callable=AsyncMock)
    @patch("app.services.rules._fetch_active_rules", new_callable=AsyncMock)
    async def test_invalid_conditions_skipped(self, mock_fetch, mock_inc):
        rule = MagicMock()
        rule.id = uuid4()
        rule.name = "Bad Rule"
        rule.conditions = {"invalid": "data"}
        rule.stop_processing = False
        mock_fetch.return_value = [rule]

        ctx = _make_context()
        result = await evaluate_rules(AsyncMock(), uuid4(), uuid4(), ctx)

        assert len(result.matched_rule_ids) == 0
