"""Tests for the AI Providers API endpoints.

Covers list, create (first provider auto-assigns plugins), get, update,
delete, test, reset-health, and pause/unpause.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException


def _make_provider(*, user_id=None, is_default=True):
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        name="OpenAI",
        provider_type=SimpleNamespace(value="openai"),
        api_key=b"encrypted-key",
        base_url="https://api.openai.com/v1",
        model_name="gpt-4o",
        is_default=is_default,
        max_tokens=4096,
        temperature=0.7,
        consecutive_errors=0,
        last_error=None,
        last_error_at=None,
        is_paused=False,
        manually_paused=False,
        paused_reason=None,
        paused_at=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestListProviders:
    """GET /api/ai-providers"""

    @pytest.mark.asyncio
    async def test_returns_providers(self):
        from app.api.ai_providers import list_providers

        provider = _make_provider()
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = [provider]
        db.execute.return_value = result

        with patch("app.api.ai_providers.AIProviderResponse.model_validate", return_value=MagicMock()):
            resp = await list_providers(db=db, user_id=provider.user_id)

        assert len(resp) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        from app.api.ai_providers import list_providers

        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute.return_value = result

        resp = await list_providers(db=db, user_id=uuid4())
        assert resp == []


class TestCreateProvider:
    """POST /api/ai-providers"""

    @pytest.mark.asyncio
    async def test_creates_first_provider_auto_assigns_plugins(self):
        from app.api.ai_providers import create_provider
        from app.schemas.ai_provider import AIProviderCreate

        db = AsyncMock()
        uid = uuid4()
        data = AIProviderCreate(
            name="OpenAI",
            provider_type="openai",
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o",
        )

        # existing_count = 0
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        db.execute.return_value = count_result

        mock_settings = MagicMock()
        mock_settings.plugin_provider_map = {}

        with (
            patch("app.api.ai_providers.get_encryption") as mock_enc,
            patch("app.api.ai_providers.AIProviderResponse.model_validate", return_value=MagicMock()),
            patch("app.api.ai_providers.get_or_create", new=AsyncMock(return_value=mock_settings)),
        ):
            mock_enc.return_value.encrypt.return_value = b"encrypted"
            await create_provider(data=data, db=db, user_id=uid)

        db.add.assert_called_once()
        db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_creates_second_provider_no_auto_assign(self):
        from app.api.ai_providers import create_provider
        from app.schemas.ai_provider import AIProviderCreate

        db = AsyncMock()
        uid = uuid4()
        data = AIProviderCreate(
            name="Ollama",
            provider_type="ollama",
            base_url="http://localhost:11434",
            model_name="llama3",
        )

        # existing_count = 1
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        db.execute.return_value = count_result

        with (
            patch("app.api.ai_providers.get_encryption") as mock_enc,
            patch("app.api.ai_providers.AIProviderResponse.model_validate", return_value=MagicMock()),
        ):
            mock_enc.return_value.encrypt.return_value = b"encrypted"
            await create_provider(data=data, db=db, user_id=uid)

        db.add.assert_called_once()


class TestGetProvider:
    """GET /api/ai-providers/{provider_id}"""

    @pytest.mark.asyncio
    async def test_returns_provider(self):
        from app.api.ai_providers import get_provider

        provider = _make_provider()
        db = AsyncMock()

        with (
            patch("app.api.ai_providers.get_or_404", new=AsyncMock(return_value=provider)),
            patch("app.api.ai_providers.AIProviderResponse.model_validate", return_value=MagicMock()),
        ):
            await get_provider(provider_id=provider.id, db=db, user_id=provider.user_id)

    @pytest.mark.asyncio
    async def test_not_found_raises_404(self):
        from app.api.ai_providers import get_provider

        db = AsyncMock()

        with patch("app.api.ai_providers.get_or_404", new=AsyncMock(side_effect=HTTPException(status_code=404))):
            with pytest.raises(HTTPException) as exc_info:
                await get_provider(provider_id=uuid4(), db=db, user_id=uuid4())
            assert exc_info.value.status_code == 404


class TestUpdateProvider:
    """PUT /api/ai-providers/{provider_id}"""

    @pytest.mark.asyncio
    async def test_updates_provider_fields(self):
        from app.api.ai_providers import update_provider
        from app.schemas.ai_provider import AIProviderUpdate

        provider = _make_provider()
        db = AsyncMock()
        data = AIProviderUpdate(name="Updated Name")

        with (
            patch("app.api.ai_providers.get_or_404", new=AsyncMock(return_value=provider)),
            patch("app.api.ai_providers.get_encryption") as mock_enc,
            patch("app.api.ai_providers.AIProviderResponse.model_validate", return_value=MagicMock()),
        ):
            mock_enc.return_value.encrypt.return_value = b"encrypted"
            await update_provider(provider_id=provider.id, data=data, db=db, user_id=provider.user_id)

        assert provider.name == "Updated Name"
        db.flush.assert_awaited_once()


class TestDeleteProvider:
    """DELETE /api/ai-providers/{provider_id}"""

    @pytest.mark.asyncio
    async def test_deletes_provider(self):
        from app.api.ai_providers import delete_provider

        provider = _make_provider()
        db = AsyncMock()

        with patch("app.api.ai_providers.get_or_404", new=AsyncMock(return_value=provider)):
            await delete_provider(provider_id=provider.id, db=db, user_id=provider.user_id)

        db.delete.assert_awaited_once_with(provider)


class TestTestProvider:
    """POST /api/ai-providers/{provider_id}/test"""

    @pytest.mark.asyncio
    async def test_successful_test(self):
        from app.api.ai_providers import test_provider

        provider = _make_provider()
        db = AsyncMock()

        test_result = SimpleNamespace(success=True, message="OK", details={"model": "gpt-4o"})

        with (
            patch("app.api.ai_providers.get_or_404", new=AsyncMock(return_value=provider)),
            patch("app.api.ai_providers.get_encryption") as mock_enc,
            patch("app.services.ai.test_llm_connection", new=AsyncMock(return_value=test_result)),
        ):
            mock_enc.return_value.decrypt.return_value = "sk-test"
            resp = await test_provider(provider_id=provider.id, db=db, user_id=provider.user_id)

        assert resp.success is True


class TestResetProviderHealth:
    """POST /api/ai-providers/{provider_id}/reset-health"""

    @pytest.mark.asyncio
    async def test_resets_health(self):
        from app.api.ai_providers import reset_provider_health

        provider = _make_provider()
        provider.consecutive_errors = 5
        provider.is_paused = True
        db = AsyncMock()

        with (
            patch("app.api.ai_providers.get_or_404", new=AsyncMock(return_value=provider)),
            patch("app.api.ai_providers.AIProviderResponse.model_validate", return_value=MagicMock()),
        ):
            await reset_provider_health(provider_id=provider.id, db=db, user_id=provider.user_id)

        assert provider.consecutive_errors == 0
        assert provider.is_paused is False
        db.flush.assert_awaited_once()


class TestUpdatePauseState:
    """PATCH /api/ai-providers/{provider_id}/pause"""

    @pytest.mark.asyncio
    async def test_pause_provider(self):
        from app.api.ai_providers import update_pause_state
        from app.schemas.ai_provider import PauseUpdate

        provider = _make_provider()
        db = AsyncMock()
        data = PauseUpdate(paused=True, pause_reason="Maintenance")

        with (
            patch("app.api.ai_providers.get_or_404", new=AsyncMock(return_value=provider)),
            patch("app.api.ai_providers.AIProviderResponse.model_validate", return_value=MagicMock()),
        ):
            await update_pause_state(provider_id=provider.id, data=data, db=db, user_id=provider.user_id)

        assert provider.is_paused is True
        assert provider.manually_paused is True
        assert provider.paused_reason == "Maintenance"

    @pytest.mark.asyncio
    async def test_unpause_provider(self):
        from app.api.ai_providers import update_pause_state
        from app.schemas.ai_provider import PauseUpdate

        provider = _make_provider()
        provider.is_paused = True
        provider.consecutive_errors = 3
        db = AsyncMock()
        data = PauseUpdate(paused=False)

        with (
            patch("app.api.ai_providers.get_or_404", new=AsyncMock(return_value=provider)),
            patch("app.api.ai_providers.AIProviderResponse.model_validate", return_value=MagicMock()),
            patch("app.core.redis.get_arq_client", return_value=MagicMock()),
            patch("app.workers.scheduler.schedule_now", new=AsyncMock()),
        ):
            await update_pause_state(provider_id=provider.id, data=data, db=db, user_id=provider.user_id)

        assert provider.is_paused is False
        assert provider.consecutive_errors == 0
