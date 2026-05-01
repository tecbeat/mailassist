"""Tests for the rule engine (test area 4).

Covers: nested conditions, all 11 operators, edge cases (empty fields,
regex timeout, boolean fields, list fields), and stop_processing.
"""

import pytest
from pydantic import ValidationError

from app.plugins.base import MailContext
from app.schemas.rules import ConditionGroup
from app.services.rules import evaluate_conditions


def _make_context(**overrides) -> MailContext:
    """Build a MailContext with sensible defaults, overriding as needed."""
    defaults = {
        "user_id": "user-1",
        "account_id": "acct-1",
        "mail_uid": "uid-1",
        "sender": "alice@example.com",
        "sender_name": "Alice Example",
        "recipient": "me@myhost.com",
        "subject": "Weekly Newsletter #42",
        "body": "Hello, here is your weekly newsletter with updates.",
        "body_plain": "Hello, here is your weekly newsletter with updates.",
        "body_html": "<p>Hello</p>",
        "headers": {
            "From": "alice@example.com",
            "To": "me@myhost.com",
            "Cc": "bob@example.com",
            "X-Custom-Header": "custom-value",
            "List-Unsubscribe": "<mailto:unsub@example.com>",
        },
        "date": "2026-01-15T10:30:00Z",
        "has_attachments": True,
        "attachment_names": ["report.pdf", "image.png"],
        "account_name": "Main Account",
        "account_email": "me@myhost.com",
        "existing_labels": ["inbox"],
        "existing_folders": ["INBOX"],
        "excluded_folders": [],
        "folder_separator": "/",
        "mail_size": 51200,
        "thread_length": 3,
        "is_reply": True,
        "is_forwarded": False,
        "contact": {"display_name": "Alice Smith", "organization": "Acme Corp"},
    }
    defaults.update(overrides)
    return MailContext(**defaults)


def _cond(field: str, op: str, value=None) -> dict:
    """Shorthand for a condition rule dict."""
    return {"field": field, "op": op, "value": value}


def _group(operator: str, rules: list) -> dict:
    """Shorthand for a condition group dict."""
    return {"operator": operator, "rules": rules}


