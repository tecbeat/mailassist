"""Contact matching service.

Resolves email senders to cached contacts via Valkey cache
and JSON array containment queries on Contact.emails.
"""

from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_cache_client
from app.models import Contact

logger = structlog.get_logger()


def _get_contact_cache_ttl() -> int:
    """Return contact cache TTL from settings."""
    return get_settings().contact_cache_ttl_seconds


async def match_sender_to_contact(
    db: AsyncSession,
    user_id: UUID,
    sender_email: str,
) -> Contact | None:
    """Match an email sender to a cached contact.

    Lookup order:
        1. Valkey cache (key ``contact_match:{user_id}:{email_lower}``)
        2. ``Contact.emails`` JSON array containment (PostgreSQL ``@>`` operator)

    Results are cached in Valkey with a configurable TTL. No database writes
    are performed — this function is purely read-only.

    Args:
        db: Async database session.
        user_id: Owner of the contacts.
        sender_email: Email address to match.

    Returns:
        The matched ``Contact``, or ``None`` if no match was found.
    """
    email_lower = sender_email.lower()
    cache = get_cache_client()

    # --- Tier 1: Valkey cache ---
    cache_key = f"contact_match:{user_id}:{email_lower}"
    cached_id = await cache.get(cache_key)
    if cached_id:
        if cached_id == "none":
            return None
        stmt = select(Contact).where(Contact.id == UUID(cached_id))
        result = await db.execute(stmt)
        contact = result.scalar_one_or_none()
        if contact:
            return contact
        # Cached ID points to a deleted contact — fall through to re-query
        logger.warning(
            "cached_contact_missing",
            contact_id=cached_id,
            email=email_lower,
        )

    # --- Tier 2: Contact.emails JSON array containment ---
    contact_stmt = (
        select(Contact)
        .where(
            Contact.user_id == user_id,
            Contact.emails.contains([email_lower]),
        )
        .limit(1)
    )
    contact_result = await db.execute(contact_stmt)
    contact = contact_result.scalar_one_or_none()

    if contact:
        await cache.setex(cache_key, _get_contact_cache_ttl(), str(contact.id))
        return contact

    # No match — cache the miss
    await cache.setex(cache_key, _get_contact_cache_ttl(), "none")
    return None
