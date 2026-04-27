"""Tests for approval_mode enum handling in plugin_executor.

Verifies that approval_mode comparisons work correctly regardless of
whether the value is an ApprovalMode enum or a plain string from the DB.
"""

from __future__ import annotations

import pytest

from app.models.user import ApprovalMode


class TestApprovalModeComparison:
    """Ensure ApprovalMode comparisons are type-safe."""

    def test_enum_equals_enum(self) -> None:
        assert ApprovalMode.AUTO == ApprovalMode.AUTO
        assert ApprovalMode.APPROVAL == ApprovalMode.APPROVAL
        assert ApprovalMode.DISABLED == ApprovalMode.DISABLED

    def test_enum_equals_string(self) -> None:
        """str enum allows string comparison, but we should not rely on it."""
        assert ApprovalMode.AUTO == "auto"
        assert ApprovalMode.APPROVAL == "approval"

    def test_string_converts_to_enum(self) -> None:
        """Raw strings from DB should be convertible to ApprovalMode."""
        assert ApprovalMode("auto") is ApprovalMode.AUTO
        assert ApprovalMode("approval") is ApprovalMode.APPROVAL
        assert ApprovalMode("disabled") is ApprovalMode.DISABLED

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid"):
            ApprovalMode("invalid_mode")

    @pytest.mark.parametrize("raw", ["auto", "approval", "disabled"])
    def test_defensive_conversion(self, raw: str) -> None:
        """Simulates the defensive conversion added in plugin_executor."""
        converted = ApprovalMode(raw) if not isinstance(raw, ApprovalMode) else raw
        assert isinstance(converted, ApprovalMode)
