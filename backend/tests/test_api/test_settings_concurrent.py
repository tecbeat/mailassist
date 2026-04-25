"""Tests for max_concurrent_processing in user settings schemas.

Verifies that the SettingsResponse includes the field and that
SettingsUpdate enforces the 1..20 validation range.
"""

import pytest
from pydantic import ValidationError

from app.schemas.settings import SettingsResponse, SettingsUpdate


class TestSettingsMaxConcurrentProcessing:
    """max_concurrent_processing field on settings schemas."""

    def test_update_schema_accepts_valid_value(self):
        """SettingsUpdate should accept values in the 1-20 range."""
        update = SettingsUpdate(max_concurrent_processing=5)
        assert update.max_concurrent_processing == 5

    def test_update_schema_accepts_min_value(self):
        """SettingsUpdate should accept the minimum value of 1."""
        update = SettingsUpdate(max_concurrent_processing=1)
        assert update.max_concurrent_processing == 1

    def test_update_schema_accepts_max_value(self):
        """SettingsUpdate should accept the maximum value of 20."""
        update = SettingsUpdate(max_concurrent_processing=20)
        assert update.max_concurrent_processing == 20

    def test_update_schema_rejects_zero(self):
        """SettingsUpdate should reject 0 (below minimum of 1)."""
        with pytest.raises(ValidationError):
            SettingsUpdate(max_concurrent_processing=0)

    def test_update_schema_rejects_above_max(self):
        """SettingsUpdate should reject values above 20."""
        with pytest.raises(ValidationError):
            SettingsUpdate(max_concurrent_processing=21)

    def test_update_schema_defaults_to_none(self):
        """SettingsUpdate should default max_concurrent_processing to None."""
        update = SettingsUpdate()
        assert update.max_concurrent_processing is None

    def test_response_schema_includes_field(self):
        """SettingsResponse must include max_concurrent_processing."""
        assert "max_concurrent_processing" in SettingsResponse.model_fields
