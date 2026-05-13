"""Tests for app.services.contacts.sync — connection testing + sync flow.

Covers: test_carddav_connection (discovery success/failure, address book
validation), sync_contacts (full sync, incremental sync, deleted contacts,
parse errors, HTTP errors, discovery failure), and _rebuild_email_cache.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

MODULE = "app.services.contacts.sync"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(*, sync_token: str | None = None) -> MagicMock:
    cfg = MagicMock()
    cfg.user_id = uuid4()
    cfg.carddav_url = "https://dav.example.com"
    cfg.address_book = "contacts"
    cfg.encrypted_credentials = b"enc"
    cfg.sync_token = sync_token
    cfg.last_sync_at = None
    return cfg


def _make_discovery(*, success: bool = True, message: str = "OK") -> MagicMock:
    d = MagicMock()
    d.success = success
    d.message = message
    d.addressbook_home = "https://dav.example.com/dav/addressbooks/user/"
    ab = MagicMock()
    ab.display_name = "Contacts"
    ab.slug = "contacts"
    d.address_books = [ab]
    cal = MagicMock()
    cal.slug = "personal"
    cal.display_name = "Personal"
    d.calendars = [cal]
    d.calendar_home = "https://dav.example.com/dav/calendars/user/"
    return d


MULTISTATUS_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<d:multistatus xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <d:sync-token>token-2</d:sync-token>
  {responses}
</d:multistatus>"""

RESPONSE_OK = """\
<d:response>
  <d:href>/dav/addressbooks/user/contacts/abc123.vcf</d:href>
  <d:propstat>
    <d:status>HTTP/1.1 200 OK</d:status>
    <d:prop>
      <d:getetag>"etag1"</d:getetag>
      <card:address-data>BEGIN:VCARD
VERSION:3.0
FN:John Doe
EMAIL:john@example.com
END:VCARD</card:address-data>
    </d:prop>
  </d:propstat>
</d:response>"""

RESPONSE_DELETED = """\
<d:response>
  <d:href>/dav/addressbooks/user/contacts/del456.vcf</d:href>
  <d:status>HTTP/1.1 404 Not Found</d:status>
</d:response>"""

RESPONSE_EMPTY_VCARD = """\
<d:response>
  <d:href>/dav/addressbooks/user/contacts/empty.vcf</d:href>
  <d:propstat>
    <d:status>HTTP/1.1 200 OK</d:status>
    <d:prop>
      <d:getetag>"etag2"</d:getetag>
      <card:address-data></card:address-data>
    </d:prop>
  </d:propstat>
</d:response>"""


# ---------------------------------------------------------------------------
# test_carddav_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
async def test_carddav_connection_discovery_fails_returns_failure(mock_disc: AsyncMock) -> None:
    from app.services.contacts.sync import test_carddav_connection

    mock_disc.return_value = _make_discovery(success=False, message="unreachable")
    result = await test_carddav_connection("https://x", "u", "p")
    assert result.success is False
    assert "unreachable" in result.message


@pytest.mark.asyncio
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
async def test_carddav_connection_no_addressbook_returns_all(mock_disc: AsyncMock) -> None:
    from app.services.contacts.sync import test_carddav_connection

    mock_disc.return_value = _make_discovery()
    result = await test_carddav_connection("https://x", "u", "p")
    assert result.success is True
    assert "contacts" in result.details["address_books"]
    assert "personal" in result.details["calendars"]


@pytest.mark.asyncio
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
async def test_carddav_connection_addressbook_valid_returns_success(mock_disc: AsyncMock) -> None:
    from app.services.contacts.sync import test_carddav_connection

    mock_disc.return_value = _make_discovery()
    result = await test_carddav_connection("https://x", "u", "p", address_book="contacts")
    assert result.success is True
    assert "valid" in result.message.lower()


@pytest.mark.asyncio
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
async def test_carddav_connection_addressbook_invalid_returns_failure(mock_disc: AsyncMock) -> None:
    from app.services.contacts.sync import test_carddav_connection

    mock_disc.return_value = _make_discovery()
    result = await test_carddav_connection("https://x", "u", "p", address_book="nonexistent")
    assert result.success is False
    assert "not found" in result.message.lower()


@pytest.mark.asyncio
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
async def test_carddav_connection_addressbook_match_by_display_name(mock_disc: AsyncMock) -> None:
    from app.services.contacts.sync import test_carddav_connection

    mock_disc.return_value = _make_discovery()
    result = await test_carddav_connection("https://x", "u", "p", address_book="Contacts")
    assert result.success is True


