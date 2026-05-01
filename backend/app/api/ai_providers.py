"""AI provider CRUD API endpoints.

Provides configuration management for AI/LLM providers (OpenAI, Ollama).
Credentials are write-only -- GET endpoints never return API keys.
"""

from datetime import UTC, datetime
from uuid import UUID

import structlog
from fastapi import APIRouter
from sqlalchemy import func, select, update

from app.api.deps import CurrentUserId, DbSession, get_or_404, get_or_create
from app.core.constants import PIPELINE_PLUGIN_NAMES
from app.core.security import get_encryption
from app.models import AIProvider, UserSettings
from app.plugins.registry import get_plugin_registry
from app.schemas.ai_provider import (
    AIProviderCreate,
    AIProviderResponse,
    AIProviderTestResult,
    AIProviderUpdate,
    PauseUpdate,
    PluginInfo,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/ai-providers", tags=["ai-providers"])


@router.get("")
async def list_providers(
    db: DbSession,
    user_id: CurrentUserId,
) -> list[AIProviderResponse]:
    """List all AI providers for the current user."""
    stmt = select(AIProvider).where(AIProvider.user_id == UUID(user_id)).order_by(AIProvider.created_at)
    result = await db.execute(stmt)
    providers = result.scalars().all()
    return [AIProviderResponse.model_validate(p) for p in providers]


@router.post("", status_code=201)
async def create_provider(
    data: AIProviderCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> AIProviderResponse:
    """Create a new AI provider with encrypted API key.

    When the user creates their first provider, all pipeline plugins
    are auto-assigned to it so the pipeline works out of the box.
    """
    uid = UUID(user_id)
    encryption = get_encryption()

    encrypted_key = None
    if data.api_key:
        encrypted_key = encryption.encrypt(data.api_key)

    # Check whether this is the user's first provider
    count_stmt = select(func.count()).where(AIProvider.user_id == uid)
    existing_count = (await db.execute(count_stmt)).scalar_one()

    provider = AIProvider(
        user_id=uid,
        name=data.name,
        provider_type=data.provider_type,
        api_key=encrypted_key,
        base_url=data.base_url,
        model_name=data.model_name,
        is_default=existing_count == 0,
        max_tokens=data.max_tokens,
        temperature=data.temperature,
    )
    db.add(provider)
    await db.flush()

    # Auto-assign all plugins to the first provider
    if existing_count == 0:
        settings = await get_or_create(db, UserSettings, uid)
        settings.plugin_provider_map = {name: str(provider.id) for name in PIPELINE_PLUGIN_NAMES}
        logger.info(
            "auto_assigned_plugins_to_first_provider",
            provider_id=str(provider.id),
            user_id=user_id,
        )

    logger.info("ai_provider_created", provider_id=str(provider.id), user_id=user_id)
    return AIProviderResponse.model_validate(provider)


@router.get("/plugins", name="list_plugins")
async def list_plugins(
    db: DbSession,
    user_id: CurrentUserId,
) -> list[PluginInfo]:
    """List all available plugins, sorted by user-defined order if set."""
    registry = get_plugin_registry()
    plugin_infos = [PluginInfo(**info) for info in registry.get_plugin_info()]

    # Respect user-defined plugin order if stored in settings
    settings = await get_or_create(db, UserSettings, UUID(user_id))
    if settings.plugin_order:
        order_map = {name: idx for idx, name in enumerate(settings.plugin_order)}
        fallback = len(order_map)
        plugin_infos.sort(key=lambda p: order_map.get(p.name, fallback))

    return plugin_infos


@router.get("/{provider_id}")
async def get_provider(
    provider_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> AIProviderResponse:
    """Get a single AI provider (API key excluded)."""
    provider = await get_or_404(db, AIProvider, provider_id, user_id, "AI provider not found")
    return AIProviderResponse.model_validate(provider)


@router.put("/{provider_id}")
async def update_provider(
    provider_id: UUID,
    data: AIProviderUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> AIProviderResponse:
    """Update an AI provider. Only provided fields are updated."""
    uid = UUID(user_id)
    provider = await get_or_404(db, AIProvider, provider_id, user_id, "AI provider not found")
    encryption = get_encryption()

    update_data = data.model_dump(exclude_unset=True)

    # Handle API key update separately
    if "api_key" in update_data:
        api_key = update_data.pop("api_key")
        provider.api_key = encryption.encrypt(api_key) if api_key else None

    # Exclusive toggle: when setting is_default=True, clear the flag on
    # all other providers for this user first.
    if update_data.get("is_default") is True:
        await db.execute(
            update(AIProvider).where(AIProvider.user_id == uid, AIProvider.id != provider_id).values(is_default=False)
        )

    for field, value in update_data.items():
        setattr(provider, field, value)

    await db.flush()
    logger.info("ai_provider_updated", provider_id=str(provider_id), user_id=user_id)
    return AIProviderResponse.model_validate(provider)


@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete an AI provider."""
    provider = await get_or_404(db, AIProvider, provider_id, user_id, "AI provider not found")
    await db.delete(provider)
    logger.info("ai_provider_deleted", provider_id=str(provider_id), user_id=user_id)


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> AIProviderTestResult:
    """Test connectivity to an AI provider."""
    provider = await get_or_404(db, AIProvider, provider_id, user_id, "AI provider not found")
    encryption = get_encryption()

    api_key = None
    if provider.api_key:
        api_key = encryption.decrypt(provider.api_key)

    from app.services.ai import test_llm_connection

    result = await test_llm_connection(
        provider_type=provider.provider_type.value,
        base_url=provider.base_url,
        model_name=provider.model_name,
        api_key=api_key,
    )
    return AIProviderTestResult(
        success=result.success,
        message=result.message,
        model=(result.details or {}).get("model", ""),
    )


@router.post("/{provider_id}/reset-health")
async def reset_provider_health(
    provider_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> AIProviderResponse:
    """Reset an AI provider's health status (clear circuit breaker).

    Re-enables a provider that was paused due to consecutive errors.
    Use this after fixing the underlying issue (e.g. renewed API key,
    restored network connectivity).
    """
    provider = await get_or_404(db, AIProvider, provider_id, user_id, "AI provider not found")
    provider.consecutive_errors = 0
    provider.last_error = None
    provider.last_error_at = None
    provider.is_paused = False
    provider.manually_paused = False
    provider.paused_reason = None
    provider.paused_at = None
    await db.flush()
    logger.info(
        "ai_provider_health_reset",
        provider_id=str(provider_id),
        user_id=user_id,
    )
    return AIProviderResponse.model_validate(provider)


@router.patch("/{provider_id}/pause")
async def update_pause_state(
    provider_id: UUID,
    data: PauseUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> AIProviderResponse:
    """Update the pause state of an AI provider.

    When ``paused`` is true the provider is paused — the scheduler will
    skip it until it is unpaused.  When ``paused`` is false the pause
    flag, error counters and the error history are cleared and the
    scheduler is triggered immediately.
    """
    provider = await get_or_404(db, AIProvider, provider_id, user_id, "AI provider not found")

    if data.paused:
        provider.is_paused = True
        provider.manually_paused = True
        provider.paused_reason = data.pause_reason
        provider.paused_at = datetime.now(UTC)
        await db.flush()
        logger.info("ai_provider_paused", provider_id=str(provider_id), user_id=user_id, reason=data.pause_reason)
    else:
        provider.is_paused = False
        provider.manually_paused = False
        provider.paused_reason = None
        provider.paused_at = None
        provider.consecutive_errors = 0
        provider.last_error = None
        provider.last_error_at = None
        await db.flush()
        logger.info("ai_provider_unpaused", provider_id=str(provider_id), user_id=user_id)

        from app.core.redis import get_arq_client
        from app.workers.scheduler import schedule_now

        await schedule_now(get_arq_client())

    return AIProviderResponse.model_validate(provider)
