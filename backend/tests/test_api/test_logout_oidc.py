"""Tests for OIDC logout — end_session_endpoint integration.

Verifies that the logout endpoint returns an end_session_url when the IdP
supports it, including the id_token_hint from the encrypted session tokens.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from conftest import FakeEncryption, FakeValkey


@pytest.fixture
def fake_session_client():
    return FakeValkey()


def _store_session(client: FakeValkey, session_id: str, *, id_token: str | None = "test-id-token") -> None:
    """Store a session with encrypted tokens in FakeValkey."""
    tokens = json.dumps({
        "access_token": "access-tok",
        "refresh_token": "refresh-tok",
        "id_token": id_token,
        "expires_at": 9999999999,
    })
    # FakeEncryption.encrypt returns plaintext bytes
    encrypted = FakeEncryption().encrypt(tokens)
    session_data = json.dumps({
        "user_id": "user-123",
        "email": "test@example.com",
        "display_name": "Test User",
        "encrypted_tokens": encrypted.decode(),
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    client._store[f"session:{session_id}"] = session_data


@pytest.mark.asyncio
async def test_logout_returns_end_session_url_with_id_token(fake_session_client):
    """Logout returns end_session_url with id_token_hint when IdP supports it."""
    _store_session(fake_session_client, "sess-123", id_token="my-id-token")

    oidc_config = {
        "end_session_endpoint": "https://idp.example.com/logout",
    }

    with (
        patch("app.api.auth.get_session_client", return_value=fake_session_client),
        patch("app.api.auth._get_oidc_config", return_value=oidc_config),
        patch("app.api.auth.get_encryption", return_value=FakeEncryption()),
    ):
        from app.api.auth import logout

        mock_request = MagicMock()
        mock_request.cookies = {"session_id": "sess-123"}

        response = await logout(mock_request)
        body = json.loads(response.body)

        assert body["message"] == "Logged out"
        assert "end_session_url" in body
        assert "id_token_hint=my-id-token" in body["end_session_url"]
        assert "post_logout_redirect_uri" in body["end_session_url"]
        assert body["end_session_url"].startswith("https://idp.example.com/logout?")


@pytest.mark.asyncio
async def test_logout_returns_end_session_url_without_id_token(fake_session_client):
    """Logout returns end_session_url without id_token_hint when token is missing."""
    _store_session(fake_session_client, "sess-123", id_token=None)

    oidc_config = {
        "end_session_endpoint": "https://idp.example.com/logout",
    }

    with (
        patch("app.api.auth.get_session_client", return_value=fake_session_client),
        patch("app.api.auth._get_oidc_config", return_value=oidc_config),
        patch("app.api.auth.get_encryption", return_value=FakeEncryption()),
    ):
        from app.api.auth import logout

        mock_request = MagicMock()
        mock_request.cookies = {"session_id": "sess-123"}

        response = await logout(mock_request)
        body = json.loads(response.body)

        assert "end_session_url" in body
        assert "id_token_hint" not in body["end_session_url"]


@pytest.mark.asyncio
async def test_logout_no_end_session_when_not_supported(fake_session_client):
    """Logout omits end_session_url when IdP doesn't support it."""
    _store_session(fake_session_client, "sess-123")

    oidc_config = {}  # No end_session_endpoint

    with (
        patch("app.api.auth.get_session_client", return_value=fake_session_client),
        patch("app.api.auth._get_oidc_config", return_value=oidc_config),
        patch("app.api.auth.get_encryption", return_value=FakeEncryption()),
    ):
        from app.api.auth import logout

        mock_request = MagicMock()
        mock_request.cookies = {"session_id": "sess-123"}

        response = await logout(mock_request)
        body = json.loads(response.body)

        assert body["message"] == "Logged out"
        assert "end_session_url" not in body


@pytest.mark.asyncio
async def test_logout_deletes_session(fake_session_client):
    """Logout deletes the session from Valkey."""
    _store_session(fake_session_client, "sess-123")

    with (
        patch("app.api.auth.get_session_client", return_value=fake_session_client),
        patch("app.api.auth._get_oidc_config", side_effect=Exception("no OIDC")),
        patch("app.api.auth.get_encryption", return_value=FakeEncryption()),
    ):
        from app.api.auth import logout

        mock_request = MagicMock()
        mock_request.cookies = {"session_id": "sess-123"}

        await logout(mock_request)

        assert "session:sess-123" not in fake_session_client._store


@pytest.mark.asyncio
async def test_logout_without_session():
    """Logout works even without a session cookie."""
    fake_client = FakeValkey()

    with (
        patch("app.api.auth.get_session_client", return_value=fake_client),
        patch("app.api.auth._get_oidc_config", side_effect=Exception("no OIDC")),
    ):
        from app.api.auth import logout

        mock_request = MagicMock()
        mock_request.cookies = {}

        response = await logout(mock_request)
        body = json.loads(response.body)

        assert body["message"] == "Logged out"