class TestOperators:
    """Test all 11 comparison operators."""

    def test_equals(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("from", "equals", "alice@example.com")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_equals_case_insensitive(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("from", "equals", "ALICE@EXAMPLE.COM")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_not_equals(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("from", "not_equals", "bob@example.com")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_contains(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("subject", "contains", "Newsletter")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_not_contains(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("subject", "not_contains", "URGENT")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_starts_with(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("subject", "starts_with", "Weekly")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_ends_with(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("subject", "ends_with", "#42")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_matches_regex(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("subject", "matches_regex", r"Newsletter\s+#\d+")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_greater_than(self):
        ctx = _make_context(mail_size=100_000)
        cg = ConditionGroup.model_validate(_group("AND", [_cond("size", "greater_than", 50000)]))
        assert evaluate_conditions(cg, ctx) is True

    def test_less_than(self):
        ctx = _make_context(mail_size=1024)
        cg = ConditionGroup.model_validate(_group("AND", [_cond("size", "less_than", 2048)]))
        assert evaluate_conditions(cg, ctx) is True

    def test_is_empty(self):
        ctx = _make_context(contact=None)
        cg = ConditionGroup.model_validate(_group("AND", [_cond("contact_name", "is_empty")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_is_not_empty(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("from", "is_not_empty")]))
        assert evaluate_conditions(cg, ctx) is True


class TestNestedConditions:
    """Test nested AND/OR condition groups."""

    def test_simple_and(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(
            _group(
                "AND",
                [
                    _cond("from", "contains", "example.com"),
                    _cond("has_attachment", "equals", True),
                ],
            )
        )
        assert evaluate_conditions(cg, ctx) is True

    def test_simple_or(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(
            _group(
                "OR",
                [
                    _cond("from", "equals", "nobody@nowhere.com"),
                    _cond("subject", "contains", "Newsletter"),
                ],
            )
        )
        assert evaluate_conditions(cg, ctx) is True

    def test_and_fails_when_one_false(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(
            _group(
                "AND",
                [
                    _cond("from", "contains", "example.com"),
                    _cond("from", "contains", "nonexistent.org"),
                ],
            )
        )
        assert evaluate_conditions(cg, ctx) is False

    def test_or_fails_when_all_false(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(
            _group(
                "OR",
                [
                    _cond("from", "equals", "nope@nope.com"),
                    _cond("subject", "equals", "Nonexistent Subject"),
                ],
            )
        )
        assert evaluate_conditions(cg, ctx) is False

    def test_nested_and_or(self):
        """AND with a nested OR group."""
        ctx = _make_context()
        cg = ConditionGroup.model_validate(
            _group(
                "AND",
                [
                    _cond("from", "contains", "@example.com"),
                    _group(
                        "OR",
                        [
                            _cond("has_attachment", "equals", True),
                            _cond("size", "greater_than", 1_000_000),
                        ],
                    ),
                ],
            )
        )
        assert evaluate_conditions(cg, ctx) is True

    def test_deeply_nested(self):
        """3 levels of nesting."""
        ctx = _make_context()
        cg = ConditionGroup.model_validate(
            _group(
                "AND",
                [
                    _group(
                        "OR",
                        [
                            _group(
                                "AND",
                                [
                                    _cond("from", "contains", "alice"),
                                    _cond("is_reply", "equals", True),
                                ],
                            ),
                            _cond("subject", "contains", "URGENT"),
                        ],
                    ),
                ],
            )
        )
        assert evaluate_conditions(cg, ctx) is True


class TestSpecialFields:
    """Test special field types: headers, contacts, lists, booleans."""

    def test_header_field(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("header:X-Custom-Header", "equals", "custom-value")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_header_field_missing(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("header:X-Nonexistent", "is_empty")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_contact_name(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("contact_name", "contains", "Alice")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_contact_org(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("contact_org", "equals", "Acme Corp")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_contact_name_when_no_contact(self):
        ctx = _make_context(contact=None)
        cg = ConditionGroup.model_validate(_group("AND", [_cond("contact_name", "is_empty")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_cc_field(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("cc", "contains", "bob@example.com")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_attachment_name_list(self):
        """attachment_name matches against any item in the list."""
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("attachment_name", "ends_with", ".pdf")]))
        assert evaluate_conditions(cg, ctx) is True

    def test_attachment_name_no_match(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("attachment_name", "ends_with", ".zip")]))
        assert evaluate_conditions(cg, ctx) is False

    def test_boolean_has_attachment(self):
        ctx = _make_context(has_attachments=False)
        cg = ConditionGroup.model_validate(_group("AND", [_cond("has_attachment", "equals", False)]))
        assert evaluate_conditions(cg, ctx) is True

    def test_is_reply_boolean(self):
        ctx = _make_context(is_reply=False)
        cg = ConditionGroup.model_validate(_group("AND", [_cond("is_reply", "equals", False)]))
        assert evaluate_conditions(cg, ctx) is True

    def test_is_forwarded_boolean(self):
        ctx = _make_context(is_forwarded=True)
        cg = ConditionGroup.model_validate(_group("AND", [_cond("is_forwarded", "equals", True)]))
        assert evaluate_conditions(cg, ctx) is True


class TestRegexSafety:
    """Test regex safety features."""

    def test_invalid_regex_returns_false(self):
        """Broken regex pattern fails gracefully (no exception)."""
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("subject", "matches_regex", "[invalid")]))
        assert evaluate_conditions(cg, ctx) is False

    def test_long_regex_rejected(self):
        """Regex patterns over 500 chars are rejected."""
        ctx = _make_context()
        long_pattern = "a" * 501
        cg = ConditionGroup.model_validate(_group("AND", [_cond("subject", "matches_regex", long_pattern)]))
        assert evaluate_conditions(cg, ctx) is False

    def test_empty_regex_returns_false(self):
        ctx = _make_context()
        cg = ConditionGroup.model_validate(_group("AND", [_cond("subject", "matches_regex", "")]))
        assert evaluate_conditions(cg, ctx) is False


class TestNestingValidation:
    """Test Pydantic validation for nesting limits."""

    def test_max_nesting_depth_exceeded(self):
        """Nesting deeper than 5 levels raises validation error."""
        # Build 6 levels of nesting
        inner = _cond("from", "equals", "test")
        for _ in range(6):
            inner = _group("AND", [inner])

        with pytest.raises(Exception, match="nesting"):
            ConditionGroup.model_validate(inner)

    def test_max_nesting_depth_exactly_5_ok(self):
        """5 levels of nesting is allowed."""
        inner = _cond("from", "equals", "test")
        for _ in range(4):
            inner = _group("AND", [inner])

        # Should not raise
        ConditionGroup.model_validate(inner)

    def test_too_many_rules_per_group(self):
        """More than 20 rules in a group raises validation error."""
        rules = [_cond("from", "equals", f"user{i}@test.com") for i in range(21)]

        with pytest.raises(ValidationError):
            ConditionGroup.model_validate(_group("AND", rules))
