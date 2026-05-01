"""CalDAV calendar service.

Handles CalDAV connection testing, calendar listing, and event creation.
Uses the caldav library for CalDAV protocol operations.

The caldav library uses ``requests`` internally, which blocks the event
loop.  All network-bound caldav calls are therefore dispatched to a
thread via ``asyncio.to_thread()``.
"""

import asyncio
import contextlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import caldav
import structlog
from icalendar import Calendar, Event, vText

from app.core.config import get_settings
from app.core.exceptions import ExternalServiceError
from app.core.security import decrypt_credentials, get_encryption
from app.core.types import ConnectionTestResult

logger = structlog.get_logger()


@dataclass(frozen=True)
class CalendarEventResult:
    """Result of a successful calendar event creation."""

    calendar_name: str
    title: str
    uid: str | None = None


async def test_caldav_connection(
    caldav_url: str,
    username: str,
    password: str,
    default_calendar: str = "",
) -> ConnectionTestResult:
    """Test CalDAV connectivity with auto-discovery.

    Uses RFC 6764 auto-discovery to find calendars from the server URL.
    If ``default_calendar`` is provided, validates that it exists.
    Returns discovered calendars and the resolved ``caldav_url``
    so the frontend can auto-fill the configuration.
    """
    from app.services.dav_discovery import discover_dav

    discovery = await discover_dav(caldav_url, username, password)

    if not discovery.success:
        return ConnectionTestResult(
            success=False,
            message=discovery.message,
            details={"calendars": []},
        )

    cal_names = [c.display_name for c in discovery.calendars]
    cal_slugs = [c.slug for c in discovery.calendars]

    # If default_calendar provided, validate it exists
    if default_calendar:
        match = default_calendar.strip("/")
        if match not in cal_slugs and match not in cal_names:
            hint = f" Available: {', '.join(cal_names)}" if cal_names else ""
            return ConnectionTestResult(
                success=False,
                message=f"Calendar '{default_calendar}' not found.{hint}",
                details={
                    "calendars": cal_names,
                    "calendar_slugs": cal_slugs,
                    "caldav_url": discovery.calendar_home,
                },
            )
        return ConnectionTestResult(
            success=True,
            message=f"Connected. Calendar '{default_calendar}' is valid.",
            details={
                "calendars": cal_names,
                "calendar_slugs": cal_slugs,
                "caldav_url": discovery.calendar_home,
            },
        )

    # No default_calendar — return discovery results
    return ConnectionTestResult(
        success=True,
        message=f"Connected successfully. Found {len(cal_names)} calendar(s).",
        details={
            "calendars": cal_names,
            "calendar_slugs": cal_slugs,
            "caldav_url": discovery.calendar_home,
            "address_books": [ab.slug for ab in discovery.address_books],
            "address_book_names": [ab.display_name for ab in discovery.address_books],
            "carddav_url": discovery.addressbook_home,
        },
    )


def get_caldav_credentials(encrypted_credentials: bytes) -> tuple[str, str]:
    """Decrypt CalDAV credentials from encrypted storage.

    Returns (username, password) tuple.
    """
    creds = decrypt_credentials(encrypted_credentials)
    return creds["username"], creds["password"]


def encrypt_caldav_credentials(username: str, password: str) -> bytes:
    """Encrypt CalDAV credentials for storage."""
    encryption = get_encryption()
    creds = json.dumps({"username": username, "password": password})
    return encryption.encrypt(creds)


