"""AI provider resolution helpers.

Centralizes the logic for finding a user's default AI provider and
resolving per-plugin provider assignments.  Previously duplicated
across mail_processor.py, pipeline.py, and rules.py.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIProvider


async def get_default_provider(db: AsyncSession, user_id: UUID) -> AIProvider | None:
    """Fetch the user's fallback AI provider.

    Resolution order:
    1. Non-paused provider with ``is_default=True`` (user-designated default).
    2. Oldest non-paused provider (fallback when no explicit default exists
       or the default was paused by the circuit breaker).

    Only non-paused providers are considered so that a paused/circuit-broken
    provider does not silently suppress the entire AI pipeline.
    """
    # Try explicit default first
    stmt = (
        select(AIProvider)
        .where(
            AIProvider.user_id == user_id,
            AIProvider.is_paused.is_(False),
            AIProvider.is_default.is_(True),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    provider = result.scalar_one_or_none()
    if provider is not None:
        return provider

    # Fallback: oldest non-paused provider
    stmt = (
        select(AIProvider)
        .where(
            AIProvider.user_id == user_id,
            AIProvider.is_paused.is_(False),
        )
        .order_by(AIProvider.created_at)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def resolve_plugin_provider(
    plugin_name: str,
    plugin_provider_map: dict[str, str],
    providers_by_id: dict[str, AIProvider],
    default_provider: AIProvider | None,
) -> AIProvider | None:
    """Resolve the AI provider for a specific plugin.

    Checks the per-plugin provider map first, falls back to the default provider.
    """
    assigned_id = plugin_provider_map.get(plugin_name)
    if assigned_id and assigned_id in providers_by_id:
        return providers_by_id[assigned_id]
    return default_provider
