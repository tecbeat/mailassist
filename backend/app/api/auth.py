"""OIDC authentication routes.

Implements Authorization Code Flow with PKCE via authlib.
Sessions stored in Valkey with TTL auto-expiry.
"""

import secrets
import json
import time
from datetime import UTC, datetime

import httpx
import structlog
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session
from app.core.redis import get_session_client
from app.core.security import get_encryption
from app.models import User

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

# OIDC discovery cache (re-fetched every 60 minutes)
_OIDC_CACHE_TTL_SECONDS = 3600
_oidc_config: dict | None = None
_oidc_config_fetched_at: float = 0.0


async def _get_oidc_config() -> dict:
    """Fetch and cache OIDC discovery document.

    The document is cached in memory and refreshed after
    ``_OIDC_CACHE_TTL_SECONDS`` so that provider-side changes
    (key rotation, endpoint migration) are picked up without a
    restart.
    """
    global _oidc_config, _oidc_config_fetched_at

    now = time.monotonic()
    if _oidc_config is not None and (now - _oidc_config_fetched_at) < _OIDC_CACHE_TTL_SECONDS:
        return _oidc_config

    settings = get_settings()
    if not settings.oidc_issuer_url:
        raise HTTPException(status_code=503, detail="OIDC not configured")
    issuer = settings.oidc_issuer_url.rstrip("/")
    discovery_url = f"{issuer}/.well-known/openid-configuration"

    async with httpx.AsyncClient() as client:
        resp = await client.get(discovery_url, timeout=10)
        resp.raise_for_status()
        _oidc_config = resp.json()
        _oidc_config_fetched_at = now

    return _oidc_config


def _create_oauth_client() -> AsyncOAuth2Client:
    """Create an authlib OAuth2 client configured for OIDC."""
    settings = get_settings()
    if not all([settings.oidc_client_id, settings.oidc_client_secret, settings.oidc_redirect_uri]):
        raise HTTPException(status_code=503, detail="OIDC not configured")
    return AsyncOAuth2Client(
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        redirect_uri=settings.oidc_redirect_uri,
        scope=settings.oidc_scopes,
        code_challenge_method="S256",
    )


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    """Initiate OIDC login by redirecting to the identity provider."""
    settings = get_settings()
    oidc_config = await _get_oidc_config()
    session_client = get_session_client()

    # Rate limiting: atomic INCR+EXPIRE via Lua script (prevents permanent
    # key without TTL if the process crashes between separate calls).
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"auth_rate:{client_ip}"
    lua_script = """
    local current = redis.call('INCR', KEYS[1])
    if current == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    return current
    """
    current_count = await session_client.eval(lua_script, 1, rate_key, 60)
    if current_count > settings.auth_rate_limit:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    # Generate PKCE code verifier and state
    client = _create_oauth_client()
    code_verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)

    authorization_url = oidc_config["authorization_endpoint"]
    url, _state = client.create_authorization_url(
        authorization_url,
        state=state,
        code_verifier=code_verifier,
    )

    # Store state and code_verifier in Valkey (expires in 10 minutes)
    await session_client.setex(
        f"oidc_state:{state}",
        600,
        json.dumps({"code_verifier": code_verifier}),
    )

    return RedirectResponse(url=url)


