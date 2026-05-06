"""Contact matching service.

Resolves email senders to cached contacts via Valkey cache
and JSON array containment queries on Contact.emails.
Also provides contact pre-filtering and scoring for the AI
contact assignment plugin.
"""

from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import String as SAString
from sqlalchemy import cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_cache_client
from app.models import Contact

logger = structlog.get_logger()

_NAME_STOPWORDS = frozenset(
    {
        "dr",
        "mr",
        "mrs",
        "ms",
        "prof",
        "ing",
        "mag",
        "von",
        "van",
        "de",
        "del",
        "der",
        "die",
        "das",
        "the",
        "and",
        "und",
        "jr",
        "sr",
        "ii",
        "iii",
        "msc",
        "bsc",
        "phd",
        "mba",
    }
)


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


async def find_relevant_contacts_for_sender(
    db: AsyncSession,
    user_id: UUID,
    sender_email: str,
    sender_name: str | None,
    *,
    max_contacts: int = 30,
    sql_limit: int = 200,
) -> list[dict[str, Any]]:
    """Find and score contacts relevant to a sender for AI prompt context.

    Pre-filters contacts in SQL by email/domain/name match, then scores
    them by relevance.  Returns the top ``max_contacts`` with score > 0,
    serialized as dicts suitable for prompt injection.

    Args:
        db: Async database session.
        user_id: Owner of the contacts.
        sender_email: Sender's email address.
        sender_name: Sender's display name (may be None).
        max_contacts: Maximum contacts to return.
        sql_limit: Maximum rows to load from DB.

    Returns:
        List of contact dicts sorted by descending relevance score.
    """
    email_lower = (sender_email or "").lower()
    domain = email_lower.split("@")[-1] if "@" in email_lower else ""
    name_lower = (sender_name or "").lower().strip()

    # Pre-filter contacts in SQL
    stmt = select(Contact).where(Contact.user_id == user_id)
    sql_filters = []
    if email_lower:
        sql_filters.append(cast(Contact.emails, SAString).ilike(f"%{email_lower}%"))
    if domain:
        sql_filters.append(cast(Contact.emails, SAString).ilike(f"%{domain}%"))
    if name_lower and len(name_lower) >= 3:
        sql_filters.append(Contact.display_name.ilike(f"%{name_lower}%"))
    if sql_filters:
        stmt = stmt.where(or_(*sql_filters))
    stmt = stmt.limit(sql_limit)

    result = await db.execute(stmt)
    all_contacts = result.scalars().all()

    # Tokenize sender name for scoring
    sender_name_parts = (
        {t for t in name_lower.split() if len(t) >= 3 and t not in _NAME_STOPWORDS} if name_lower else set()
    )

    scored: list[tuple[float, Contact]] = []
    for c in all_contacts:
        score = 0.0
        c_emails = [e.lower() for e in (c.emails or [])]

        # Exact email match → highest score
        if email_lower and email_lower in c_emails:
            score += 100.0
        # Same domain → exact domain comparison
        elif domain:
            c_domains = {e.split("@")[-1] for e in c_emails if "@" in e}
            if domain in c_domains:
                score += 10.0

        # Name overlap → score per overlapping token
        c_name_parts = {t for t in (c.display_name or "").lower().split() if len(t) >= 3 and t not in _NAME_STOPWORDS}
        if c.first_name and len(c.first_name) >= 3:
            c_name_parts.add(c.first_name.lower())
        if c.last_name and len(c.last_name) >= 3:
            c_name_parts.add(c.last_name.lower())
        overlap = sender_name_parts & c_name_parts
        score += len(overlap) * 5.0

        # Organization match → exact domain comparison
        if c.organization and domain:
            org_domain = c.organization.lower().replace(" ", "")
            if org_domain == domain.split(".")[0]:
                score += 8.0

        scored.append((score, c))

    # Sort by score descending, take top N with score > 0
    scored.sort(key=lambda x: x[0], reverse=True)
    contacts_data: list[dict[str, Any]] = []
    for _score, c in scored[:max_contacts]:
        if _score <= 0.0:
            break
        contacts_data.append(
            {
                "id": str(c.id),
                "display_name": c.display_name,
                "first_name": c.first_name,
                "last_name": c.last_name,
                "organization": c.organization,
                "title": c.title,
                "emails": c.emails,
            }
        )

    return contacts_data
