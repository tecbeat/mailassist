"""Test fixtures and configuration.

Provides mock database sessions, Valkey stubs, and factory functions
for User, MailAccount, Contact, Rule, and other models.
"""

from __future__ import annotations

import os

# Set required env vars for tests (get_settings() needs these)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("APP_SECRET_KEY", "test-secret-key-minimum-32-characters-for-unit-tests")

import asyncio
import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Event loop
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Mock Valkey clients
# ---------------------------------------------------------------------------


class FakeValkey:
    """In-memory Valkey mock for testing.

    Supports basic string ops, counters, key expiry, and list ops.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self._store[key] = str(value)

    async def setex(self, key: str, ttl: int, value: Any) -> None:
        self._store[key] = str(value)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def incr(self, key: str) -> int:
        val = int(self._store.get(key, 0)) + 1
        self._store[key] = str(val)
        return val

    async def incrby(self, key: str, amount: int) -> int:
        val = int(self._store.get(key, 0)) + amount
        self._store[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int) -> None:
        pass

    async def keys(self, pattern: str = "*") -> list[str]:
        return list(self._store.keys())

    async def llen(self, key: str) -> int:
        val = self._store.get(key, [])
        return len(val) if isinstance(val, list) else 0

    async def ping(self) -> bool:
        return True

    def clear(self) -> None:
        self._store.clear()


@pytest.fixture
def fake_valkey():
    """Fresh FakeValkey instance per test."""
    return FakeValkey()


@pytest.fixture
def mock_cache_client(fake_valkey):
    """Patch get_cache_client at source and all known call sites."""
    with (
        patch("app.core.redis.get_cache_client", return_value=fake_valkey),
        patch("app.services.contacts.matching.get_cache_client", return_value=fake_valkey),
        patch("app.services.contacts.sync.get_cache_client", return_value=fake_valkey),
        patch("app.services.contacts.writeback.get_cache_client", return_value=fake_valkey),
        patch("app.services.ai.get_cache_client", return_value=fake_valkey),
    ):
        yield fake_valkey


@pytest.fixture
def mock_session_client(fake_valkey):
    """Patch get_session_client to return FakeValkey."""
    with patch("app.core.redis.get_session_client", return_value=fake_valkey):
        yield fake_valkey


@pytest.fixture
def mock_task_client(fake_valkey):
    """Patch get_task_client to return FakeValkey."""
    with patch("app.core.redis.get_task_client", return_value=fake_valkey):
        yield fake_valkey


# ---------------------------------------------------------------------------
# Mock encryption
# ---------------------------------------------------------------------------


class FakeEncryption:
    """Transparent mock encryption that returns data as-is (base64-ish)."""

    def encrypt(self, plaintext: str) -> bytes:
        return plaintext.encode("utf-8")

    def decrypt(self, ciphertext: bytes) -> str:
        return ciphertext.decode("utf-8")


@pytest.fixture
def mock_encryption():
    """Patch get_encryption at its canonical source.

    All consumers import from ``app.core.security``, so patching the
    source module is sufficient.
    """
    fake = FakeEncryption()
    with patch("app.core.security.get_encryption", return_value=fake):
        yield fake


# ---------------------------------------------------------------------------
# Model factories
# ---------------------------------------------------------------------------


def make_user(**kwargs) -> dict:
    """Create a User-like dict with defaults."""
    defaults = {
        "id": uuid4(),
        "oidc_subject": f"sub-{uuid4().hex[:8]}",
        "email": f"user-{uuid4().hex[:6]}@example.com",
        "display_name": "Test User",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return defaults


def make_mail_account(user_id=None, **kwargs) -> dict:
    """Create a MailAccount-like dict with defaults."""
    defaults = {
        "id": uuid4(),
        "user_id": user_id or uuid4(),
        "name": "Test Account",
        "email_address": "test@example.com",
        "imap_host": "imap.example.com",
        "imap_port": 993,
        "is_active": True,
        "consecutive_errors": 0,
        "last_error": None,
        "last_error_at": None,
        "last_sync_at": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return defaults


def make_contact(user_id=None, **kwargs) -> dict:
    """Create a Contact-like dict with defaults."""
    defaults = {
        "id": uuid4(),
        "user_id": user_id or uuid4(),
        "display_name": "Jane Doe",
        "first_name": "Jane",
        "last_name": "Doe",
        "organization": "Acme Corp",
        "title": None,
        "emails": ["jane@example.com"],
        "phones": [],
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return defaults


def make_rule(user_id=None, **kwargs) -> dict:
    """Create a Rule-like dict with defaults."""
    defaults = {
        "id": uuid4(),
        "user_id": user_id or uuid4(),
        "mail_account_id": None,
        "name": "Test Rule",
        "description": None,
        "priority": 10,
        "is_active": True,
        "conditions": {
            "operator": "AND",
            "rules": [
                {"field": "from", "op": "contains", "value": "@example.com"},
            ],
        },
        "actions": [
            {"type": "label", "value": "test-label", "target": None},
        ],
        "stop_processing": False,
        "match_count": 0,
        "last_matched_at": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return defaults


def make_mail_context(**kwargs) -> dict:
    """Create a MailContext-compatible dict with defaults."""
    from app.plugins.base import MailContext

    defaults = {
        "user_id": str(uuid4()),
        "account_id": str(uuid4()),
        "mail_uid": "123",
        "sender": "sender@example.com",
        "sender_name": "Test Sender",
        "recipient": "me@example.com",
        "subject": "Test Subject",
        "body": "Test body content",
        "body_plain": "Test body content",
        "body_html": "<p>Test body content</p>",
        "headers": {"From": "sender@example.com", "To": "me@example.com", "Cc": ""},
        "date": "2026-01-15T10:00:00Z",
        "has_attachments": False,
        "attachment_names": [],
        "account_name": "Test Account",
        "account_email": "me@example.com",
        "existing_labels": [],
        "existing_folders": [],
        "folder_separator": "/",
        "mail_size": 2048,
        "thread_length": 1,
        "is_reply": False,
        "is_forwarded": False,
        "contact": None,
    }
    defaults.update(kwargs)
    return MailContext(**defaults)