async def create_calendar_event(
    caldav_url: str,
    username: str,
    password: str,
    calendar_name: str,
    title: str,
    start: datetime,
    end: datetime | None = None,
    location: str | None = None,
    description: str | None = None,
    is_all_day: bool = False,
) -> CalendarEventResult:
    """Create a calendar event via CalDAV.

    Builds an iCalendar VEVENT and pushes it to the specified calendar.
    If end is None, defaults to start + 1 hour (or all-day event).

    Raises:
        ExternalServiceError: If the CalDAV server cannot be reached,
            no calendars are found, or the event creation fails.
    """
    if end is None:
        end = start + timedelta(days=1) if is_all_day else start + timedelta(hours=1)

    # Build iCalendar event
    cal = Calendar()  # type: ignore[no-untyped-call]
    cal.add("prodid", get_settings().ical_product_id)
    cal.add("version", "2.0")

    event = Event()  # type: ignore[no-untyped-call]
    event.add("summary", title)

    if is_all_day:
        event.add("dtstart", start.date())
        event.add("dtend", end.date())
    else:
        event.add("dtstart", start)
        event.add("dtend", end)

    if location:
        event["location"] = vText(location)
    if description:
        event["description"] = vText(description)

    event.add("dtstamp", datetime.now())
    cal.add_component(event)

    ical_string = cal.to_ical().decode("utf-8")

    # --- Auto-discover the real DAV URL if the caller passed a bare server URL ---
    from app.services.dav_discovery import discover_dav

    discovery = await discover_dav(caldav_url, username, password)
    if discovery.success and discovery.dav_url:
        resolved_url = discovery.dav_url
        logger.debug(
            "caldav_url_resolved",
            original=caldav_url,
            resolved=resolved_url,
        )
    else:
        # Fall back to the provided URL and let the caldav library try
        resolved_url = caldav_url

    try:

        def _create_event() -> tuple[str, bool, str | None]:
            """Run blocking CalDAV operations in a worker thread.

            Returns (calendar_name, used_fallback, uid) so logging stays
            on the main thread where structlog context vars are available.
            """
            client = caldav.DAVClient(  # type: ignore[operator]
                url=resolved_url,
                username=username,
                password=password,
            )
            principal = client.principal()
            calendars = principal.calendars()

            target_cal = None
            for cal_obj in calendars:
                # Match by display name or by slug (last path segment of URL)
                cal_slug = str(cal_obj.url).rstrip("/").rsplit("/", 1)[-1]
                if cal_obj.name == calendar_name or cal_slug == calendar_name:
                    target_cal = cal_obj
                    break

            used_fallback = False
            if target_cal is None:
                if calendars:
                    target_cal = calendars[0]
                    used_fallback = True
                else:
                    raise ExternalServiceError("CalDAV", "No calendars found on server")

            created = target_cal.save_event(ical_string)
            # Extract the UID from the created event
            uid = None
            with contextlib.suppress(Exception):
                uid = str(created.vobject_instance.vevent.uid.value)
            return target_cal.name, used_fallback, uid

        used_calendar, used_fallback, event_uid = await asyncio.to_thread(_create_event)

        if used_fallback:
            logger.warning(
                "caldav_calendar_not_found",
                requested=calendar_name,
                fallback=used_calendar,
            )

        logger.info(
            "caldav_event_created",
            title=title,
            calendar=used_calendar,
            start=str(start),
            uid=event_uid,
        )
        return CalendarEventResult(calendar_name=used_calendar, title=title, uid=event_uid)

    except ExternalServiceError:
        raise
    except Exception as e:
        logger.exception("caldav_event_creation_failed", title=title)
        raise ExternalServiceError("CalDAV", f"Failed to create event: {e}") from e


async def delete_caldav_event(
    caldav_url: str,
    username: str,
    password: str,
    calendar_name: str,
    uid: str,
) -> None:
    """Delete a calendar event from CalDAV by its UID.

    Raises:
        ExternalServiceError: If the event cannot be deleted.
    """
    from app.services.dav_discovery import discover_dav

    discovery = await discover_dav(caldav_url, username, password)
    resolved_url = discovery.dav_url if discovery.success and discovery.dav_url else caldav_url

    try:

        def _delete() -> None:
            client = caldav.DAVClient(  # type: ignore[operator]
                url=resolved_url,
                username=username,
                password=password,
            )
            principal = client.principal()
            calendars = principal.calendars()

            target_cal = None
            for cal_obj in calendars:
                cal_slug = str(cal_obj.url).rstrip("/").rsplit("/", 1)[-1]
                if cal_obj.name == calendar_name or cal_slug == calendar_name:
                    target_cal = cal_obj
                    break
            if target_cal is None and calendars:
                target_cal = calendars[0]
            if target_cal is None:
                raise ExternalServiceError("CalDAV", "No calendars found on server")

            event = target_cal.event_by_uid(uid)
            event.delete()

        await asyncio.to_thread(_delete)
        logger.info("caldav_event_deleted", uid=uid)

    except ExternalServiceError:
        raise
    except Exception as e:
        logger.exception("caldav_event_delete_failed", uid=uid)
        raise ExternalServiceError("CalDAV", f"Failed to delete event: {e}") from e
