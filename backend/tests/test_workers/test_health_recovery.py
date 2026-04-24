"""Tests for paused-provider recovery with active probes (Issue #50).

Verifies:
- IMAP probe success/failure paths
- AI provider probe success/failure paths (OpenAI and Ollama)
- Cooldown enforcement (probe not called before cooldown expires)
- Unpause flow (fields cleared on success, event emitted)
- Cooldown reset on failed probe
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# IMAP probe
# ---------------------------------------------------------------------------


class TestProbeImapAccount:
    """IMAP probe: connect via MailBox + login + logout within timeout."""

    def _make_account(self, *, host="imap.example.com", port=993):
        account = MagicMock()
        account.id = uuid4()
        account.user_id = uuid4()
        account.email_address = "user@example.com"
        account.imap_host = host
        account.imap_port = port
        account.encrypted_credentials = b"encrypted"
        account.is_paused = True
        account.paused_at = datetime.now(UTC) - timedelta(minutes=10)
        account.paused_reason = "imap_error"
        account.consecutive_errors = 3
        return account

    @pytest.mark.asyncio
    async def test_successful_probe(self):
        """Successful MailBox connect + login + logout returns True."""
        from app.workers.health import probe_imap_account

        account = self._make_account()

        mock_mb = MagicMock()
        mock_mb.login = MagicMock()
        mock_mb.logout = MagicMock()

        with (
            patch("app.workers.health.decrypt_credentials",
                  return_value={"username": "user", "password": "pass"}),
            patch("app.workers.health.MailBox", return_value=mock_mb),
        ):
            result = await probe_imap_account(account)

        assert result is True
        mock_mb.login.assert_called_once_with("user", "pass", initial_folder=None)
        mock_mb.logout.assert_called_once()

    @pytest.mark.asyncio
    async def test_login_failure_returns_false(self):
        """Login failure (wrong credentials) returns False."""
        from app.workers.health import probe_imap_account

        account = self._make_account()

        mock_mb = MagicMock()
        mock_mb.login = MagicMock(side_effect=Exception("LOGIN failed"))

        with (
            patch("app.workers.health.decrypt_credentials",
                  return_value={"username": "user", "password": "wrong"}),
            patch("app.workers.health.MailBox", return_value=mock_mb),
        ):
            result = await probe_imap_account(account)

        assert result is False

    @pytest.mark.asyncio
    async def test_connection_error_returns_false(self):
        """Network error during MailBox construction returns False."""
        from app.workers.health import probe_imap_account

        account = self._make_account()

        with (
            patch("app.workers.health.decrypt_credentials",
                  return_value={"username": "user", "password": "pass"}),
            patch("app.workers.health.MailBox",
                  side_effect=OSError("Connection refused")),
        ):
            result = await probe_imap_account(account)

        assert result is False

    @pytest.mark.asyncio
    async def test_timeout_returns_false(self):
        """Timeout during probe returns False."""
        import asyncio
        from app.workers.health import probe_imap_account

        account = self._make_account()

        # Simulate a slow connection that exceeds the timeout
        def slow_init(*args, **kwargs):
            raise asyncio.TimeoutError()

        with (
            patch("app.workers.health.decrypt_credentials",
                  return_value={"username": "user", "password": "pass"}),
            patch("app.workers.health.asyncio.wait_for",
                  side_effect=asyncio.TimeoutError),
        ):
            result = await probe_imap_account(account)

        assert result is False

    @pytest.mark.asyncio
    async def test_logout_failure_still_returns_true(self):
        """If login succeeds but logout fails, probe still returns True."""
        from app.workers.health import probe_imap_account

        account = self._make_account()

        mock_mb = MagicMock()
        mock_mb.login = MagicMock()
        mock_mb.logout = MagicMock(side_effect=OSError("broken pipe"))

        with (
            patch("app.workers.health.decrypt_credentials",
                  return_value={"username": "user", "password": "pass"}),
            patch("app.workers.health.MailBox", return_value=mock_mb),
        ):
            result = await probe_imap_account(account)

        assert result is True


# ---------------------------------------------------------------------------
# AI provider probe
# ---------------------------------------------------------------------------


class TestProbeAiProvider:
    """AI provider probe: /v1/models or /api/tags."""

    def _make_provider(self, *, provider_type="openai", base_url="https://api.openai.com",
                       api_key=b"encrypted_key"):
        provider = MagicMock()
        provider.id = uuid4()
        provider.user_id = uuid4()
        provider.name = "test-provider"
        provider.provider_type = MagicMock(value=provider_type)
        provider.base_url = base_url
        provider.api_key = api_key
        provider.is_paused = True
        provider.paused_at = datetime.now(UTC) - timedelta(minutes=5)
        provider.paused_reason = "llm_error"
        provider.consecutive_errors = 3
        return provider

    @pytest.mark.asyncio
    async def test_openai_probe_success(self):
        """OpenAI-compatible probe via litellm.amodels succeeds."""
        from app.workers.health import probe_ai_provider

        provider = self._make_provider(provider_type="openai")

        mock_response = MagicMock()
        mock_response.data = [MagicMock()]  # non-empty model list

        with (
            patch("app.workers.health.get_encryption") as mock_enc,
            patch("app.workers.health.litellm") as mock_litellm,
        ):
            mock_enc.return_value.decrypt.return_value = "sk-test-key"
            mock_litellm.amodels = AsyncMock(return_value=mock_response)
            result = await probe_ai_provider(provider)

        assert result is True

    @pytest.mark.asyncio
    async def test_openai_probe_failure(self):
        """OpenAI probe failure returns False."""
        from app.workers.health import probe_ai_provider

        provider = self._make_provider(provider_type="openai")

        with (
            patch("app.workers.health.get_encryption") as mock_enc,
            patch("app.workers.health.litellm") as mock_litellm,
        ):
            mock_enc.return_value.decrypt.return_value = "sk-test-key"
            mock_litellm.amodels = AsyncMock(side_effect=Exception("API error"))
            result = await probe_ai_provider(provider)

        assert result is False

    @pytest.mark.asyncio
    async def test_ollama_probe_success(self):
        """Ollama probe via GET /api/tags succeeds."""
        from app.workers.health import probe_ai_provider

        provider = self._make_provider(
            provider_type="ollama",
            base_url="http://localhost:11434",
            api_key=None,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("app.workers.health.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client
            result = await probe_ai_provider(provider)

        assert result is True
        mock_client.get.assert_awaited_once_with(
            "http://localhost:11434/api/tags",
        )

    @pytest.mark.asyncio
    async def test_ollama_probe_failure(self):
        """Ollama probe failure (server down) returns False."""
        from app.workers.health import probe_ai_provider

        provider = self._make_provider(
            provider_type="ollama",
            base_url="http://localhost:11434",
            api_key=None,
        )

        with patch("app.workers.health.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client
            result = await probe_ai_provider(provider)

        assert result is False

    @pytest.mark.asyncio
    async def test_provider_without_api_key(self):
        """Provider with no API key (e.g. local Ollama) probes without key."""
        from app.workers.health import probe_ai_provider

        provider = self._make_provider(
            provider_type="ollama",
            base_url="http://localhost:11434",
            api_key=None,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("app.workers.health.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client
            result = await probe_ai_provider(provider)

        assert result is True


# ---------------------------------------------------------------------------
# recover_paused_providers — integration-level unit tests
# ---------------------------------------------------------------------------


class TestRecoverPausedAccounts:
    """IMAP account recovery: cooldown + probe + unpause."""

    def _make_account(self, *, paused_at):
        account = MagicMock()
        account.id = uuid4()
        account.user_id = uuid4()
        account.email_address = "user@example.com"
        account.imap_host = "imap.example.com"
        account.imap_port = 993
        account.encrypted_credentials = b"encrypted"
        account.is_paused = True
        account.paused_at = paused_at
        account.paused_reason = "imap_error"
        account.consecutive_errors = 3
        return account

    @pytest.mark.asyncio
    async def test_successful_probe_unpauses_account(self):
        """Account is unpaused when probe succeeds after cooldown."""
        from app.workers.health import _recover_paused_accounts

        now = datetime.now(UTC)
        account = self._make_account(
            paused_at=now - timedelta(minutes=10),  # well past 5-min cooldown
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [account]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def fake_get_session():
            yield mock_db

        with (
            patch("app.workers.health.get_session", fake_get_session),
            patch("app.workers.health.probe_imap_account",
                  AsyncMock(return_value=True)),
            patch("app.workers.health.get_event_bus") as mock_bus_fn,
        ):
            mock_bus = AsyncMock()
            mock_bus_fn.return_value = mock_bus
            await _recover_paused_accounts(now, cooldown_seconds=300)

        assert account.is_paused is False
        assert account.paused_reason is None
        assert account.paused_at is None
        assert account.consecutive_errors == 0
        mock_db.commit.assert_awaited_once()
        mock_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_probe_resets_cooldown(self):
        """Failed probe resets paused_at to now for next cooldown cycle."""
        from app.workers.health import _recover_paused_accounts

        now = datetime.now(UTC)
        account = self._make_account(
            paused_at=now - timedelta(minutes=10),
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [account]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def fake_get_session():
            yield mock_db

        with (
            patch("app.workers.health.get_session", fake_get_session),
            patch("app.workers.health.probe_imap_account",
                  AsyncMock(return_value=False)),
            patch("app.workers.health.get_event_bus") as mock_bus_fn,
        ):
            mock_bus = AsyncMock()
            mock_bus_fn.return_value = mock_bus
            await _recover_paused_accounts(now, cooldown_seconds=300)

        # Account stays paused, paused_at reset to now
        assert account.is_paused is True
        assert account.paused_at == now
        # No event emitted
        mock_bus.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cooldown_not_elapsed_skips_probe(self):
        """Account within cooldown window is not probed."""
        from app.workers.health import _recover_paused_accounts

        now = datetime.now(UTC)
        account = self._make_account(
            paused_at=now - timedelta(minutes=2),  # only 2 min, cooldown is 5
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [account]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def fake_get_session():
            yield mock_db

        probe_mock = AsyncMock(return_value=True)

        with (
            patch("app.workers.health.get_session", fake_get_session),
            patch("app.workers.health.probe_imap_account", probe_mock),
            patch("app.workers.health.get_event_bus") as mock_bus_fn,
        ):
            mock_bus = AsyncMock()
            mock_bus_fn.return_value = mock_bus
            await _recover_paused_accounts(now, cooldown_seconds=300)

        # Probe not called — cooldown hasn't elapsed
        probe_mock.assert_not_awaited()
        # Account stays paused
        assert account.is_paused is True


class TestRecoverPausedProviders:
    """AI provider recovery: cooldown + probe + unpause."""

    def _make_provider(self, *, paused_at):
        provider = MagicMock()
        provider.id = uuid4()
        provider.user_id = uuid4()
        provider.name = "test-provider"
        provider.provider_type = MagicMock(value="openai")
        provider.base_url = "https://api.openai.com"
        provider.api_key = b"encrypted"
        provider.is_paused = True
        provider.paused_at = paused_at
        provider.paused_reason = "llm_error"
        provider.consecutive_errors = 3
        return provider

    @pytest.mark.asyncio
    async def test_successful_probe_unpauses_provider(self):
        """Provider is unpaused when probe succeeds after cooldown."""
        from app.workers.health import _recover_paused_ai_providers

        now = datetime.now(UTC)
        provider = self._make_provider(
            paused_at=now - timedelta(minutes=5),  # past 2-min cooldown
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [provider]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def fake_get_session():
            yield mock_db

        with (
            patch("app.workers.health.get_session", fake_get_session),
            patch("app.workers.health.probe_ai_provider",
                  AsyncMock(return_value=True)),
            patch("app.workers.health.get_event_bus") as mock_bus_fn,
        ):
            mock_bus = AsyncMock()
            mock_bus_fn.return_value = mock_bus
            await _recover_paused_ai_providers(now, cooldown_seconds=120)

        assert provider.is_paused is False
        assert provider.paused_reason is None
        assert provider.paused_at is None
        assert provider.consecutive_errors == 0
        mock_db.commit.assert_awaited_once()
        mock_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failed_probe_resets_cooldown(self):
        """Failed probe resets paused_at to now."""
        from app.workers.health import _recover_paused_ai_providers

        now = datetime.now(UTC)
        provider = self._make_provider(
            paused_at=now - timedelta(minutes=5),
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [provider]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def fake_get_session():
            yield mock_db

        with (
            patch("app.workers.health.get_session", fake_get_session),
            patch("app.workers.health.probe_ai_provider",
                  AsyncMock(return_value=False)),
            patch("app.workers.health.get_event_bus") as mock_bus_fn,
        ):
            mock_bus = AsyncMock()
            mock_bus_fn.return_value = mock_bus
            await _recover_paused_ai_providers(now, cooldown_seconds=120)

        assert provider.is_paused is True
        assert provider.paused_at == now
        mock_bus.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cooldown_not_elapsed_skips_probe(self):
        """Provider within cooldown window is not probed."""
        from app.workers.health import _recover_paused_ai_providers

        now = datetime.now(UTC)
        provider = self._make_provider(
            paused_at=now - timedelta(seconds=60),  # only 60s, cooldown is 120s
        )

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [provider]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        async def fake_get_session():
            yield mock_db

        probe_mock = AsyncMock(return_value=True)

        with (
            patch("app.workers.health.get_session", fake_get_session),
            patch("app.workers.health.probe_ai_provider", probe_mock),
            patch("app.workers.health.get_event_bus") as mock_bus_fn,
        ):
            mock_bus = AsyncMock()
            mock_bus_fn.return_value = mock_bus
            await _recover_paused_ai_providers(now, cooldown_seconds=120)

        probe_mock.assert_not_awaited()
        assert provider.is_paused is True
