"""Shared FastAPI dependencies and utility helpers.

Provides database session, current user, generic get-or-404,
and pagination helpers via FastAPI's Depends() mechanism.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Annotated, Any, Sequence, TypeVar
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session


@lru_cache
def get_cached_settings() -> Settings:
    """Cached settings singleton."""
    return get_settings()


from app.api.auth import get_current_user_id


# Type aliases for dependency injection
SettingsDep = Annotated[Settings, Depends(get_cached_settings)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentUserId = Annotated[str, Depends(get_current_user_id)]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

T = TypeVar("T")


async def get_or_404(
    db: AsyncSession,
    model: type[T],
    record_id: UUID,
    user_id: str,
    detail: str = "Not found",
) -> T:
    """Fetch a single record by ID scoped to a user, or raise 404.

    Args:
        db: Async database session.
        model: SQLAlchemy model class (must have ``id`` and ``user_id`` columns).
        record_id: Primary key value.
        user_id: Current user ID (string, converted to UUID internally).
        detail: Error message for the 404 response.

    Returns:
        The model instance.

    Raises:
        HTTPException: 404 if the record does not exist or belongs to another user.
    """
    stmt = select(model).where(
        model.id == record_id,  # type: ignore[attr-defined]
        model.user_id == UUID(user_id),  # type: ignore[attr-defined]
    )
    result = await db.execute(stmt)
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail=detail)
    return instance


class PaginatedResult:
    """Container for paginated query results."""

    __slots__ = ("items", "total", "page", "per_page", "pages")

    def __init__(
        self,
        items: Sequence[Any],
        total: int,
        page: int,
        per_page: int,
        pages: int,
    ) -> None:
        self.items = items
        self.total = total
        self.page = page
        self.per_page = per_page
        self.pages = pages


async def paginate(
    db: AsyncSession,
    base_stmt: Select[Any],
    page: int,
    per_page: int,
    *,
    scalars: bool = True,
) -> PaginatedResult:
    """Execute a count + paginated query and return results with metadata.

    The project uses two intentional pagination tiers:

    - **Activity streams** (``per_page=50, le=200``): high-volume, append-only
      data — approvals, contacts, dashboard recent-actions,
      dashboard errors.
    - **Entity lists** (``per_page=20, le=100``): slower-growing domain objects
      — coupons, newsletters, reprocessing jobs, summaries.
    - **No pagination**: datasets that remain small per-user — rules,
      mail_accounts, ai_providers, prompts.

    Args:
        db: Async database session.
        base_stmt: Base SELECT statement (before ordering if desired; caller
            should apply ``.order_by()`` before passing).
        page: 1-indexed page number.
        per_page: Items per page.
        scalars: If True (default), call ``result.scalars().all()`` to unwrap
            ORM model instances.  Set to False for queries that return raw
            rows (e.g. union subqueries with ``select(subquery)``).

    Returns:
        A ``PaginatedResult`` with ``items``, ``total``, ``page``,
        ``per_page``, and ``pages``.
    """
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total: int = (await db.execute(count_stmt)).scalar_one()

    pages = max(1, math.ceil(total / per_page))
    offset = (page - 1) * per_page

    result = await db.execute(base_stmt.offset(offset).limit(per_page))
    items = result.scalars().all() if scalars else result.all()

    return PaginatedResult(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


async def get_or_create(
    db: AsyncSession,
    model: type[T],
    user_id: UUID,
    **defaults: Any,
) -> T:
    """Fetch a singleton config record for a user, creating it if absent.

    Args:
        db: Async database session.
        model: SQLAlchemy model class (must have a ``user_id`` column).
        user_id: Owner UUID.
        **defaults: Extra column values passed to the constructor when creating.

    Returns:
        The existing or newly-created model instance.
    """
    stmt = select(model).where(
        model.user_id == user_id,  # type: ignore[attr-defined]
    )
    result = await db.execute(stmt)
    instance = result.scalar_one_or_none()

    if instance is None:
        instance = model(user_id=user_id, **defaults)  # type: ignore[call-arg]
        db.add(instance)
        await db.flush()

    return instance


def sanitize_like(value: str) -> str:
    """Escape SQL LIKE wildcards (``%`` and ``_``) in user input.

    Returns a pattern suitable for ``column.ilike(f"%{escaped}%")``.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
