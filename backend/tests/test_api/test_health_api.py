"""Tests for the Health Check API endpoint.

Covers healthy state, degraded state (Postgres down, Valkey down).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestHealthCheck:
    """GET /health"""

    @pytest.mark.asyncio
    async def test_all_healthy(self):
        from app.api.health import health_check

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_valkey = AsyncMock()
        mock_valkey.ping.return_value = True

        mock_settings = MagicMock()
        mock_settings.version = "1.0.0"

        with (
            patch("app.api.health.get_engine", return_value=mock_engine),
            patch("app.api.health.get_task_client", return_value=mock_valkey),
            patch("app.api.health.get_settings", return_value=mock_settings),
        ):
            resp = await health_check()

        assert resp.status_code == 200
        assert resp.body is not None

    @pytest.mark.asyncio
    async def test_postgres_down_returns_503(self):
        from app.api.health import health_check

        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("Connection refused")

        mock_valkey = AsyncMock()
        mock_valkey.ping.return_value = True

        mock_settings = MagicMock()
        mock_settings.version = "1.0.0"

        with (
            patch("app.api.health.get_engine", return_value=mock_engine),
            patch("app.api.health.get_task_client", return_value=mock_valkey),
            patch("app.api.health.get_settings", return_value=mock_settings),
        ):
            resp = await health_check()

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_valkey_down_returns_503(self):
        from app.api.health import health_check

        mock_conn = AsyncMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_valkey = AsyncMock()
        mock_valkey.ping.side_effect = Exception("Connection refused")

        mock_settings = MagicMock()
        mock_settings.version = "1.0.0"

        with (
            patch("app.api.health.get_engine", return_value=mock_engine),
            patch("app.api.health.get_task_client", return_value=mock_valkey),
            patch("app.api.health.get_settings", return_value=mock_settings),
        ):
            resp = await health_check()

        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_engine_not_initialized(self):
        from app.api.health import health_check

        mock_valkey = AsyncMock()
        mock_valkey.ping.return_value = True

        mock_settings = MagicMock()
        mock_settings.version = "1.0.0"

        with (
            patch("app.api.health.get_engine", return_value=None),
            patch("app.api.health.get_task_client", return_value=mock_valkey),
            patch("app.api.health.get_settings", return_value=mock_settings),
        ):
            resp = await health_check()

        assert resp.status_code == 503
