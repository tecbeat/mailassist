"""Tests for pause fields on MailAccount and AIProvider.

Verifies that pause-related columns default correctly and that
Pydantic response schemas include the new fields.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.schemas.mail_account import MailAccountResponse, MailAccountStatus
from app.schemas.ai_provider import AIProviderResponse


class TestMailAccountPauseDefaults:
    """Pause fields on MailAccount should default to 'not paused'."""

    def test_response_schema_includes_pause_fields(self):
        """MailAccountResponse must expose is_paused, paused_reason, paused_at."""
        obj = MagicMock()
        obj.id = uuid4()
        obj.name = "Test"
        obj.email_address = "test@example.com"
        obj.imap_host = "imap.example.com"
        obj.imap_port = 993
        obj.imap_use_ssl = True
        obj.polling_enabled = True
        obj.polling_interval_minutes = 5
        obj.idle_enabled = True
        obj.initial_scan_done = False
        obj.excluded_folders = None
        obj.last_sync_at = None
        obj.last_error = None
        obj.last_error_at = None
        obj.consecutive_errors = 0
        obj.is_paused = False
        obj.manually_paused = False
        obj.paused_reason = None
        obj.paused_at = None
        obj.created_at = datetime.now(UTC)
        obj.updated_at = datetime.now(UTC)

        resp = MailAccountResponse.model_validate(obj, from_attributes=True)
        assert resp.is_paused is False
        assert resp.paused_reason is None
        assert resp.paused_at is None

    def test_response_schema_paused_account(self):
        """Paused account should serialize pause fields correctly."""
        now = datetime.now(UTC)
        obj = MagicMock()
        obj.id = uuid4()
        obj.name = "Paused Account"
        obj.email_address = "paused@example.com"
        obj.imap_host = "imap.example.com"
        obj.imap_port = 993
        obj.imap_use_ssl = True
        obj.polling_enabled = True
        obj.polling_interval_minutes = 5
        obj.idle_enabled = True
        obj.initial_scan_done = False
        obj.excluded_folders = None
        obj.last_sync_at = None
        obj.last_error = None
        obj.last_error_at = None
        obj.consecutive_errors = 0
        obj.is_paused = True
        obj.manually_paused = False
        obj.paused_reason = "imap_unreachable"
        obj.paused_at = now
        obj.created_at = now
        obj.updated_at = now

        resp = MailAccountResponse.model_validate(obj, from_attributes=True)
        assert resp.is_paused is True
        assert resp.paused_reason == "imap_unreachable"
        assert resp.paused_at == now

    def test_status_schema_includes_pause_fields(self):
        """MailAccountStatus must expose pause state."""
        obj = MagicMock()
        obj.id = uuid4()
        obj.name = "Test"
        obj.is_paused = True
        obj.manually_paused = True
        obj.paused_reason = "manual"
        obj.paused_at = datetime.now(UTC)
        obj.last_sync_at = None
        obj.last_error = None
        obj.last_error_at = None
        obj.consecutive_errors = 0

        status = MailAccountStatus.model_validate(obj, from_attributes=True)
        assert status.is_paused is True
        assert status.paused_reason == "manual"


class TestAIProviderPauseDefaults:
    """Pause fields on AIProvider should default to 'not paused'."""

    def test_response_schema_includes_pause_fields(self):
        """AIProviderResponse must expose is_paused, paused_reason, paused_at."""
        obj = MagicMock()
        obj.id = uuid4()
        obj.name = "Test Provider"
        obj.provider_type = "openai"
        obj.base_url = "https://api.openai.com"
        obj.model_name = "gpt-4o"
        obj.is_default = True
        obj.max_tokens = 1024
        obj.temperature = 0.3
        obj.consecutive_errors = 0
        obj.last_error = None
        obj.last_error_at = None
        obj.last_success_at = None
        obj.is_paused = False
        obj.manually_paused = False
        obj.paused_reason = None
        obj.paused_at = None
        obj.created_at = datetime.now(UTC)
        obj.updated_at = datetime.now(UTC)

        resp = AIProviderResponse.model_validate(obj, from_attributes=True)
        assert resp.is_paused is False
        assert resp.paused_reason is None
        assert resp.paused_at is None

    def test_response_schema_paused_provider(self):
        """Paused provider should serialize pause fields correctly."""
        now = datetime.now(UTC)
        obj = MagicMock()
        obj.id = uuid4()
        obj.name = "Paused Provider"
        obj.provider_type = "openai"
        obj.base_url = "https://api.openai.com"
        obj.model_name = "gpt-4o"
        obj.is_default = True
        obj.max_tokens = 1024
        obj.temperature = 0.3
        obj.consecutive_errors = 5
        obj.last_error = "rate_limit_exceeded"
        obj.last_error_at = now
        obj.last_success_at = None
        obj.is_paused = True
        obj.manually_paused = False
        obj.paused_reason = "provider_ai_error"
        obj.paused_at = now
        obj.created_at = now
        obj.updated_at = now

        resp = AIProviderResponse.model_validate(obj, from_attributes=True)
        assert resp.is_paused is True
        assert resp.paused_reason == "provider_ai_error"
        assert resp.paused_at == now
