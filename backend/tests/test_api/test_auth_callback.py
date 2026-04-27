"""Tests for OIDC auth callback — ghost session prevention.

Verifies that a Valkey session is only created after a successful DB commit,
and that commit failures produce a proper error without ghost sessions.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from conftest import FakeValkey
from fastapi import HTTPException


@pytest.fixture
def fake_session_client():
    return FakeValkey()


@pytest.fixture
def fake_userinfo():
    return {
        "sub": f"sub-{uuid4().hex[:8]}",
        "email": "test@example.com",
        "name": "Test User",
    }


@pytest.fixture
def fake_token():
    return {
        "access_token": "access-tok",
        "refresh_token": "refresh-tok",
        "id_token": "id-tok",
        "expires_at": 9999999999,
    }


def _make_mock_db_session(*, commit_side_effect=None):
    """Create a mock async DB session generator.

    If commit_side_effect is set, db.commit() will raise that exception.
    """
    mock_user = MagicMock()
    mock_user.id = uuid4()
    mock_user.email = "test@example.com"
    mock_user.display_name = "Test User"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_user

    db = AsyncMock()
    db.execute.return_value = mock_result
    db.flush = AsyncMock()
    db.commit = AsyncMock(side_effect=commit_side_effect)
    db.rollback = AsyncMock()

    async def fake_get_session():
        yield db

    return fake_get_session, db, mock_user


@pytest.mark.asyncio
async def test_callback_creates_session_after_commit(
    fake_session_client, fake_userinfo, fake_token
):
    """Valkey session is created only after a successful DB commit."""
    fake_get_session, db, mock_user = _make_mock_db_session()

    oidc_config = {
        "token_endpoint": "https://idp.example.com/token",
        "userinfo_endpoint": "https://idp.example.com/userinfo",
    }
    state_data = json.dumps({"code_verifier": "test-verifier"})

    with (
        patch("app.api.auth.get_settings") as mock_settings,
        patch("app.api.auth._get_oidc_config", return_value=oidc_config),
        patch("app.api.auth.get_session_client", return_value=fake_session_client),
        patch("app.api.auth.get_session", fake_get_session),
        patch("app.api.auth.get_encryption") as mock_enc,
        patch("app.api.auth._create_oauth_client") as mock_oauth,
        patch("httpx.AsyncClient") as mock_http_cls,
    ):
        # Configure mocks
        settings = MagicMock()
        settings.debug = True
        settings.session_ttl_seconds = 3600
        mock_settings.return_value = settings

        mock_enc_instance = MagicMock()
        mock_enc_instance.encrypt.return_value = b"encrypted"
        mock_enc.return_value = mock_enc_instance

        # Mock OAuth token exchange
        oauth_client = AsyncMock()
        oauth_client.fetch_token = AsyncMock(return_value=fake_token)
        mock_oauth.return_value = oauth_client

        # Mock userinfo HTTP call
        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_userinfo
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http_cls.return_value = mock_http

        # Mock state in Valkey
        await fake_session_client.set("oidc_state:test-state", state_data)

        # Import and call
        from app.api.auth import callback

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        response = await callback(mock_request, code="auth-code", state="test-state")

        # DB commit was called
        db.commit.assert_awaited_once()

        # Session was stored in Valkey
        session_keys = [k for k in fake_session_client._store if k.startswith("session:")]
        assert len(session_keys) == 1

        # Response is a redirect with session cookie
        assert response.status_code == 302


@pytest.mark.asyncio
async def test_callback_no_session_on_commit_failure(
    fake_session_client, fake_userinfo, fake_token
):
    """No Valkey session is created when DB commit fails."""
    fake_get_session, db, mock_user = _make_mock_db_session(
        commit_side_effect=Exception("DB commit failed"),
    )

    oidc_config = {
        "token_endpoint": "https://idp.example.com/token",
        "userinfo_endpoint": "https://idp.example.com/userinfo",
    }
    state_data = json.dumps({"code_verifier": "test-verifier"})

    with (
        patch("app.api.auth.get_settings") as mock_settings,
        patch("app.api.auth._get_oidc_config", return_value=oidc_config),
        patch("app.api.auth.get_session_client", return_value=fake_session_client),
        patch("app.api.auth.get_session", fake_get_session),
        patch("app.api.auth.get_encryption") as mock_enc,
        patch("app.api.auth._create_oauth_client") as mock_oauth,
        patch("httpx.AsyncClient") as mock_http_cls,
    ):
        settings = MagicMock()
        settings.debug = True
        settings.session_ttl_seconds = 3600
        settings.auth_rate_limit = 10
        mock_settings.return_value = settings

        mock_enc_instance = MagicMock()
        mock_enc_instance.encrypt.return_value = b"encrypted"
        mock_enc.return_value = mock_enc_instance

        oauth_client = AsyncMock()
        oauth_client.fetch_token = AsyncMock(return_value=fake_token)
        mock_oauth.return_value = oauth_client

        mock_resp = MagicMock()
        mock_resp.json.return_value = fake_userinfo
        mock_resp.raise_for_status = MagicMock()

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http_cls.return_value = mock_http

        await fake_session_client.set("oidc_state:test-state", state_data)

        from app.api.auth import callback

        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"

        with pytest.raises(HTTPException) as exc_info:
            await callback(mock_request, code="auth-code", state="test-state")

        assert exc_info.value.status_code == 500

        # DB rollback was called
        db.rollback.assert_awaited_once()

        # No session was created in Valkey
        session_keys = [k for k in fake_session_client._store if k.startswith("session:")]
        assert len(session_keys) == 0
