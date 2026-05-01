"""Shared FastAPI dependencies and utility helpers.

Provides database session, current user, generic get-or-404,
pagination helpers, and the paginated-response builder via FastAPI's
Depends() mechanism.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_session


def get_cached_settings() -> Settings:
    """Return the cached settings singleton (caching handled by get_settings)."""
    return get_settings()


# Imported here to avoid circular imports at module level — auth depends on
# deps indirectly, but get_current_user_id is a leaf dependency.
from app.api.auth import get_current_user_id  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Sequence

# Type aliases for dependency injection
SettingsDep = Annotated[Settings, Depends(get_cached_settings)]
DbSession = Annotated[AsyncSession, Depends(get_session)]
CurrentUserId = Annotated[UUID, Depends(get_current_user_id)]


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------


async def get_or_404[T](
    db: AsyncSession,
    model: type[T],
    record_id: UUID,
    user_id: UUID,
    detail: str = "Not found",
) -> T:
    """Fetch a single record by ID scoped to a user, or raise 404.

    Args:
        db: Async database session.
        model: SQLAlchemy model class (must have ``id`` and ``user_id`` columns).
        record_id: Primary key value.
        user_id: Current user UUID.
        detail: Error message for the 404 response.

    Returns:
        The model instance.

    Raises:
        HTTPException: 404 if the record does not exist or belongs to another user.
    """
    stmt = select(model).where(
        model.id == record_id,  # type: ignore[attr-defined]
        model.user_id == user_id,  # type: ignore[attr-defined]
    )
    result = await db.execute(stmt)
    instance = result.scalar_one_or_none()
    if instance is None:
        raise HTTPException(status_code=404, detail=detail)
    return instance


class PaginatedResult:
    """Container for paginated query results."""

    __slots__ = ("items", "page", "pages", "per_page", "total")

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


def build_paginated_response[Item: BaseModel, List](
    result: PaginatedResult,
    item_schema: type[Item],
    list_schema: type[List],
) -> List:
    """Convert a :class:`PaginatedResult` into a typed list-response schema.

    Eliminates the boilerplate ``XListResponse(items=[X.model_validate(r) for r
    in result.items], total=..., page=..., per_page=..., pages=...)`` that
    appears across all list endpoints.

    Args:
        result: Paginated query result returned by :func:`paginate`.
        item_schema: Pydantic schema class used to validate each ORM row.
        list_schema: List-response schema class whose constructor accepts
            ``items``, ``total``, ``page``, ``per_page``, and ``pages``.

    Returns:
        An instance of ``list_schema`` populated with validated items and
        pagination metadata.

    Example::

        result = await paginate(db, stmt, page, per_page)
        return build_paginated_response(result, MyResponse, MyListResponse)
    """
    return list_schema(  # type: ignore[call-arg]
        items=[item_schema.model_validate(r) for r in result.items],
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
    )


async def get_or_create[T](
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