# ---------------------------------------------------------------------------
# sync_contacts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(f"{MODULE}._rebuild_email_cache", new_callable=AsyncMock)
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
@patch(f"{MODULE}.decrypt_credentials")
async def test_sync_contacts_full_sync_adds_new_contact(
    mock_creds: MagicMock,
    mock_disc: AsyncMock,
    mock_rebuild: AsyncMock,
) -> None:
    from app.services.contacts.sync import sync_contacts

    mock_creds.return_value = {"username": "u", "password": "p"}
    mock_disc.return_value = _make_discovery()

    config = _make_config()
    db = AsyncMock()
    # select existing contact -> None
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    db.execute.return_value = scalar_result

    xml = MULTISTATUS_TEMPLATE.format(responses=RESPONSE_OK)
    response = MagicMock()
    response.status_code = 207
    response.text = xml

    with patch("httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.request.return_value = response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        stats = await sync_contacts(db, config)

    assert stats["added"] == 1
    assert stats["deleted"] == 0
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    mock_rebuild.assert_awaited_once()


@pytest.mark.asyncio
@patch(f"{MODULE}._rebuild_email_cache", new_callable=AsyncMock)
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
@patch(f"{MODULE}.decrypt_credentials")
async def test_sync_contacts_incremental_deletes_contact(
    mock_creds: MagicMock,
    mock_disc: AsyncMock,
    mock_rebuild: AsyncMock,
) -> None:
    from app.services.contacts.sync import sync_contacts

    mock_creds.return_value = {"username": "u", "password": "p"}
    mock_disc.return_value = _make_discovery()

    config = _make_config(sync_token="token-1")
    db = AsyncMock()

    xml = MULTISTATUS_TEMPLATE.format(responses=RESPONSE_DELETED)
    response = MagicMock()
    response.status_code = 207
    response.text = xml

    with patch("httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.request.return_value = response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        stats = await sync_contacts(db, config)

    assert stats["deleted"] == 1
    assert config.sync_token == "token-2"


@pytest.mark.asyncio
@patch(f"{MODULE}._rebuild_email_cache", new_callable=AsyncMock)
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
@patch(f"{MODULE}.decrypt_credentials")
async def test_sync_contacts_updates_existing_contact_different_etag(
    mock_creds: MagicMock,
    mock_disc: AsyncMock,
    mock_rebuild: AsyncMock,
) -> None:
    from app.services.contacts.sync import sync_contacts

    mock_creds.return_value = {"username": "u", "password": "p"}
    mock_disc.return_value = _make_discovery()

    existing_contact = MagicMock()
    existing_contact.etag = "old-etag"

    config = _make_config()
    db = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = existing_contact
    db.execute.return_value = scalar_result

    xml = MULTISTATUS_TEMPLATE.format(responses=RESPONSE_OK)
    response = MagicMock()
    response.status_code = 207
    response.text = xml

    with patch("httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.request.return_value = response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        stats = await sync_contacts(db, config)

    assert stats["updated"] == 1
    assert existing_contact.etag == "etag1"


@pytest.mark.asyncio
@patch(f"{MODULE}._rebuild_email_cache", new_callable=AsyncMock)
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
@patch(f"{MODULE}.decrypt_credentials")
async def test_sync_contacts_skips_empty_vcard(
    mock_creds: MagicMock,
    mock_disc: AsyncMock,
    mock_rebuild: AsyncMock,
) -> None:
    from app.services.contacts.sync import sync_contacts

    mock_creds.return_value = {"username": "u", "password": "p"}
    mock_disc.return_value = _make_discovery()

    config = _make_config()
    db = AsyncMock()

    xml = MULTISTATUS_TEMPLATE.format(responses=RESPONSE_EMPTY_VCARD)
    response = MagicMock()
    response.status_code = 207
    response.text = xml

    with patch("httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.request.return_value = response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        stats = await sync_contacts(db, config)

    assert stats["added"] == 0
    assert stats["updated"] == 0


@pytest.mark.asyncio
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
@patch(f"{MODULE}.decrypt_credentials")
async def test_sync_contacts_http_error_raises(
    mock_creds: MagicMock,
    mock_disc: AsyncMock,
) -> None:
    from app.services.contacts.sync import sync_contacts

    mock_creds.return_value = {"username": "u", "password": "p"}
    mock_disc.return_value = _make_discovery()

    config = _make_config()
    db = AsyncMock()

    response = MagicMock()
    response.status_code = 403
    response.text = ""

    with patch("httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.request.return_value = response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(ConnectionError, match="HTTP 403"):
            await sync_contacts(db, config)


@pytest.mark.asyncio
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
@patch(f"{MODULE}.decrypt_credentials")
async def test_sync_contacts_discovery_failure_raises(
    mock_creds: MagicMock,
    mock_disc: AsyncMock,
) -> None:
    from app.services.contacts.sync import sync_contacts

    mock_creds.return_value = {"username": "u", "password": "p"}
    mock_disc.return_value = _make_discovery(success=False, message="timeout")

    config = _make_config()
    db = AsyncMock()

    with pytest.raises(ConnectionError, match="DAV discovery failed"):
        await sync_contacts(db, config)


@pytest.mark.asyncio
@patch(f"{MODULE}._rebuild_email_cache", new_callable=AsyncMock)
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
@patch(f"{MODULE}.decrypt_credentials")
async def test_sync_contacts_parse_error_increments_errors(
    mock_creds: MagicMock,
    mock_disc: AsyncMock,
    mock_rebuild: AsyncMock,
) -> None:
    from app.services.contacts.sync import sync_contacts

    mock_creds.return_value = {"username": "u", "password": "p"}
    mock_disc.return_value = _make_discovery()

    config = _make_config()
    db = AsyncMock()
    # Make the DB execute (select existing) raise to trigger parse error path
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.side_effect = ValueError("boom")
    db.execute.return_value = scalar_result

    xml = MULTISTATUS_TEMPLATE.format(responses=RESPONSE_OK)
    response = MagicMock()
    response.status_code = 207
    response.text = xml

    with patch("httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.request.return_value = response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        stats = await sync_contacts(db, config)

    assert stats["errors"] == 1


@pytest.mark.asyncio
@patch(f"{MODULE}._rebuild_email_cache", new_callable=AsyncMock)
@patch(f"{MODULE}.discover_dav", new_callable=AsyncMock)
@patch(f"{MODULE}.decrypt_credentials")
async def test_sync_contacts_same_etag_skips_update(
    mock_creds: MagicMock,
    mock_disc: AsyncMock,
    mock_rebuild: AsyncMock,
) -> None:
    from app.services.contacts.sync import sync_contacts

    mock_creds.return_value = {"username": "u", "password": "p"}
    mock_disc.return_value = _make_discovery()

    existing_contact = MagicMock()
    existing_contact.etag = "etag1"  # same as in RESPONSE_OK

    config = _make_config()
    db = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = existing_contact
    db.execute.return_value = scalar_result

    xml = MULTISTATUS_TEMPLATE.format(responses=RESPONSE_OK)
    response = MagicMock()
    response.status_code = 207
    response.text = xml

    with patch("httpx.AsyncClient") as MockClient:
        client_instance = AsyncMock()
        client_instance.request.return_value = response
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client_instance)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        stats = await sync_contacts(db, config)

    assert stats["added"] == 0
    assert stats["updated"] == 0


# ---------------------------------------------------------------------------
# _rebuild_email_cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch(f"{MODULE}.get_cache_client")
@patch(f"{MODULE}._get_contact_cache_ttl", return_value=3600)
async def test_rebuild_email_cache_sets_keys(
    mock_ttl: MagicMock,
    mock_cache_client: MagicMock,
) -> None:
    from app.services.contacts.sync import _rebuild_email_cache

    cache = AsyncMock()
    mock_cache_client.return_value = cache

    contact = MagicMock()
    contact.id = uuid4()
    contact.emails = ["alice@example.com", "ALICE@EXAMPLE.COM"]

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [contact]
    db.execute.return_value = result

    user_id = uuid4()
    await _rebuild_email_cache(db, user_id)

    assert cache.setex.await_count == 2
    # Both should be lowercased
    calls = [c.args for c in cache.setex.await_args_list]
    assert all(f"contact_match:{user_id}:" in c[0] for c in calls)


@pytest.mark.asyncio
@patch(f"{MODULE}.get_cache_client")
@patch(f"{MODULE}._get_contact_cache_ttl", return_value=3600)
async def test_rebuild_email_cache_no_emails_skips(
    mock_ttl: MagicMock,
    mock_cache_client: MagicMock,
) -> None:
    from app.services.contacts.sync import _rebuild_email_cache

    cache = AsyncMock()
    mock_cache_client.return_value = cache

    contact = MagicMock()
    contact.emails = None

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [contact]
    db.execute.return_value = result

    await _rebuild_email_cache(db, uuid4())
    cache.setex.assert_not_awaited()
