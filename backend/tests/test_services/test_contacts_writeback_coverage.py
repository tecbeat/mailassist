"""Coverage tests for app.services.contacts.writeback.

Covers: write_back_email_to_contact, remove_email_from_contact, auto_add_sender_email.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_config():
    config = MagicMock()
    config.carddav_url = "https://nc.example.com"
    config.address_book = "contacts"
    config.encrypted_credentials = b"encrypted"
    config.user_id = uuid4()
    config.is_active = True
    return config


def _make_contact(*, emails=None, user_id=None):
    contact = MagicMock()
    contact.id = uuid4()
    contact.user_id = user_id or uuid4()
    contact.carddav_uid = "abc-123"
    contact.emails = emails or []
    contact.etag = "etag1"
    contact.raw_vcard = ""
    return contact


def _make_discovery(*, success=True, addressbook_home="https://nc.example.com/dav/ab"):
    d = MagicMock()
    d.success = success
    d.addressbook_home = addressbook_home
    d.message = "ok" if success else "failed"
    return d


# ---------------------------------------------------------------------------
# write_back_email_to_contact
# ---------------------------------------------------------------------------


class TestWriteBackEmailToContact:
    @pytest.mark.asyncio
    async def test_email_already_exists_returns_true(self):
        from app.services.contacts.writeback import write_back_email_to_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact(emails=["alice@example.com"])

        with patch(
            "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
        ):
            result = await write_back_email_to_contact(db, config, contact, "Alice@Example.com")

        assert result is True

    @pytest.mark.asyncio
    async def test_discovery_exception_returns_false(self):
        from app.services.contacts.writeback import write_back_email_to_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", side_effect=RuntimeError("boom")),
        ):
            result = await write_back_email_to_contact(db, config, contact, "new@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_discovery_failure_returns_false(self):
        from app.services.contacts.writeback import write_back_email_to_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch(
                "app.services.contacts.writeback.discover_dav",
                AsyncMock(return_value=_make_discovery(success=False, addressbook_home="")),
            ),
        ):
            result = await write_back_email_to_contact(db, config, contact, "new@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_fetch_non200_returns_false(self):
        from app.services.contacts.writeback import write_back_email_to_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        mock_resp = MagicMock()
        mock_resp.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await write_back_email_to_contact(db, config, contact, "new@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_put_success_updates_contact(self):
        from app.services.contacts.writeback import write_back_email_to_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact(user_id=uuid4())

        vcard_text = "BEGIN:VCARD\nVERSION:3.0\nFN:Test\nEND:VCARD"
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.headers = {"ETag": '"etag1"'}
        get_resp.text = vcard_text

        put_resp = MagicMock()
        put_resp.status_code = 204
        put_resp.headers = {"ETag": '"etag2"'}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=get_resp)
        mock_client.put = AsyncMock(return_value=put_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_cache = AsyncMock()

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.contacts.writeback.get_cache_client", return_value=mock_cache),
        ):
            result = await write_back_email_to_contact(db, config, contact, "new@example.com")

        assert result is True
        db.commit.assert_awaited_once()
        assert "new@example.com" in contact.emails

    @pytest.mark.asyncio
    async def test_put_412_retries(self):
        from app.services.contacts.writeback import write_back_email_to_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact(user_id=uuid4())

        vcard_text = "BEGIN:VCARD\nVERSION:3.0\nFN:Test\nEND:VCARD"
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.headers = {"ETag": '"etag1"'}
        get_resp.text = vcard_text

        put_412 = MagicMock()
        put_412.status_code = 412

        put_ok = MagicMock()
        put_ok.status_code = 204
        put_ok.headers = {"ETag": '"etag3"'}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=get_resp)
        mock_client.put = AsyncMock(side_effect=[put_412, put_412, put_ok])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_cache = AsyncMock()

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.contacts.writeback.get_cache_client", return_value=mock_cache),
        ):
            result = await write_back_email_to_contact(db, config, contact, "retry@example.com")

        assert result is True

    @pytest.mark.asyncio
    async def test_put_unexpected_status_returns_false(self):
        from app.services.contacts.writeback import write_back_email_to_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        vcard_text = "BEGIN:VCARD\nVERSION:3.0\nFN:Test\nEND:VCARD"
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.headers = {"ETag": '"etag1"'}
        get_resp.text = vcard_text

        put_resp = MagicMock()
        put_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=get_resp)
        mock_client.put = AsyncMock(return_value=put_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await write_back_email_to_contact(db, config, contact, "fail@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_exception_during_put_retries_then_fails(self):
        from app.services.contacts.writeback import write_back_email_to_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=RuntimeError("network error"))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await write_back_email_to_contact(db, config, contact, "err@example.com")

        assert result is False


# ---------------------------------------------------------------------------
# remove_email_from_contact
# ---------------------------------------------------------------------------


class TestRemoveEmailFromContact:
    @pytest.mark.asyncio
    async def test_discovery_exception_returns_false(self):
        from app.services.contacts.writeback import remove_email_from_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact(emails=["a@b.com"])

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", side_effect=RuntimeError("boom")),
        ):
            result = await remove_email_from_contact(db, config, contact, "a@b.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_discovery_no_addressbook_home_returns_false(self):
        from app.services.contacts.writeback import remove_email_from_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch(
                "app.services.contacts.writeback.discover_dav",
                AsyncMock(return_value=_make_discovery(success=False, addressbook_home="")),
            ),
        ):
            result = await remove_email_from_contact(db, config, contact, "x@y.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_non200_returns_false(self):
        from app.services.contacts.writeback import remove_email_from_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        get_resp = MagicMock()
        get_resp.status_code = 404

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=get_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await remove_email_from_contact(db, config, contact, "x@y.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_email_not_on_vcard_returns_true(self):
        from app.services.contacts.writeback import remove_email_from_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        vcard_text = "BEGIN:VCARD\nVERSION:3.0\nFN:Test\nEND:VCARD"
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.headers = {"ETag": '"etag1"'}
        get_resp.text = vcard_text

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=get_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await remove_email_from_contact(db, config, contact, "nothere@example.com")

        assert result is True

    @pytest.mark.asyncio
    async def test_remove_success_updates_contact(self):
        from app.services.contacts.writeback import remove_email_from_contact

        db = AsyncMock()
        config = _make_config()
        user_id = uuid4()
        contact = _make_contact(emails=["target@example.com"], user_id=user_id)

        vcard_text = "BEGIN:VCARD\nVERSION:3.0\nFN:Test\nEMAIL;TYPE=INTERNET:target@example.com\nEND:VCARD"
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.headers = {"ETag": '"etag1"'}
        get_resp.text = vcard_text

        put_resp = MagicMock()
        put_resp.status_code = 204
        put_resp.headers = {"ETag": '"etag2"'}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=get_resp)
        mock_client.put = AsyncMock(return_value=put_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_cache = AsyncMock()

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
            patch("app.services.contacts.writeback.get_cache_client", return_value=mock_cache),
        ):
            result = await remove_email_from_contact(db, config, contact, "target@example.com")

        assert result is True
        db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remove_412_retries_then_exhausted(self):
        from app.services.contacts.writeback import remove_email_from_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        vcard_text = "BEGIN:VCARD\nVERSION:3.0\nFN:Test\nEMAIL;TYPE=INTERNET:rm@example.com\nEND:VCARD"
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.headers = {"ETag": '"etag1"'}
        get_resp.text = vcard_text

        put_resp = MagicMock()
        put_resp.status_code = 412

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=get_resp)
        mock_client.put = AsyncMock(return_value=put_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await remove_email_from_contact(db, config, contact, "rm@example.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_remove_put_unexpected_status_returns_false(self):
        from app.services.contacts.writeback import remove_email_from_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        vcard_text = "BEGIN:VCARD\nVERSION:3.0\nFN:Test\nEMAIL;TYPE=INTERNET:x@y.com\nEND:VCARD"
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.headers = {"ETag": '"etag1"'}
        get_resp.text = vcard_text

        put_resp = MagicMock()
        put_resp.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=get_resp)
        mock_client.put = AsyncMock(return_value=put_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await remove_email_from_contact(db, config, contact, "x@y.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_remove_exception_retries_then_fails(self):
        from app.services.contacts.writeback import remove_email_from_contact

        db = AsyncMock()
        config = _make_config()
        contact = _make_contact()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=RuntimeError("network"))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "app.services.contacts.writeback.decrypt_credentials", return_value={"username": "u", "password": "p"}
            ),
            patch("app.services.contacts.writeback.discover_dav", AsyncMock(return_value=_make_discovery())),
            patch("app.services.contacts.writeback.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await remove_email_from_contact(db, config, contact, "err@example.com")

        assert result is False


# ---------------------------------------------------------------------------
# auto_add_sender_email
# ---------------------------------------------------------------------------


class TestAutoAddSenderEmail:
    @pytest.mark.asyncio
    async def test_empty_email_returns_false(self):
        from app.services.contacts.writeback import auto_add_sender_email

        result = await auto_add_sender_email(uuid4(), uuid4(), "  ")
        assert result is False

    @pytest.mark.asyncio
    async def test_contact_not_found_returns_false(self):
        from app.services.contacts.writeback import auto_add_sender_email

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with patch("app.services.contacts.writeback.get_session_ctx", fake_session):
            result = await auto_add_sender_email(uuid4(), uuid4(), "a@b.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_contact_wrong_user_returns_false(self):
        from app.services.contacts.writeback import auto_add_sender_email

        user_id = uuid4()
        contact = MagicMock()
        contact.user_id = uuid4()  # different user
        contact.emails = []

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=contact)

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with patch("app.services.contacts.writeback.get_session_ctx", fake_session):
            result = await auto_add_sender_email(user_id, uuid4(), "a@b.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_email_already_on_contact_returns_true(self):
        from app.services.contacts.writeback import auto_add_sender_email

        user_id = uuid4()
        contact = MagicMock()
        contact.user_id = user_id
        contact.emails = ["a@b.com"]

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=contact)

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with patch("app.services.contacts.writeback.get_session_ctx", fake_session):
            result = await auto_add_sender_email(user_id, uuid4(), "A@B.COM")

        assert result is True

    @pytest.mark.asyncio
    async def test_success_with_carddav_and_cache(self):
        from app.services.contacts.writeback import auto_add_sender_email

        user_id = uuid4()
        contact_id = uuid4()
        contact = MagicMock()
        contact.id = contact_id
        contact.user_id = user_id
        contact.emails = []

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=contact)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        carddav_config = MagicMock()
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = carddav_config
        mock_db.execute = AsyncMock(return_value=config_result)

        mock_cache = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with (
            patch("app.services.contacts.writeback.get_session_ctx", fake_session),
            patch("app.services.contacts.writeback.write_back_email_to_contact", new_callable=AsyncMock) as mock_wb,
            patch("app.services.contacts.writeback.get_cache_client", return_value=mock_cache),
            patch("app.services.contacts.writeback.get_settings") as mock_s,
        ):
            mock_s.return_value.contact_cache_ttl_seconds = 3600
            result = await auto_add_sender_email(user_id, contact_id, "new@example.com")

        assert result is True
        mock_wb.assert_awaited_once()
        mock_cache.setex.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_success_without_carddav(self):
        from app.services.contacts.writeback import auto_add_sender_email

        user_id = uuid4()
        contact = MagicMock()
        contact.id = uuid4()
        contact.user_id = user_id
        contact.emails = []

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=contact)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=config_result)

        mock_cache = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with (
            patch("app.services.contacts.writeback.get_session_ctx", fake_session),
            patch("app.services.contacts.writeback.get_cache_client", return_value=mock_cache),
            patch("app.services.contacts.writeback.get_settings") as mock_s,
        ):
            mock_s.return_value.contact_cache_ttl_seconds = 3600
            result = await auto_add_sender_email(user_id, uuid4(), "new@example.com")

        assert result is True

    @pytest.mark.asyncio
    async def test_exception_returns_false(self):
        from app.services.contacts.writeback import auto_add_sender_email

        with patch("app.services.contacts.writeback.get_session_ctx", side_effect=RuntimeError("db down")):
            result = await auto_add_sender_email(uuid4(), uuid4(), "x@y.com")

        assert result is False

    @pytest.mark.asyncio
    async def test_writeback_exception_swallowed(self):
        from app.services.contacts.writeback import auto_add_sender_email

        user_id = uuid4()
        contact = MagicMock()
        contact.id = uuid4()
        contact.user_id = user_id
        contact.emails = []

        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=contact)
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()

        carddav_config = MagicMock()
        config_result = MagicMock()
        config_result.scalar_one_or_none.return_value = carddav_config
        mock_db.execute = AsyncMock(return_value=config_result)

        mock_cache = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with (
            patch("app.services.contacts.writeback.get_session_ctx", fake_session),
            patch(
                "app.services.contacts.writeback.write_back_email_to_contact",
                new_callable=AsyncMock,
                side_effect=RuntimeError("writeback boom"),
            ),
            patch("app.services.contacts.writeback.get_cache_client", return_value=mock_cache),
            patch("app.services.contacts.writeback.get_settings") as mock_s,
        ):
            mock_s.return_value.contact_cache_ttl_seconds = 3600
            result = await auto_add_sender_email(user_id, uuid4(), "new@example.com")

        assert result is True
