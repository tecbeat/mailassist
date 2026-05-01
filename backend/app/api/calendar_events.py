"""Calendar event API endpoints.

Provides listing, update, and delete views for calendar events
extracted by the AI calendar plugin.
"""

from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.sql.elements import UnaryExpression

from app.api.deps import CurrentUserId, DbSession, get_or_404, paginate, sanitize_like
from app.models import CalendarEvent
from app.schemas.calendar_event import (
    CalendarEventListResponse,
    CalendarEventResponse,
    CalendarEventUpdate,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/calendar-events", tags=["calendar-events"])


@router.get("")
async def list_calendar_events(
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    search: str | None = None,
    sort: Literal["newest", "oldest", "title"] = Query(default="newest", description="Sort order"),
) -> CalendarEventListResponse:
    """List calendar events with pagination and optional search filter."""
    uid = UUID(user_id)

    base_stmt = select(CalendarEvent).where(CalendarEvent.user_id == uid)

    if search:
        base_stmt = base_stmt.where(CalendarEvent.title.ilike(f"%{sanitize_like(search)}%"))

    order_col: UnaryExpression[Any]
    if sort == "oldest":
        order_col = CalendarEvent.created_at.asc()
    elif sort == "title":
        order_col = CalendarEvent.title.asc()
    else:
        order_col = CalendarEvent.created_at.desc()

    base_stmt = base_stmt.order_by(order_col)
    result = await paginate(db, base_stmt, page, per_page)

    return CalendarEventListResponse(
        items=[CalendarEventResponse.model_validate(r) for r in result.items],
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
    )


@router.get("/{event_id}")
async def get_calendar_event(
    event_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> CalendarEventResponse:
    """Get a single calendar event."""
    event = await get_or_404(db, CalendarEvent, event_id, user_id, "Calendar event not found")
    return CalendarEventResponse.model_validate(event)


@router.patch("/{event_id}")
async def update_calendar_event(
    event_id: UUID,
    data: CalendarEventUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> CalendarEventResponse:
    """Update a calendar event."""
    event = await get_or_404(db, CalendarEvent, event_id, user_id, "Calendar event not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(event, field, value)

    await db.flush()
    logger.info("calendar_event_updated", event_id=str(event_id))

    # Re-sync to CalDAV with updated data
    from app.services.persistence import _sync_event_to_caldav

    await _sync_event_to_caldav(event)

    await db.refresh(event)
    return CalendarEventResponse.model_validate(event)


@router.post("/{event_id}/sync")
async def sync_calendar_event(
    event_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> CalendarEventResponse:
    """Push an existing calendar event to CalDAV."""
    event = await get_or_404(db, CalendarEvent, event_id, user_id, "Calendar event not found")

    from app.services.persistence import _sync_event_to_caldav

    await _sync_event_to_caldav(event)

    await db.refresh(event)
    logger.info("calendar_event_synced", event_id=str(event_id))
    return CalendarEventResponse.model_validate(event)


@router.delete("/{event_id}", status_code=204)
async def delete_calendar_event(
    event_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a calendar event record and remove it from CalDAV if synced."""
    from app.models.contacts import CalDAVConfig
    from app.services.calendar import delete_caldav_event, get_caldav_credentials

    event = await get_or_404(db, CalendarEvent, event_id, user_id, "Calendar event not found")

    # If the event was synced to CalDAV, try to delete it there too
    if event.caldav_synced and event.caldav_uid:
        uid = UUID(user_id)
        config_stmt = select(CalDAVConfig).where(
            CalDAVConfig.user_id == uid,
            CalDAVConfig.is_active.is_(True),
        )
        config = (await db.execute(config_stmt)).scalar_one_or_none()
        if config:
            try:
                username, password = get_caldav_credentials(config.encrypted_credentials)
                await delete_caldav_event(
                    caldav_url=config.caldav_url,
                    username=username,
                    password=password,
                    calendar_name=config.default_calendar or "",
                    uid=event.caldav_uid,
                )
            except Exception as exc:
                logger.warning(
                    "caldav_delete_failed",
                    event_id=str(event_id),
                    error=str(exc),
                )

    await db.delete(event)
    await db.flush()
    logger.info("calendar_event_deleted", event_id=str(event_id))
