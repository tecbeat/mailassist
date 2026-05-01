"""Tests for MailAccount update field whitelist.

Verifies that the setattr loop in the update endpoint only writes to
explicitly allowed columns, preventing overwrites of sensitive fields
like id, user_id, or encrypted_credentials.
"""

from __future__ import annotations

import pytest

from app.api.mail_accounts import _UPDATABLE_FIELDS

# Fields that must NEVER be writable through the update endpoint.
_SENSITIVE_FIELDS = {
    "id",
    "user_id",
    "encrypted_credentials",
    "created_at",
    "updated_at",
    "initial_scan_done",
    "last_sync_at",
    "last_error",
    "last_error_at",
    "consecutive_errors",
    "is_paused",
    "manually_paused",
    "paused_reason",
    "paused_at",
}


class TestUpdatableFieldsWhitelist:
    """Ensure the whitelist is correct and complete."""

    def test_sensitive_fields_excluded(self) -> None:
        overlap = _UPDATABLE_FIELDS & _SENSITIVE_FIELDS
        assert overlap == set(), f"Sensitive fields in whitelist: {overlap}"

    def test_expected_fields_present(self) -> None:
        expected = {
            "name",
            "email_address",
            "imap_host",
            "imap_port",
            "imap_use_ssl",
            "polling_enabled",
            "polling_interval_minutes",
            "idle_enabled",
            "scan_existing_emails",
            "excluded_folders",
        }
        assert expected == _UPDATABLE_FIELDS

    @pytest.mark.parametrize("field", sorted(_SENSITIVE_FIELDS))
    def test_each_sensitive_field_blocked(self, field: str) -> None:
        assert field not in _UPDATABLE_FIELDS