@router.get("/callback")
async def callback(request: Request, code: str, state: str) -> RedirectResponse:
    """Handle OIDC callback after user authenticates with the identity provider."""
    settings = get_settings()
    oidc_config = await _get_oidc_config()
    session_client = get_session_client()

    # Retrieve and validate state
    state_data = await session_client.get(f"oidc_state:{state}")
    if state_data is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state parameter")

    # Delete used state immediately to prevent replay
    await session_client.delete(f"oidc_state:{state}")

    state_obj = json.loads(state_data)
    code_verifier = state_obj["code_verifier"]

    # Exchange authorization code for tokens
    client = _create_oauth_client()
    token_endpoint = oidc_config["token_endpoint"]

    try:
        token = await client.fetch_token(
            token_endpoint,
            code=code,
            code_verifier=code_verifier,
        )
    except Exception as e:
        logger.error("oidc_token_exchange_failed", error=str(e))
        raise HTTPException(status_code=401, detail="Authentication failed")

    # Fetch user info
    userinfo_endpoint = oidc_config["userinfo_endpoint"]
    async with httpx.AsyncClient() as http_client:
        resp = await http_client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {token['access_token']}"},
            timeout=10,
        )
        resp.raise_for_status()
        userinfo = resp.json()

    # Upsert user in database
    async for db in get_session():
        sub = userinfo.get("sub")
        email = userinfo.get("email", "")
        display_name = userinfo.get("name", userinfo.get("preferred_username", email))

        stmt = select(User).where(User.oidc_subject == sub)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                oidc_subject=sub,
                email=email,
                display_name=display_name,
            )
            db.add(user)
            await db.flush()
            logger.info("user_created", user_id=str(user.id), email=email)
        else:
            user.email = email
            user.display_name = display_name
            user.updated_at = datetime.now(UTC)
            logger.info("user_updated", user_id=str(user.id), email=email)

        await db.flush()
        user_id = str(user.id)

    # Session fixation prevention: generate new session ID
    session_id = secrets.token_urlsafe(48)

    # Encrypt and store tokens in Valkey session
    encryption = get_encryption()
    encrypted_tokens = encryption.encrypt(json.dumps({
        "access_token": token.get("access_token"),
        "refresh_token": token.get("refresh_token"),
        "id_token": token.get("id_token"),
        "expires_at": token.get("expires_at"),
    }))

    session_data = json.dumps({
        "user_id": user_id,
        "email": email,
        "display_name": display_name,
        "encrypted_tokens": encrypted_tokens.decode(),
        "created_at": datetime.now(UTC).isoformat(),
    })

    await session_client.setex(
        f"session:{session_id}",
        settings.session_ttl_seconds,
        session_data,
    )

    # Set session cookie and redirect to frontend
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=not settings.debug,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
    )

    logger.info("user_logged_in", user_id=user_id, email=email)
    return response


@router.post("/logout")
async def logout(request: Request) -> JSONResponse:
    """Clear session and optionally trigger OIDC end_session."""
    session_client = get_session_client()
    session_id = request.cookies.get("session_id")

    if session_id:
        await session_client.delete(f"session:{session_id}")

    response = JSONResponse(content={"message": "Logged out"})
    response.delete_cookie("session_id")

    # Attempt OIDC end_session if supported
    try:
        oidc_config = await _get_oidc_config()
        end_session_url = oidc_config.get("end_session_endpoint")
        if end_session_url:
            logger.info("oidc_end_session_available", url=end_session_url)
    except Exception:
        pass

    logger.info("user_logged_out")
    return response


@router.get("/me")
async def get_current_user(request: Request) -> JSONResponse:
    """Return current authenticated user info."""
    session_client = get_session_client()
    session_id = request.cookies.get("session_id")

    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_data = await session_client.get(f"session:{session_id}")
    if session_data is None:
        raise HTTPException(status_code=401, detail="Session expired")

    session = json.loads(session_data)

    return JSONResponse(content={
        "user_id": session["user_id"],
        "email": session["email"],
        "display_name": session["display_name"],
    })


async def get_current_user_id(request: Request) -> str:
    """FastAPI dependency: extract and validate user_id from session.

    Use via Depends(get_current_user_id) on protected endpoints.
    Raises 401 if not authenticated or session expired.
    """
    session_client = get_session_client()
    session_id = request.cookies.get("session_id")

    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_data = await session_client.get(f"session:{session_id}")
    if session_data is None:
        raise HTTPException(status_code=401, detail="Session expired")

    session = json.loads(session_data)
    return session["user_id"]
