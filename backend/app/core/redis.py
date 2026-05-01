"""Valkey (Redis-compatible) connection pool.

Manages connections for task queue (DB 0), sessions (DB 1), and cache (DB 2).
Uses redis-py which is wire-compatible with Valkey.
"""

import redis.asyncio as aioredis
from arq.connections import ArqRedis

from app.core.config import Settings

_task_client: aioredis.Redis | None = None
_task_binary_client: aioredis.Redis | None = None
_session_client: aioredis.Redis | None = None
_cache_client: aioredis.Redis | None = None


def _make_url(base_url: str, db: int) -> str:
    """Replace the DB number in a redis:// URL.

    Handles URLs with or without a trailing DB number
    (e.g. 'redis://host:6379' and 'redis://host:6379/0').
    """
    # Strip trailing slash to normalise
    base = base_url.rstrip("/")
    parts = base.rsplit("/", 1)
    # If the last segment is a digit, it's the DB number — replace it
    if len(parts) == 2 and parts[1].isdigit():
        return f"{parts[0]}/{db}"
    # No DB number in URL — just append it
    return f"{base}/{db}"


def init_valkey(settings: Settings) -> None:
    """Initialize Valkey connection clients for all three databases."""
    global _task_client, _task_binary_client, _session_client, _cache_client

    common_kwargs = {
        "socket_timeout": settings.valkey_socket_timeout,
        "socket_connect_timeout": settings.valkey_socket_connect_timeout,
        "socket_keepalive": True,
        # Proactively verify connections so stale ones are detected after a
        # Valkey restart rather than causing errors on the next request.
        "health_check_interval": 30,
    }

    _task_client = aioredis.from_url(  # type: ignore[no-untyped-call]
        _make_url(settings.valkey_url, 0),
        max_connections=20,
        decode_responses=True,
        **common_kwargs,
    )
    # Binary-mode client for reading raw ARQ job payloads (pickle-serialized).
    # Shares DB 0 but does NOT decode responses so callers get raw bytes.
    _task_binary_client = aioredis.from_url(  # type: ignore[no-untyped-call]
        _make_url(settings.valkey_url, 0),
        max_connections=5,
        decode_responses=False,
        **common_kwargs,
    )
    _session_client = aioredis.from_url(  # type: ignore[no-untyped-call]
        _make_url(settings.valkey_url, 1),
        max_connections=10,
        decode_responses=True,
        **common_kwargs,
    )
    _cache_client = aioredis.from_url(  # type: ignore[no-untyped-call]
        _make_url(settings.valkey_url, 2),
        max_connections=10,
        decode_responses=True,
        **common_kwargs,
    )


def get_task_client() -> aioredis.Redis:
    """Return the Valkey client for ARQ task queue (DB 0)."""
    if _task_client is None:
        raise RuntimeError("Valkey not initialized. Call init_valkey() first.")
    return _task_client


def get_task_binary_client() -> aioredis.Redis:
    """Return a binary-mode Valkey client for ARQ task queue (DB 0).

    Unlike ``get_task_client()`` this client does **not** decode
    responses, so callers receive raw ``bytes``.  Used by the dashboard
    to read pickle-serialized ARQ job payloads without creating a new
    connection per request.
    """
    if _task_binary_client is None:
        raise RuntimeError("Valkey not initialized. Call init_valkey() first.")
    return _task_binary_client


def get_arq_client() -> ArqRedis:
    """Return an ARQ-compatible client for enqueuing jobs.

    Reuses the existing task-queue connection pool so no extra
    connections are created.
    """
    return ArqRedis(pool_or_conn=get_task_client().connection_pool)


def get_session_client() -> aioredis.Redis:
    """Return the Valkey client for session storage (DB 1)."""
    if _session_client is None:
        raise RuntimeError("Valkey not initialized. Call init_valkey() first.")
    return _session_client


def get_cache_client() -> aioredis.Redis:
    """Return the Valkey client for cache (DB 2)."""
    if _cache_client is None:
        raise RuntimeError("Valkey not initialized. Call init_valkey() first.")
    return _cache_client


async def close_valkey() -> None:
    """Close all Valkey connections. Called on shutdown."""
    global _task_client, _task_binary_client, _session_client, _cache_client
    for client in (_task_client, _task_binary_client, _session_client, _cache_client):
        if client is not None:
            await client.aclose()
    _task_client = None
    _task_binary_client = None
    _session_client = None
    _cache_client = None
