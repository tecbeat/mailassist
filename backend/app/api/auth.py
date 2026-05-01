"""OIDC authentication routes.

Implements Authorization Code Flow with PKCE using pure httpx.
Sessions stored in Valkey with TTL auto-expiry.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from uuid import UUID

import httpx
import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_ctx
from app.core.middleware import get_client_ip
from app.core.redis import get_session_client
from app.core.security import get_encryption
from app.models import User

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

# OIDC discovery cache (re-fetched every 60 minutes)
_OIDC_CACHE_TTL_SECONDS = 3600
_oidc_config: dict[str, Any] | None = None
_oidc_config_fetched_at: float = 0.0
_oidc_lock = asyncio.Lock()  # prevents thundering herd on cache expiry


def _create_pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and its S256 code_challenge."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


async def _get_oidc_config() -> dict[str, Any]:
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

    async with _oidc_lock:
        # Re-check inside the lock — another coroutine may have refreshed while we waited
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


def _build_authorization_url(
    authorization_endpoint: str,
    code_challenge: str,
    state: str,
) -> str:
    """Build the OIDC authorization URL with PKCE parameters."""
    settings = get_settings()
    if not all([settings.oidc_client_id, settings.oidc_redirect_uri]):
        raise HTTPException(status_code=503, detail="OIDC not configured")
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": settings.oidc_scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{authorization_endpoint}?{urlencode(params)}"


async def _exchange_code_for_token(
    token_endpoint: str,
    code: str,
    code_verifier: str,
) -> dict[str, Any]:
    """Exchange an authorization code for tokens using PKCE."""
    settings = get_settings()
    if not all([settings.oidc_client_id, settings.oidc_client_secret, settings.oidc_redirect_uri]):
        raise HTTPException(status_code=503, detail="OIDC not configured")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_uri,
        "client_id": settings.oidc_client_id,
        "client_secret": settings.oidc_client_secret,
        "code_verifier": code_verifier,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_endpoint, data=data, timeout=10)
        if resp.status_code != 200:
            logger.error("oidc_token_exchange_failed", status=resp.status_code, body=resp.text)
            raise HTTPException(status_code=401, detail="Authentication failed")
        return resp.json()  # type: ignore[no-any-return]


@router.get("/login")
async def login(request: Request) -> RedirectResponse:
    """Initiate OIDC login by redirecting to the identity provider."""
    settings = get_settings()
    oidc_config = await _get_oidc_config()
    session_client = get_session_client()

    # Rate limiting: atomic INCR+EXPIRE via Lua script (prevents permanent
    # key without TTL if the process crashes between separate calls).
    client_ip = get_client_ip(request)
    rate_key = f"auth_rate:{client_ip}"
    lua_script = """
    local current = redis.call('INCR', KEYS[1])
    if current == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    return current
    """
    current_count = await session_client.eval(lua_script, 1, rate_key, str(60))  # type: ignore[misc]
    if current_count > settings.auth_rate_limit:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")

    # Generate PKCE code verifier and state
    code_verifier, code_challenge = _create_pkce_pair()
    state = secrets.token_urlsafe(32)

    authorization_url = oidc_config["authorization_endpoint"]
    url = _build_authorization_url(authorization_url, code_challenge, state)

    # Store state and code_verifier in Valkey (expires in 10 minutes)
    await session_client.setex(
        f"oidc_state:{state}",
        600,
        json.dumps({"code_verifier": code_verifier}),
    )

    return RedirectResponse(url=url)


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    """Handle OIDC callback after user authenticates with the identity provider."""
    if error:
        logger.warning(
            "oidc_callback_error",
            error=error,
            error_description=error_description,
        )
        from urllib.parse import quote

        error_msg = error_description or error
        return RedirectResponse(
            url=f"/login?error={quote(error_msg)}",
            status_code=302,
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

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
    token_endpoint = oidc_config["token_endpoint"]

    try:
        token = await _exchange_code_for_token(
            token_endpoint,
            code=code,
            code_verifier=code_verifier,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("oidc_token_exchange_failed", error=str(e))
        raise HTTPException(status_code=401, detail="Authentication failed") from None

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

    # Upsert user in database and create session only after successful commit
    async with get_session_ctx() as db:
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

        # Explicitly commit before creating the Valkey session so that a
        # commit failure prevents ghost sessions pointing to unpersisted users.
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            logger.error("auth_db_commit_failed", user_id=user_id, email=email)
            raise HTTPException(
                status_code=500,
                detail="Authentication failed due to a server error",
            ) from None

        # Session fixation prevention: generate new session ID
        session_id = secrets.token_urlsafe(48)

        # Encrypt and store tokens in Valkey session
        encryption = get_encryption()
        encrypted_tokens = encryption.encrypt(
            json.dumps(
                {
                    "access_token": token.get("access_token"),
                    "refresh_token": token.get("refresh_token"),
                    "id_token": token.get("id_token"),
                    "expires_at": token.get("expires_at"),
                }
            )
        )

        session_data = json.dumps(
            {
                "user_id": user_id,
                "email": email,
                "display_name": display_name,
                "encrypted_tokens": encrypted_tokens.decode(),
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

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
    """Clear session and trigger OIDC end_session if supported.

    Returns ``end_session_url`` in the JSON body so the frontend can
    redirect the user to the IdP logout page.
    """
    session_client = get_session_client()
    session_id = request.cookies.get("session_id")

    id_token: str | None = None

    if session_id:
        # Retrieve session before deleting so we can extract the id_token
        session_raw = await session_client.get(f"session:{session_id}")
        if session_raw:
            try:
                session_obj = json.loads(session_raw)
                encryption = get_encryption()
                decrypted = encryption.decrypt(session_obj["encrypted_tokens"].encode())
                tokens = json.loads(decrypted)
                id_token = tokens.get("id_token")
            except Exception:
                logger.warning("logout_token_decrypt_failed")
        await session_client.delete(f"session:{session_id}")

    # Build OIDC end_session URL if supported
    end_session_url: str | None = None
    try:
        oidc_config = await _get_oidc_config()
        base_url = oidc_config.get("end_session_endpoint")
        if base_url:
            from urllib.parse import urlencode

            params: dict[str, str] = {"post_logout_redirect_uri": "/"}
            if id_token:
                params["id_token_hint"] = id_token
            end_session_url = f"{base_url}?{urlencode(params)}"
    except Exception:
        logger.warning("logout_oidc_discovery_failed")

    body: dict[str, str | None] = {"message": "Logged out"}
    if end_session_url:
        body["end_session_url"] = end_session_url

    response = JSONResponse(content=body)
    response.delete_cookie("session_id")

    logger.info("user_logged_out", has_end_session=end_session_url is not None)
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

    return JSONResponse(
        content={
            "user_id": session["user_id"],
            "email": session["email"],
            "display_name": session["display_name"],
        }
    )


async def get_current_user_id(request: Request) -> UUID:
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
    return UUID(session["user_id"])  # type: ignore[no-any-return]
