"""Tests for _repair_json stack-based brace closing.

Verifies that interleaved and nested braces/brackets are closed in the
correct order using a stack instead of naive counting.
"""

from __future__ import annotations

import json

from app.services.ai import _repair_json


class TestRepairJsonBraceClosing:
    """Ensure braces and brackets are closed in correct nesting order."""

    def test_simple_missing_closing_brace(self) -> None:
        result = _repair_json('{"key": "value"')
        assert json.loads(result) == {"key": "value"}

    def test_simple_missing_closing_bracket(self) -> None:
        result = _repair_json('["a", "b"')
        assert json.loads(result) == ["a", "b"]

    def test_interleaved_brace_and_bracket(self) -> None:
        """The original count-based approach would produce {[}] here."""
        result = _repair_json('{"items": ["a", "b"')
        parsed = json.loads(result)
        assert parsed == {"items": ["a", "b"]}

    def test_deeply_nested(self) -> None:
        result = _repair_json('{"a": {"b": [1, 2, {"c": 3')
        parsed = json.loads(result)
        assert parsed == {"a": {"b": [1, 2, {"c": 3}]}}

    def test_already_valid_json(self) -> None:
        valid = '{"key": [1, 2, 3]}'
        result = _repair_json(valid)
        assert json.loads(result) == {"key": [1, 2, 3]}

    def test_braces_inside_strings_ignored(self) -> None:
        """Braces inside string values should not affect the stack."""
        result = _repair_json('{"msg": "use { and [ in text"')
        parsed = json.loads(result)
        assert parsed == {"msg": "use { and [ in text"}

    def test_trailing_comma_removed(self) -> None:
        result = _repair_json('{"a": 1, "b": 2,}')
        assert json.loads(result) == {"a": 1, "b": 2}

    def test_single_quotes_converted(self) -> None:
        result = _repair_json("{'key': 'value'}")
        assert json.loads(result) == {"key": "value"}
