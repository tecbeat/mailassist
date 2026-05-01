"""Async SQLAlchemy engine and session factory.

Provides the async engine and a session dependency for FastAPI.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(settings: Settings) -> None:
    """Initialize the async engine and session factory.

    Called once during application startup.
    """
    global _engine, _session_factory
    _engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=settings.db_pool_recycle,
    )
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency that yields an async database session.

    Always commits after yielding.  An explicit ``flush()`` inside an
    endpoint clears ``session.new`` / ``session.dirty`` / ``session.deleted``,
    so the previous "smart-commit" check (``if session.new or …``) silently
    skipped the commit and the transaction was rolled back on session close.
    An unconditional ``commit()`` on a truly read-only session is essentially
    free (PostgreSQL treats it as a no-op) and avoids data-loss bugs.

    **Commit convention:** endpoints *must not* call ``await db.commit()``
    manually — the generator commits unconditionally after the endpoint
    returns.  A manual commit inside the endpoint is not harmful (PostgreSQL
    begins a new implicit transaction for the remaining work), but it is
    redundant and misleading.  Use ``await db.flush()`` if you need
    auto-generated IDs to be visible within the same request without
    ending the transaction early.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_session_ctx() -> AsyncGenerator[AsyncSession]:
    """Async context manager for obtaining a database session.

    Unlike ``get_session`` (an async generator designed as a FastAPI
    dependency), this function is safe to use with ``async with`` in
    application code.  It guarantees that the session is committed on
    success and rolled back + closed on error.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db() -> None:
    """Dispose the engine connection pool. Called on shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


def get_engine() -> AsyncEngine:
    """Return the current async engine (for Alembic migrations).

    Raises:
        RuntimeError: If the engine has not been initialized via init_db().
    """
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine
