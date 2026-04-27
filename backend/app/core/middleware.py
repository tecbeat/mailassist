"""HTTP middleware for security headers, CSRF, rate limiting, request size, and correlation IDs.

Implements Tasks 41 (security headers), 42 (rate limiting), 43 (input size),
and 45 (correlation IDs) from Phase 7, plus CSRF protection via double-submit cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from uuid import uuid4

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings
from app.core.redis import get_cache_client, get_session_client

logger = structlog.get_logger()

# Paths excluded from rate limiting (health check, static, auth callback)
_RATE_LIMIT_EXEMPT_PATHS = frozenset({"/health", "/docs", "/openapi.json"})

# Paths excluded from CSRF checks (auth callback needs to accept POST without CSRF)
_CSRF_EXEMPT_PATHS = frozenset({"/auth/callback", "/auth/login", "/health"})

# HTTP methods that require CSRF protection (state-changing)
_CSRF_PROTECTED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Max request body size: 1 MB
_MAX_REQUEST_BODY_BYTES = 1_048_576

# Paths logged at debug level to reduce noise
_LOG_QUIET_PATHS = frozenset({"/health", "/docs", "/openapi.json"})


# ---------------------------------------------------------------------------
# Security Headers (Task 41)
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security response headers to every response.

    Headers: CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, HSTS.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        # CSP: restrictive default, allow self for scripts/styles (frontend SPA)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )

        # HSTS (only when accessed via HTTPS in production)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response


# ---------------------------------------------------------------------------
# CSRF Protection (Double-Submit Cookie)
# ---------------------------------------------------------------------------


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF protection using the double-submit cookie pattern.

    On every response, sets a ``csrf_token`` cookie (readable by JS).
    On state-changing requests (POST/PUT/PATCH/DELETE), validates that
    the ``X-CSRF-Token`` header matches the cookie value.
    Auth callback and login paths are exempt.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip CSRF for explicitly exempt paths and safe (GET/HEAD/OPTIONS) methods
        if path in _CSRF_EXEMPT_PATHS:
            return await call_next(request)

        # Only enforce on state-changing methods
        if request.method in _CSRF_PROTECTED_METHODS:
            cookie_token = request.cookies.get("csrf_token")
            header_token = request.headers.get("X-CSRF-Token")

            if not cookie_token or not header_token:
                return JSONResponse(
                    status_code=403,
                    content={"error": "CSRF validation failed", "detail": "Missing CSRF token."},
                )

            if not hmac.compare_digest(cookie_token, header_token):
                return JSONResponse(
                    status_code=403,
                    content={"error": "CSRF validation failed", "detail": "CSRF token mismatch."},
                )

        response = await call_next(request)

        # Set CSRF cookie if not already present (httpOnly=False so JS can read it)
        if "csrf_token" not in request.cookies:
            settings = get_settings()
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                key="csrf_token",
                value=token,
                httponly=False,
                secure=not settings.debug,
                samesite="lax",
                path="/",
            )

        return response


# ---------------------------------------------------------------------------
# Correlation ID (Task 45)
# ---------------------------------------------------------------------------


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Inject a unique request_id into every request for end-to-end tracing.

    The ID is added to structlog context, the response header, and is
    available via ``request.state.request_id`` for propagation to ARQ jobs.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id

        # Bind to structlog context for all log lines in this request
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response


# ---------------------------------------------------------------------------
# Rate Limiting (Task 42)
# ---------------------------------------------------------------------------


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Enforce per-user API rate limits via Valkey counters.

    - Authenticated API requests: ``api_rate_limit`` per minute per user (default 100)
    - Auth endpoints: ``auth_rate_limit`` per minute per IP (default 10) -- handled in auth.py
    - Exempt: /health, /docs, /openapi.json
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Skip exempt paths and non-API paths
        if path in _RATE_LIMIT_EXEMPT_PATHS or not path.startswith("/api"):
            return await call_next(request)

        settings = get_settings()

        try:
            cache = get_cache_client()

            # Extract user_id from session for per-user limiting
            user_id = await _extract_user_id(request)

            if user_id is not None:
                # Authenticated: per-user rate limiting
                rate_key = f"api_rate:{user_id}"
                limit = settings.api_rate_limit
            else:
                # Unauthenticated: per-IP rate limiting to protect auth endpoints
                client_ip = _get_client_ip(request)
                rate_key = f"api_rate_ip:{client_ip}"
                limit = settings.auth_rate_limit

            # Atomic increment with TTL using Lua script to prevent race condition
            # If the key doesn't exist, it's created with value 1 and TTL 60s.
            # If it exists, it's incremented. TTL is never lost.
            lua_script = """
            local current = redis.call('INCR', KEYS[1])
            if current == 1 then
                redis.call('EXPIRE', KEYS[1], ARGV[1])
            end
            return current
            """
            current = await cache.eval(lua_script, 1, rate_key, 60)

            if current > limit:
                logger.warning(
                    "rate_limit_exceeded",
                    rate_key=rate_key,
                    current=current,
                    limit=limit,
                )
                return JSONResponse(
                    status_code=429,
                    content={"error": "Rate limit exceeded", "detail": "Too many requests. Try again later."},
                    headers={"Retry-After": "60"},
                )
        except Exception:
            # Fail-open: if Valkey is down, don't block requests
            logger.warning("rate_limit_check_failed", reason="valkey_error")

        return await call_next(request)


async def _extract_user_id(request: Request) -> str | None:
    """Extract user_id from session cookie without raising exceptions."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None

    try:
        session_client = get_session_client()
        session_data = await session_client.get(f"session:{session_id}")
        if session_data is None:
            return None
        session = json.loads(session_data)
        return session.get("user_id")
    except Exception:
        return None


def _get_client_ip(request: Request) -> str:
    """Extract the client IP address, respecting X-Forwarded-For behind a reverse proxy."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Take the first (leftmost) IP which is the original client
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# Request Size Limit (Task 43)
# ---------------------------------------------------------------------------


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with bodies exceeding the maximum size (1 MB).

    Checks Content-Length header first for efficiency. For requests
    without Content-Length (chunked/streaming), reads and limits the
    actual body size to prevent unbounded uploads.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")

        if content_length is not None:
            try:
                size = int(content_length)
                if size > _MAX_REQUEST_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "error": "Request body too large",
                            "detail": f"Maximum allowed size is {_MAX_REQUEST_BODY_BYTES} bytes (1 MB).",
                        },
                    )
            except ValueError:
                pass
        elif request.method in {"POST", "PUT", "PATCH"}:
            # No Content-Length header: enforce limit by reading the body
            body = await request.body()
            if len(body) > _MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": "Request body too large",
                        "detail": f"Maximum allowed size is {_MAX_REQUEST_BODY_BYTES} bytes (1 MB).",
                    },
                )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Request Logging (access log)
# ---------------------------------------------------------------------------


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log method, path, status code, and response time for every request.

    Relies on ``CorrelationIdMiddleware`` having already set the ``request_id``
    in structlog context vars, so log lines are correlated automatically.
    Health checks are logged at debug level to reduce noise.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = (time.monotonic() - start) * 1000

        path = request.url.path
        log_method = logger.debug if path in _LOG_QUIET_PATHS else logger.info

        log_method(
            "request_completed",
            method=request.method,
            path=path,
            status=response.status_code,
            duration_ms=round(elapsed_ms, 1),
        )

        return response
