"""CalDAV calendar configuration API endpoints.

Provides configuration management for CalDAV calendar integration.
Credentials are write-only -- GET endpoints never return passwords.
"""

from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUserId, DbSession
from app.models import CalDAVConfig
from app.schemas.calendar import (
    CalDAVConfigResponse,
    CalDAVConfigUpdate,
    CalDAVTestRequest,
    CalDAVTestResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/config")
async def get_config(
    db: DbSession,
    user_id: CurrentUserId,
) -> CalDAVConfigResponse | None:
    """Get CalDAV configuration (credentials excluded).

    Returns ``None`` (HTTP 200 with ``null`` body) when no config exists.
    This is intentional: ``null`` tells the frontend "not configured yet"
    and renders the setup form, whereas a 404 would trigger an error state.
    """
    config = await _get_config(db, UUID(user_id))
    if config is None:
        return None
    return CalDAVConfigResponse.model_validate(config)


@router.put("/config")
async def update_config(
    data: CalDAVConfigUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> CalDAVConfigResponse:
    """Create or update CalDAV configuration.

    Credentials are encrypted before storage.
    """
    uid = UUID(user_id)

    from app.services.calendar import encrypt_caldav_credentials

    # Only re-encrypt credentials if both username and password are provided.
    # When editing, empty credentials mean "keep existing".
    has_new_credentials = bool(data.username and data.password)

    config = await _get_config(db, uid)

    if config is None:
        # Creating new config: credentials are required
        if not has_new_credentials:
            raise HTTPException(status_code=422, detail="Username and password are required for initial setup")
        try:
            encrypted = encrypt_caldav_credentials(data.username, data.password)
        except Exception as e:
            logger.error("caldav_credential_encryption_failed", error=str(e))
            raise HTTPException(status_code=500, detail="Failed to encrypt CalDAV credentials") from e
        config = CalDAVConfig(
            user_id=uid,
            caldav_url=data.caldav_url,
            encrypted_credentials=encrypted,
            default_calendar=data.default_calendar,
        )
        db.add(config)
    else:
        config.caldav_url = data.caldav_url
        config.default_calendar = data.default_calendar
        if has_new_credentials:
            try:
                encrypted = encrypt_caldav_credentials(data.username, data.password)
            except Exception as e:
                logger.error("caldav_credential_encryption_failed", error=str(e))
                raise HTTPException(status_code=500, detail="Failed to encrypt CalDAV credentials") from e
            config.encrypted_credentials = encrypted
        # else: preserve existing encrypted_credentials

    await db.flush()
    logger.info("caldav_config_updated", user_id=user_id)
    return CalDAVConfigResponse.model_validate(config)


@router.post("/config/test")
async def test_config(
    db: DbSession,
    user_id: CurrentUserId,
    data: CalDAVTestRequest | None = None,
) -> CalDAVTestResponse:
    """Test CalDAV connectivity.

    Accepts credentials directly for pre-save testing.  Falls back to
    stored configuration when no credentials are provided in the body.
    """
    from app.services.calendar import get_caldav_credentials, test_caldav_connection

    # Determine credentials: from request body or stored config
    if data and data.caldav_url and data.username and data.password:
        caldav_url = data.caldav_url
        username = data.username
        password = data.password
        default_calendar = data.default_calendar
    else:
        config = await _get_config(db, UUID(user_id))
        if config is None:
            raise HTTPException(
                status_code=404, detail="CalDAV not configured. Provide credentials in the request body."
            )
        caldav_url = config.caldav_url
        username, password = get_caldav_credentials(config.encrypted_credentials)
        default_calendar = (data.default_calendar if data else "") or config.default_calendar

    try:
        result = await test_caldav_connection(
            caldav_url=caldav_url,
            username=username,
            password=password,
            default_calendar=default_calendar,
        )
    except Exception as e:
        logger.error("caldav_test_failed", error=str(e))
        raise HTTPException(status_code=502, detail="CalDAV connection test failed") from None
    return CalDAVTestResponse(
        success=result.success,
        message=result.message,
        calendars=(result.details or {}).get("calendars", []),
        details=result.details,
    )


async def _get_config(db: AsyncSession, user_id: UUID) -> CalDAVConfig | None:
    """Fetch CalDAV config for a user."""
    stmt = select(CalDAVConfig).where(CalDAVConfig.user_id == user_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
