"""Tests for app.services.calendar — CalDAV operations."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ExternalServiceError
from app.services.calendar import (
    CalendarEventResult,
    create_calendar_event,
    delete_caldav_event,
    encrypt_caldav_credentials,
    get_caldav_credentials,
    test_caldav_connection,
)

# ---------------------------------------------------------------------------
# test_caldav_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
async def test_test_caldav_connection_success_no_default_returns_calendars(
    mock_discover: AsyncMock,
) -> None:
    cal = MagicMock(display_name="Personal", slug="personal")
    ab = MagicMock(slug="contacts", display_name="Contacts")
    mock_discover.return_value = MagicMock(
        success=True,
        calendars=[cal],
        address_books=[ab],
        calendar_home="https://dav.example.com/cal/",
        addressbook_home="https://dav.example.com/card/",
        dav_url="https://dav.example.com/",
    )

    result = await test_caldav_connection("https://dav.example.com", "user", "pass")

    assert result.success is True
    assert "1 calendar" in result.message
    assert result.details["calendars"] == ["Personal"]


@pytest.mark.asyncio
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
async def test_test_caldav_connection_discovery_failure_returns_error(
    mock_discover: AsyncMock,
) -> None:
    mock_discover.return_value = MagicMock(
        success=False,
        message="Connection refused",
        calendars=[],
    )

    result = await test_caldav_connection("https://bad.example.com", "u", "p")

    assert result.success is False
    assert "Connection refused" in result.message


@pytest.mark.asyncio
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
async def test_test_caldav_connection_calendar_not_found_returns_error(
    mock_discover: AsyncMock,
) -> None:
    cal = MagicMock(display_name="Work", slug="work")
    mock_discover.return_value = MagicMock(
        success=True,
        calendars=[cal],
        calendar_home="https://dav.example.com/cal/",
    )

    result = await test_caldav_connection("https://dav.example.com", "u", "p", default_calendar="missing")

    assert result.success is False
    assert "'missing' not found" in result.message


@pytest.mark.asyncio
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
async def test_test_caldav_connection_default_calendar_valid_returns_success(
    mock_discover: AsyncMock,
) -> None:
    cal = MagicMock(display_name="Work", slug="work")
    mock_discover.return_value = MagicMock(
        success=True,
        calendars=[cal],
        calendar_home="https://dav.example.com/cal/",
    )

    result = await test_caldav_connection("https://dav.example.com", "u", "p", default_calendar="work")

    assert result.success is True
    assert "'work' is valid" in result.message


# ---------------------------------------------------------------------------
# get_caldav_credentials / encrypt_caldav_credentials
# ---------------------------------------------------------------------------


@patch("app.services.calendar.decrypt_credentials")
def test_get_caldav_credentials_decrypts_returns_tuple(mock_decrypt: MagicMock) -> None:
    mock_decrypt.return_value = {"username": "alice", "password": "s3cret"}

    user, pw = get_caldav_credentials(b"encrypted")

    assert user == "alice"
    assert pw == "s3cret"
    mock_decrypt.assert_called_once_with(b"encrypted")


@patch("app.services.calendar.get_encryption")
def test_encrypt_caldav_credentials_encrypts_json(mock_enc: MagicMock) -> None:
    mock_fernet = MagicMock()
    mock_fernet.encrypt.return_value = b"cipher"
    mock_enc.return_value = mock_fernet

    result = encrypt_caldav_credentials("alice", "pw")

    assert result == b"cipher"
    mock_fernet.encrypt.assert_called_once()
    # Verify the JSON payload contains the credentials
    call_arg = mock_fernet.encrypt.call_args[0][0]
    import json

    payload = json.loads(call_arg)
    assert payload == {"username": "alice", "password": "pw"}


# ---------------------------------------------------------------------------
# create_calendar_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.services.calendar.asyncio.to_thread", new_callable=AsyncMock)
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
@patch("app.services.calendar.get_settings")
async def test_create_calendar_event_success_returns_result(
    mock_settings: MagicMock,
    mock_discover: AsyncMock,
    mock_to_thread: AsyncMock,
) -> None:
    mock_settings.return_value.ical_product_id = "-//Test//Test//EN"
    mock_discover.return_value = MagicMock(success=True, dav_url="https://dav.example.com/")

    mock_to_thread.return_value = ("Personal", False, "uid-123")

    start = datetime(2025, 6, 1, 10, 0)
    result = await create_calendar_event("https://dav.example.com", "u", "p", "Personal", "Meeting", start)

    assert isinstance(result, CalendarEventResult)
    assert result.calendar_name == "Personal"
    assert result.uid == "uid-123"


@pytest.mark.asyncio
@patch("app.services.calendar.asyncio.to_thread", new_callable=AsyncMock)
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
@patch("app.services.calendar.get_settings")
async def test_create_calendar_event_all_day_uses_date(
    mock_settings: MagicMock,
    mock_discover: AsyncMock,
    mock_to_thread: AsyncMock,
) -> None:
    mock_settings.return_value.ical_product_id = "-//Test//EN"
    mock_discover.return_value = MagicMock(success=True, dav_url="https://d.example.com/")
    mock_to_thread.return_value = ("Cal", False, "uid-day")

    start = datetime(2025, 6, 1)
    result = await create_calendar_event("https://d.example.com", "u", "p", "Cal", "Holiday", start, is_all_day=True)

    assert result.title == "Holiday"


@pytest.mark.asyncio
@patch("app.services.calendar.asyncio.to_thread", new_callable=AsyncMock)
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
@patch("app.services.calendar.get_settings")
async def test_create_calendar_event_exception_raises_external_service_error(
    mock_settings: MagicMock,
    mock_discover: AsyncMock,
    mock_to_thread: AsyncMock,
) -> None:
    mock_settings.return_value.ical_product_id = "-//Test//EN"
    mock_discover.return_value = MagicMock(success=True, dav_url="https://d.example.com/")
    mock_to_thread.side_effect = ConnectionError("timeout")

    with pytest.raises(ExternalServiceError):
        await create_calendar_event("https://d.example.com", "u", "p", "Cal", "Oops", datetime(2025, 1, 1))


@pytest.mark.asyncio
@patch("app.services.calendar.asyncio.to_thread", new_callable=AsyncMock)
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
@patch("app.services.calendar.get_settings")
async def test_create_calendar_event_discovery_fails_uses_original_url(
    mock_settings: MagicMock,
    mock_discover: AsyncMock,
    mock_to_thread: AsyncMock,
) -> None:
    mock_settings.return_value.ical_product_id = "-//Test//EN"
    mock_discover.return_value = MagicMock(success=False, dav_url=None)
    mock_to_thread.return_value = ("Fallback", False, None)

    result = await create_calendar_event("https://orig.example.com", "u", "p", "Fallback", "Test", datetime(2025, 1, 1))

    assert result.calendar_name == "Fallback"


# ---------------------------------------------------------------------------
# delete_caldav_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.services.calendar.asyncio.to_thread", new_callable=AsyncMock)
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
async def test_delete_caldav_event_success(
    mock_discover: AsyncMock,
    mock_to_thread: AsyncMock,
) -> None:
    mock_discover.return_value = MagicMock(success=True, dav_url="https://d.example.com/")
    mock_to_thread.return_value = None

    # Should not raise
    await delete_caldav_event("https://d.example.com", "u", "p", "Cal", "uid-1")
    mock_to_thread.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.calendar.asyncio.to_thread", new_callable=AsyncMock)
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
async def test_delete_caldav_event_exception_raises_external_service_error(
    mock_discover: AsyncMock,
    mock_to_thread: AsyncMock,
) -> None:
    mock_discover.return_value = MagicMock(success=True, dav_url="https://d.example.com/")
    mock_to_thread.side_effect = Exception("not found")

    with pytest.raises(ExternalServiceError):
        await delete_caldav_event("https://d.example.com", "u", "p", "Cal", "uid-x")


@pytest.mark.asyncio
@patch("app.services.calendar.asyncio.to_thread", new_callable=AsyncMock)
@patch("app.services.calendar.discover_dav", new_callable=AsyncMock)
async def test_delete_caldav_event_external_error_reraised(
    mock_discover: AsyncMock,
    mock_to_thread: AsyncMock,
) -> None:
    mock_discover.return_value = MagicMock(success=True, dav_url="https://d.example.com/")
    mock_to_thread.side_effect = ExternalServiceError("CalDAV", "No calendars found")

    with pytest.raises(ExternalServiceError, match="No calendars found"):
        await delete_caldav_event("https://d.example.com", "u", "p", "Cal", "uid-x")
