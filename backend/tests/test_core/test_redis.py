"""Tests for app.core.redis."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.redis import (
    _make_url,
    close_valkey,
    get_cache_client,
    get_session_client,
    get_task_binary_client,
    get_task_client,
    init_valkey,
)

# ---------------------------------------------------------------------------
# _make_url
# ---------------------------------------------------------------------------


class TestMakeUrl:
    def test_replace_db_number(self):
        assert _make_url("redis://host:6379/0", 2) == "redis://host:6379/2"

    def test_append_db_number(self):
        assert _make_url("redis://host:6379", 1) == "redis://host:6379/1"

    def test_trailing_slash(self):
        assert _make_url("redis://host:6379/", 3) == "redis://host:6379/3"

    def test_replace_existing_db(self):
        assert _make_url("redis://host:6379/5", 0) == "redis://host:6379/0"


# ---------------------------------------------------------------------------
# Uninitialized access raises RuntimeError
# ---------------------------------------------------------------------------


class TestUninitializedAccess:
    def setup_method(self):
        """Reset module-level clients to None."""
        import app.core.redis as redis_mod

        self._mod = redis_mod
        self._orig = (
            redis_mod._task_client,
            redis_mod._task_binary_client,
            redis_mod._session_client,
            redis_mod._cache_client,
        )
        redis_mod._task_client = None
        redis_mod._task_binary_client = None
        redis_mod._session_client = None
        redis_mod._cache_client = None

    def teardown_method(self):
        (
            self._mod._task_client,
            self._mod._task_binary_client,
            self._mod._session_client,
            self._mod._cache_client,
        ) = self._orig

    def test_get_task_client_raises(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_task_client()

    def test_get_task_binary_client_raises(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_task_binary_client()

    def test_get_session_client_raises(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_session_client()

    def test_get_cache_client_raises(self):
        with pytest.raises(RuntimeError, match="not initialized"):
            get_cache_client()


# ---------------------------------------------------------------------------
# init_valkey + getters
# ---------------------------------------------------------------------------


class TestInitValkey:
    def test_init_and_get_clients(self):
        mock_client = MagicMock()

        with patch("app.core.redis.aioredis.from_url", return_value=mock_client):
            settings = MagicMock()
            settings.valkey_url = "redis://localhost:6379/0"
            settings.valkey_socket_timeout = 5
            settings.valkey_socket_connect_timeout = 5

            init_valkey(settings)

            assert get_task_client() is mock_client
            assert get_task_binary_client() is mock_client
            assert get_session_client() is mock_client
            assert get_cache_client() is mock_client


# ---------------------------------------------------------------------------
# close_valkey
# ---------------------------------------------------------------------------


class TestCloseValkey:
    @pytest.mark.asyncio
    async def test_close_all_clients(self):
        import app.core.redis as redis_mod

        clients = [AsyncMock() for _ in range(4)]
        redis_mod._task_client = clients[0]
        redis_mod._task_binary_client = clients[1]
        redis_mod._session_client = clients[2]
        redis_mod._cache_client = clients[3]

        await close_valkey()

        for client in clients:
            client.aclose.assert_awaited_once()

        assert redis_mod._task_client is None
        assert redis_mod._task_binary_client is None
        assert redis_mod._session_client is None
        assert redis_mod._cache_client is None

    @pytest.mark.asyncio
    async def test_close_with_none_clients(self):
        import app.core.redis as redis_mod

        redis_mod._task_client = None
        redis_mod._task_binary_client = None
        redis_mod._session_client = None
        redis_mod._cache_client = None

        # Should not raise
        await close_valkey()
