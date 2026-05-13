"""Comprehensive API endpoint tests to boost coverage.

Tests contacts, dashboard, mail_accounts, and auth endpoints by calling
the endpoint functions directly with mocked DB sessions and dependencies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_USER_ID = uuid4()


def _mock_db_result(value):
    """Create a mock DB result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    result.scalar_one.return_value = value if value is not None else 0
    result.scalars.return_value.all.return_value = value if isinstance(value, list) else [value] if value else []
    result.all.return_value = value if isinstance(value, list) else []
    return result


def _async_db(execute_return=None):
    """Create a mock async DB session."""
    db = AsyncMock()
    if execute_return is not None:
        db.execute.return_value = execute_return
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.delete = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    return db


def _make_contact_model(user_id=None, **kwargs):
    """Create a mock Contact ORM object."""
    c = MagicMock()
    c.id = kwargs.get("id", uuid4())
    c.user_id = user_id or FAKE_USER_ID
    c.carddav_uid = kwargs.get("carddav_uid", "uid-123")
    c.display_name = kwargs.get("display_name", "Jane Doe")
    c.first_name = kwargs.get("first_name", "Jane")
    c.last_name = kwargs.get("last_name", "Doe")
    c.emails = kwargs.get("emails", ["jane@example.com"])
    c.phones = kwargs.get("phones", [])
    c.organization = kwargs.get("organization", "Acme")
    c.title = kwargs.get("title")
    c.raw_vcard = kwargs.get("raw_vcard", "BEGIN:VCARD\nEND:VCARD")
    c.etag = kwargs.get("etag", "etag-1")
    c.synced_at = kwargs.get("synced_at", datetime.now(UTC))
    c.created_at = kwargs.get("created_at", datetime.now(UTC))
    c.updated_at = kwargs.get("updated_at", datetime.now(UTC))
    return c


def _make_account_model(user_id=None, **kwargs):
    """Create a mock MailAccount ORM object."""
    a = MagicMock()
    a.id = kwargs.get("id", uuid4())
    a.user_id = user_id or FAKE_USER_ID
    a.name = kwargs.get("name", "Test Account")
    a.email_address = kwargs.get("email_address", "test@example.com")
    a.imap_host = kwargs.get("imap_host", "imap.example.com")
    a.imap_port = kwargs.get("imap_port", 993)
    a.imap_use_ssl = kwargs.get("imap_use_ssl", True)
    a.encrypted_credentials = kwargs.get("encrypted_credentials", b'{"username":"u","password":"p"}')
    a.polling_enabled = kwargs.get("polling_enabled", True)
    a.polling_interval_minutes = kwargs.get("polling_interval_minutes", 5)
    a.idle_enabled = kwargs.get("idle_enabled", False)
    a.scan_existing_emails = kwargs.get("scan_existing_emails", False)
    a.is_paused = kwargs.get("is_paused", False)
    a.manually_paused = kwargs.get("manually_paused", False)
    a.paused_reason = kwargs.get("paused_reason")
    a.paused_at = kwargs.get("paused_at")
    a.consecutive_errors = kwargs.get("consecutive_errors", 0)
    a.last_error = kwargs.get("last_error")
    a.last_error_at = kwargs.get("last_error_at")
    a.excluded_folders = kwargs.get("excluded_folders", [])
    a.created_at = kwargs.get("created_at", datetime.now(UTC))
    a.updated_at = kwargs.get("updated_at", datetime.now(UTC))
    a.initial_scan_done = kwargs.get("initial_scan_done", False)
    a.last_sync_at = kwargs.get("last_sync_at")
    return a


def _make_carddav_config(user_id=None, **kwargs):
    """Create a mock CardDAVConfig ORM object."""
    c = MagicMock()
    c.id = kwargs.get("id", uuid4())
    c.user_id = user_id or FAKE_USER_ID
    c.carddav_url = kwargs.get("carddav_url", "https://dav.example.com")
    c.encrypted_credentials = kwargs.get("encrypted_credentials", b'{"username":"u","password":"p"}')
    c.address_book = kwargs.get("address_book", "default")
    c.sync_interval = kwargs.get("sync_interval", 60)
    c.is_active = kwargs.get("is_active", True)
    c.last_sync_at = kwargs.get("last_sync_at")
    c.sync_token = kwargs.get("sync_token")
    c.created_at = kwargs.get("created_at", datetime.now(UTC))
    c.updated_at = kwargs.get("updated_at", datetime.now(UTC))
    return c


def _make_tracked_email(user_id=None, **kwargs):
    """Create a mock TrackedEmail ORM object."""
    t = MagicMock()
    t.id = kwargs.get("id", uuid4())
    t.user_id = user_id or FAKE_USER_ID
    t.mail_account_id = kwargs.get("mail_account_id", uuid4())
    t.mail_uid = kwargs.get("mail_uid", "12345")
    t.subject = kwargs.get("subject", "Test Subject")
    t.sender = kwargs.get("sender", "sender@example.com")
    t.current_folder = kwargs.get("current_folder", "INBOX")
    t.status = kwargs.get("status", "failed")
    t.last_error = kwargs.get("last_error", "Some error")
    t.error_type = kwargs.get("error_type")
    t.retry_count = kwargs.get("retry_count", 3)
    t.plugins_completed = kwargs.get("plugins_completed", [])
    t.plugins_failed = kwargs.get("plugins_failed", [])
    t.plugins_skipped = kwargs.get("plugins_skipped", [])
    t.completion_reason = kwargs.get("completion_reason")
    t.created_at = kwargs.get("created_at", datetime.now(UTC))
    t.updated_at = kwargs.get("updated_at", datetime.now(UTC))
    return t


# ===========================================================================
# Contacts API
# ===========================================================================


class TestContactsGetConfig:
    """GET /api/contacts/config"""

    @pytest.mark.asyncio
    async def test_get_config_none_returns_null(self):
        from app.api.contacts import get_config

        db = _async_db(_mock_db_result(None))
        result = await get_config(db, FAKE_USER_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_config_exists_returns_response(self):
        from app.api.contacts import get_config

        config = _make_carddav_config()
        db = _async_db(_mock_db_result(config))

        with patch("app.api.contacts.CardDAVConfigResponse") as MockResp:
            MockResp.model_validate.return_value = MagicMock()
            await get_config(db, FAKE_USER_ID)
            MockResp.model_validate.assert_called_once_with(config)


class TestContactsUpsertConfig:
    """PUT /api/contacts/config"""

    @pytest.mark.asyncio
    async def test_upsert_config_create_no_credentials_raises_422(self):
        from fastapi import HTTPException

        from app.api.contacts import upsert_config

        db = _async_db(_mock_db_result(None))
        data = MagicMock()
        data.username = ""
        data.password = ""
        data.carddav_url = "https://dav.example.com"
        data.address_book = "default"
        data.sync_interval = 60

        with patch("app.api.contacts.get_encryption"):
            with pytest.raises(HTTPException) as exc_info:
                await upsert_config(data, db, FAKE_USER_ID)
            assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_upsert_config_create_success(self):
        from app.api.contacts import upsert_config

        db = _async_db(_mock_db_result(None))
        data = MagicMock()
        data.username = "user"
        data.password = "pass"
        data.carddav_url = "https://dav.example.com"
        data.address_book = "default"
        data.sync_interval = 60

        fake_enc = MagicMock()
        fake_enc.encrypt.return_value = b"encrypted"

        with (
            patch("app.api.contacts.get_encryption", return_value=fake_enc),
            patch("app.api.contacts.sync_contacts", new_callable=AsyncMock, return_value={"created": 1}),
            patch("app.api.contacts.CardDAVConfigResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await upsert_config(data, db, FAKE_USER_ID)
            db.add.assert_called_once()
            db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_upsert_config_update_existing_keeps_credentials(self):
        from app.api.contacts import upsert_config

        existing = _make_carddav_config()
        db = _async_db(_mock_db_result(existing))
        data = MagicMock()
        data.username = ""
        data.password = ""
        data.carddav_url = "https://new.example.com"
        data.address_book = "new-book"
        data.sync_interval = 120

        fake_enc = MagicMock()

        with (
            patch("app.api.contacts.get_encryption", return_value=fake_enc),
            patch("app.api.contacts.sync_contacts", new_callable=AsyncMock, return_value={}),
            patch("app.api.contacts.CardDAVConfigResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await upsert_config(data, db, FAKE_USER_ID)
            assert existing.carddav_url == "https://new.example.com"
            # encrypt should not have been called since no new creds
            fake_enc.encrypt.assert_not_called()

    @pytest.mark.asyncio
    async def test_upsert_config_sync_failure_still_returns(self):
        from app.api.contacts import upsert_config

        existing = _make_carddav_config()
        db = _async_db(_mock_db_result(existing))
        data = MagicMock()
        data.username = "u"
        data.password = "p"
        data.carddav_url = "https://dav.example.com"
        data.address_book = "default"
        data.sync_interval = 60

        fake_enc = MagicMock()
        fake_enc.encrypt.return_value = b"encrypted"

        with (
            patch("app.api.contacts.get_encryption", return_value=fake_enc),
            patch("app.api.contacts.sync_contacts", new_callable=AsyncMock, side_effect=RuntimeError("sync failed")),
            patch("app.api.contacts.CardDAVConfigResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await upsert_config(data, db, FAKE_USER_ID)
            # Should succeed despite sync failure
            MockResp.model_validate.assert_called_once()


class TestContactsTestConfig:
    """POST /api/contacts/config/test"""

    @pytest.mark.asyncio
    async def test_test_config_success(self):
        from app.api.contacts import test_config

        data = MagicMock()
        data.carddav_url = "https://dav.example.com"
        data.username = "u"
        data.password = "p"
        data.address_book = "default"

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.message = "OK"
        mock_result.details = {}

        with patch("app.api.contacts.test_carddav_connection", new_callable=AsyncMock, return_value=mock_result):
            result = await test_config(data, FAKE_USER_ID)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_test_config_failure_raises_502(self):
        from fastapi import HTTPException

        from app.api.contacts import test_config

        data = MagicMock()
        data.carddav_url = "https://dav.example.com"
        data.username = "u"
        data.password = "p"
        data.address_book = "default"

        with patch(
            "app.api.contacts.test_carddav_connection",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await test_config(data, FAKE_USER_ID)
            assert exc_info.value.status_code == 502


class TestContactsSync:
    """POST /api/contacts/sync"""

    @pytest.mark.asyncio
    async def test_sync_no_config_raises_404(self):
        from fastapi import HTTPException

        from app.api.contacts import trigger_sync

        db = _async_db(_mock_db_result(None))
        with pytest.raises(HTTPException) as exc_info:
            await trigger_sync(db, FAKE_USER_ID)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_sync_success(self):
        from app.api.contacts import trigger_sync

        config = _make_carddav_config()
        db = _async_db(_mock_db_result(config))

        with patch(
            "app.api.contacts.sync_contacts",
            new_callable=AsyncMock,
            return_value={"created": 5, "updated": 2, "deleted": 0, "added": 5, "errors": 0},
        ):
            result = await trigger_sync(db, FAKE_USER_ID)
            assert result.added == 5

    @pytest.mark.asyncio
    async def test_sync_failure_raises_502(self):
        from fastapi import HTTPException

        from app.api.contacts import trigger_sync

        config = _make_carddav_config()
        db = _async_db(_mock_db_result(config))

        with patch("app.api.contacts.sync_contacts", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            with pytest.raises(HTTPException) as exc_info:
                await trigger_sync(db, FAKE_USER_ID)
            assert exc_info.value.status_code == 502


class TestContactsList:
    """GET /api/contacts"""

    @pytest.mark.asyncio
    async def test_list_contacts_empty(self):
        from app.api.contacts import list_contacts
        from app.api.deps import PaginatedResult

        mock_result = PaginatedResult(items=[], total=0, page=1, per_page=50, pages=1)

        with patch("app.api.contacts.paginate", new_callable=AsyncMock, return_value=mock_result):
            db = _async_db()
            result = await list_contacts(db, FAKE_USER_ID, search=None, page=1, per_page=50)
            assert result.total == 0
            assert result.items == []

    @pytest.mark.asyncio
    async def test_list_contacts_with_search(self):
        from app.api.contacts import list_contacts
        from app.api.deps import PaginatedResult

        mock_result = PaginatedResult(items=[], total=0, page=1, per_page=50, pages=1)

        with patch("app.api.contacts.paginate", new_callable=AsyncMock, return_value=mock_result):
            db = _async_db()
            result = await list_contacts(db, FAKE_USER_ID, search="jane", page=1, per_page=50)
            assert result.total == 0


class TestContactsSenders:
    """GET /api/contacts/senders"""

    @pytest.mark.asyncio
    async def test_list_senders_empty(self):
        from app.api.contacts import list_all_senders

        db = _async_db()
        # First execute returns sender rows, second returns contacts
        sender_result = MagicMock()
        sender_result.all.return_value = []
        contact_result = MagicMock()
        contact_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[sender_result, contact_result])

        result = await list_all_senders(db, FAKE_USER_ID, search="", matched=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_senders_with_contacts(self):
        from app.api.contacts import list_all_senders

        db = _async_db()

        sender_row = MagicMock()
        sender_row.email_address = "alice@example.com"
        sender_row.mail_count = 3
        sender_result = MagicMock()
        sender_result.all.return_value = [sender_row]

        contact = MagicMock()
        contact.id = uuid4()
        contact.emails = ["alice@example.com"]
        contact_result = MagicMock()
        contact_result.scalars.return_value.all.return_value = [contact]

        db.execute = AsyncMock(side_effect=[sender_result, contact_result])

        result = await list_all_senders(db, FAKE_USER_ID, search="", matched=None)
        assert len(result) == 1
        assert result[0].matched_contact_id == contact.id

    @pytest.mark.asyncio
    async def test_list_senders_matched_filter(self):
        from app.api.contacts import list_all_senders

        db = _async_db()

        sender_row = MagicMock()
        sender_row.email_address = "unmatched@example.com"
        sender_row.mail_count = 1
        sender_result = MagicMock()
        sender_result.all.return_value = [sender_row]

        contact_result = MagicMock()
        contact_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[sender_result, contact_result])

        # matched=True should skip unmatched senders
        result = await list_all_senders(db, FAKE_USER_ID, search="", matched=True)
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_list_senders_unmatched_filter(self):
        from app.api.contacts import list_all_senders

        db = _async_db()

        sender_row = MagicMock()
        sender_row.email_address = "unmatched@example.com"
        sender_row.mail_count = 1
        sender_result = MagicMock()
        sender_result.all.return_value = [sender_row]

        contact_result = MagicMock()
        contact_result.scalars.return_value.all.return_value = []

        db.execute = AsyncMock(side_effect=[sender_result, contact_result])

        # matched=False should include unmatched senders
        result = await list_all_senders(db, FAKE_USER_ID, search="", matched=False)
        assert len(result) == 1


class TestContactsGetById:
    """GET /api/contacts/{contact_id}"""

    @pytest.mark.asyncio
    async def test_get_contact_success(self):
        from app.api.contacts import get_contact

        contact = _make_contact_model()
        db = _async_db()

        with (
            patch("app.api.contacts.get_or_404", new_callable=AsyncMock, return_value=contact),
            patch("app.api.contacts.ContactResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await get_contact(contact.id, db, FAKE_USER_ID)
            MockResp.model_validate.assert_called_once_with(contact)


class TestContactsDelete:
    """DELETE /api/contacts/{contact_id}"""

    @pytest.mark.asyncio
    async def test_delete_contact_success(self):
        from app.api.contacts import delete_contact

        contact = _make_contact_model()
        db = _async_db()

        with patch("app.api.contacts.get_or_404", new_callable=AsyncMock, return_value=contact):
            await delete_contact(contact.id, db, FAKE_USER_ID)
            db.delete.assert_awaited_once_with(contact)


class TestContactsMails:
    """GET /api/contacts/{contact_id}/mails"""

    @pytest.mark.asyncio
    async def test_list_contact_mails_empty(self):
        from app.api.contacts import list_contact_mails
        from app.api.deps import PaginatedResult

        contact = _make_contact_model()
        db = _async_db()
        mock_result = PaginatedResult(items=[], total=0, page=1, per_page=20, pages=1)

        with (
            patch("app.api.contacts.get_or_404", new_callable=AsyncMock, return_value=contact),
            patch("app.api.contacts.paginate", new_callable=AsyncMock, return_value=mock_result),
        ):
            result = await list_contact_mails(contact.id, db, FAKE_USER_ID)
            assert result.total == 0


class TestContactsUnlinkMail:
    """DELETE /api/contacts/{contact_id}/mails/{assignment_id}"""

    @pytest.mark.asyncio
    async def test_unlink_success(self):
        from app.api.contacts import unlink_contact_mail

        contact_id = uuid4()
        assignment = MagicMock()
        assignment.contact_id = contact_id
        db = _async_db()

        with patch("app.api.contacts.get_or_404", new_callable=AsyncMock, return_value=assignment):
            await unlink_contact_mail(contact_id, assignment.id, db, FAKE_USER_ID)
            db.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unlink_wrong_contact_raises_404(self):
        from fastapi import HTTPException

        from app.api.contacts import unlink_contact_mail

        assignment = MagicMock()
        assignment.contact_id = uuid4()  # different from contact_id
        db = _async_db()

        with patch("app.api.contacts.get_or_404", new_callable=AsyncMock, return_value=assignment):
            with pytest.raises(HTTPException) as exc_info:
                await unlink_contact_mail(uuid4(), assignment.id, db, FAKE_USER_ID)
            assert exc_info.value.status_code == 404


class TestContactsAssignEmail:
    """POST /api/contacts/{contact_id}/emails"""

    @pytest.mark.asyncio
    async def test_assign_email_new(self):
        from app.api.contacts import assign_email_to_contact

        contact = _make_contact_model(emails=["old@example.com"])
        config = _make_carddav_config()
        db = _async_db()

        # First call: get_or_404, second: carddav config lookup
        config_result = _mock_db_result(config)

        data = MagicMock()
        data.email_address = "new@example.com"

        fake_cache = AsyncMock()
        fake_settings = MagicMock()
        fake_settings.contact_cache_ttl_seconds = 3600

        with (
            patch("app.api.contacts.get_or_404", new_callable=AsyncMock, return_value=contact),
            patch.object(db, "execute", new_callable=AsyncMock, return_value=config_result),
            patch("app.api.contacts.write_back_email_to_contact", new_callable=AsyncMock),
            patch("app.api.contacts.get_cache_client", return_value=fake_cache),
            patch("app.core.config.get_settings", return_value=fake_settings),
        ):
            result = await assign_email_to_contact(contact.id, data, db, FAKE_USER_ID)
            assert result.email_address == "new@example.com"

    @pytest.mark.asyncio
    async def test_assign_email_already_present(self):
        from app.api.contacts import assign_email_to_contact

        contact = _make_contact_model(emails=["existing@example.com"])
        db = _async_db()

        data = MagicMock()
        data.email_address = "existing@example.com"

        fake_cache = AsyncMock()
        fake_settings = MagicMock()
        fake_settings.contact_cache_ttl_seconds = 3600

        with (
            patch("app.api.contacts.get_or_404", new_callable=AsyncMock, return_value=contact),
            patch("app.api.contacts.get_cache_client", return_value=fake_cache),
            patch("app.core.config.get_settings", return_value=fake_settings),
        ):
            result = await assign_email_to_contact(contact.id, data, db, FAKE_USER_ID)
            assert result.email_address == "existing@example.com"
            # Should not have flushed since email already present
            db.flush.assert_not_awaited()


class TestContactsRemoveEmail:
    """DELETE /api/contacts/{contact_id}/emails"""

    @pytest.mark.asyncio
    async def test_remove_email_success(self):
        from app.api.contacts import remove_email_from_contact_endpoint

        contact = _make_contact_model(emails=["remove@example.com", "keep@example.com"])
        db = _async_db()

        data = MagicMock()
        data.email_address = "remove@example.com"

        config_result = _mock_db_result(None)  # no carddav config
        fake_cache = AsyncMock()

        with (
            patch("app.api.contacts.get_or_404", new_callable=AsyncMock, return_value=contact),
            patch.object(db, "execute", new_callable=AsyncMock, return_value=config_result),
            patch("app.api.contacts.get_cache_client", return_value=fake_cache),
        ):
            result = await remove_email_from_contact_endpoint(contact.id, data, db, FAKE_USER_ID)
            assert result.email_address == "remove@example.com"
            fake_cache.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_remove_email_not_present(self):
        from app.api.contacts import remove_email_from_contact_endpoint

        contact = _make_contact_model(emails=["other@example.com"])
        db = _async_db()

        data = MagicMock()
        data.email_address = "missing@example.com"

        fake_cache = AsyncMock()

        with (
            patch("app.api.contacts.get_or_404", new_callable=AsyncMock, return_value=contact),
            patch("app.api.contacts.get_cache_client", return_value=fake_cache),
        ):
            result = await remove_email_from_contact_endpoint(contact.id, data, db, FAKE_USER_ID)
            assert result.writeback_triggered is False


class TestContactsExtract:
    """POST /api/contacts/extract-from-sender"""

    @pytest.mark.asyncio
    async def test_extract_no_summaries_returns_basic(self):
        from app.api.contacts import extract_contact_from_sender

        db = _async_db()
        summary_result = MagicMock()
        summary_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=summary_result)

        data = MagicMock()
        data.sender_email = "alice@example.com"

        result = await extract_contact_from_sender(data, db, FAKE_USER_ID)
        assert result.emails == ["alice@example.com"]
        assert "alice" in result.display_name.lower()


class TestContactsCreate:
    """POST /api/contacts"""

    @pytest.mark.asyncio
    async def test_create_contact_success(self):
        from app.api.contacts import create_contact

        db = _async_db()
        data = MagicMock()
        data.display_name = "New Contact"
        data.first_name = "New"
        data.last_name = "Contact"
        data.emails = ["new@example.com"]
        data.phones = ["+1234"]
        data.organization = "Corp"
        data.title = "Engineer"

        fake_cache = AsyncMock()
        fake_settings = MagicMock()
        fake_settings.contact_cache_ttl_seconds = 3600

        with (
            patch("app.api.contacts.get_cache_client", return_value=fake_cache),
            patch("app.core.config.get_settings", return_value=fake_settings),
            patch("app.api.contacts.ContactResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await create_contact(data, db, FAKE_USER_ID)
            db.add.assert_called_once()
            db.flush.assert_awaited()


class TestContactsAssignment:
    """GET /api/contacts/assignment/..."""

    @pytest.mark.asyncio
    async def test_get_mail_contact_by_mail_id_none(self):
        from app.api.contacts import get_mail_contact_by_mail_id

        db = _async_db(_mock_db_result(None))
        result = await get_mail_contact_by_mail_id(uuid4(), db, FAKE_USER_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_mail_contact_by_mail_id_found(self):
        from app.api.contacts import get_mail_contact_by_mail_id

        assignment = MagicMock()
        db = _async_db(_mock_db_result(assignment))

        with patch("app.api.contacts.ContactAssignmentSchema") as MockSchema:
            MockSchema.model_validate.return_value = MagicMock()
            await get_mail_contact_by_mail_id(uuid4(), db, FAKE_USER_ID)
            MockSchema.model_validate.assert_called_once_with(assignment)


# ===========================================================================
# Dashboard API
# ===========================================================================


class TestDashboardStats:
    """GET /api/dashboard/stats"""

    @pytest.mark.asyncio
    async def test_get_stats_success(self):
        from app.api.dashboard import get_dashboard_stats

        db = _async_db()
        # Need to mock many db.execute calls — just return 0/empty for all
        accounts_result = MagicMock()
        accounts_result.scalars.return_value.all.return_value = []
        providers_result = MagicMock()
        providers_result.scalars.return_value.all.return_value = []
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0

        db.execute = AsyncMock(return_value=count_result)
        # Override first two calls for accounts and providers
        call_count = 0
        returns = [accounts_result, providers_result] + [count_result] * 20

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            idx = min(call_count, len(returns) - 1)
            call_count += 1
            return returns[idx]

        db.execute = AsyncMock(side_effect=side_effect)

        with patch("app.api.dashboard._get_token_usage", new_callable=AsyncMock, return_value=0):
            result = await get_dashboard_stats(db, FAKE_USER_ID)
            assert result.active_accounts == 0
            assert result.pending_approvals == 0


class TestDashboardRecentActions:
    """GET /api/dashboard/recent-actions"""

    @pytest.mark.asyncio
    async def test_recent_actions_empty(self):
        from app.api.dashboard import get_recent_actions
        from app.api.deps import PaginatedResult

        mock_result = PaginatedResult(items=[], total=0, page=1, per_page=50, pages=1)

        with patch("app.api.dashboard.paginate", new_callable=AsyncMock, return_value=mock_result):
            db = _async_db()
            result = await get_recent_actions(db, FAKE_USER_ID)
            assert result.total == 0
            assert result.items == []


class TestDashboardErrors:
    """GET /api/dashboard/errors"""

    @pytest.mark.asyncio
    async def test_errors_empty(self):
        from app.api.dashboard import get_dashboard_errors
        from app.api.deps import PaginatedResult

        mock_result = PaginatedResult(items=[], total=0, page=1, per_page=50, pages=1)

        with patch("app.api.dashboard.paginate", new_callable=AsyncMock, return_value=mock_result):
            db = _async_db()
            result = await get_dashboard_errors(db, FAKE_USER_ID)
            assert result.total == 0

    @pytest.mark.asyncio
    async def test_errors_with_accounts(self):
        from app.api.dashboard import get_dashboard_errors
        from app.api.deps import PaginatedResult

        account = _make_account_model(
            last_error="IMAP timeout",
            last_error_at=datetime.now(UTC),
            consecutive_errors=5,
        )

        mock_result = PaginatedResult(items=[account], total=1, page=1, per_page=50, pages=1)

        with patch("app.api.dashboard.paginate", new_callable=AsyncMock, return_value=mock_result):
            db = _async_db()
            result = await get_dashboard_errors(db, FAKE_USER_ID)
            assert result.total == 1
            assert result.items[0].error == "IMAP timeout"


class TestDashboardFailedMails:
    """GET /api/dashboard/failed-mails"""

    @pytest.mark.asyncio
    async def test_failed_mails_empty(self):
        from app.api.dashboard import get_failed_mails
        from app.api.deps import PaginatedResult

        mock_result = PaginatedResult(items=[], total=0, page=1, per_page=50, pages=1)

        with patch("app.api.dashboard.paginate", new_callable=AsyncMock, return_value=mock_result):
            db = _async_db()
            result = await get_failed_mails(db, FAKE_USER_ID)
            assert result.total == 0

    @pytest.mark.asyncio
    async def test_failed_mails_with_data(self):
        from app.api.dashboard import get_failed_mails
        from app.api.deps import PaginatedResult

        te = _make_tracked_email()
        mock_result = PaginatedResult(items=[te], total=1, page=1, per_page=50, pages=1)

        with patch("app.api.dashboard.paginate", new_callable=AsyncMock, return_value=mock_result):
            db = _async_db()
            result = await get_failed_mails(db, FAKE_USER_ID)
            assert result.total == 1
            assert result.items[0].subject == "Test Subject"


class TestDashboardRetryFailedMail:
    """POST /api/dashboard/failed-mails/{id}/retry"""

    @pytest.mark.asyncio
    async def test_retry_success(self):
        from app.api.dashboard import retry_failed_mail

        te = _make_tracked_email()
        db = _async_db(_mock_db_result(te))

        result = await retry_failed_mail(db, FAKE_USER_ID, str(te.id))
        assert result.status == "queued"

    @pytest.mark.asyncio
    async def test_retry_not_found_raises_404(self):
        from fastapi import HTTPException

        from app.api.dashboard import retry_failed_mail

        db = _async_db(_mock_db_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await retry_failed_mail(db, FAKE_USER_ID, str(uuid4()))
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_invalid_uuid_raises_422(self):
        from fastapi import HTTPException

        from app.api.dashboard import retry_failed_mail

        db = _async_db()

        with pytest.raises(HTTPException) as exc_info:
            await retry_failed_mail(db, FAKE_USER_ID, "not-a-uuid")
        assert exc_info.value.status_code == 422


class TestDashboardResolveFailedMail:
    """POST /api/dashboard/failed-mails/{id}/resolve"""

    @pytest.mark.asyncio
    async def test_resolve_success(self):
        from app.api.dashboard import resolve_failed_mail

        te = _make_tracked_email()
        db = _async_db(_mock_db_result(te))

        result = await resolve_failed_mail(db, FAKE_USER_ID, str(te.id))
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_resolve_not_found_raises_404(self):
        from fastapi import HTTPException

        from app.api.dashboard import resolve_failed_mail

        db = _async_db(_mock_db_result(None))

        with pytest.raises(HTTPException) as exc_info:
            await resolve_failed_mail(db, FAKE_USER_ID, str(uuid4()))
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_resolve_invalid_uuid_raises_422(self):
        from fastapi import HTTPException

        from app.api.dashboard import resolve_failed_mail

        db = _async_db()

        with pytest.raises(HTTPException) as exc_info:
            await resolve_failed_mail(db, FAKE_USER_ID, "bad-uuid")
        assert exc_info.value.status_code == 422


class TestDashboardCrons:
    """GET /api/dashboard/crons"""

    @pytest.mark.asyncio
    async def test_get_crons_success(self):
        from app.api.dashboard import get_cron_jobs

        fake_cache = AsyncMock()
        fake_cache.get = AsyncMock(return_value=None)
        fake_task = AsyncMock()
        fake_task.keys = AsyncMock(return_value=[])

        with (
            patch("app.api.dashboard.get_cache_client", return_value=fake_cache),
            patch("app.api.dashboard.get_task_client", return_value=fake_task),
            patch("app.api.dashboard.get_settings") as mock_settings,
        ):
            mock_settings.return_value.cron_interval_minutes = 5
            result = await get_cron_jobs(FAKE_USER_ID)
            assert len(result.jobs) == 5

    @pytest.mark.asyncio
    async def test_get_crons_error_returns_empty(self):
        from app.api.dashboard import get_cron_jobs

        with (
            patch("app.api.dashboard.get_cache_client", side_effect=RuntimeError("fail")),
            patch("app.api.dashboard.get_settings") as mock_settings,
        ):
            mock_settings.return_value.cron_interval_minutes = 10
            result = await get_cron_jobs(FAKE_USER_ID)
            assert result.jobs == []


class TestDashboardTriggerCron:
    """POST /api/dashboard/crons/{name}/trigger"""

    @pytest.mark.asyncio
    async def test_trigger_unknown_cron_raises_404(self):
        from fastapi import HTTPException

        from app.api.dashboard import trigger_cron_job

        with pytest.raises(HTTPException) as exc_info:
            await trigger_cron_job(FAKE_USER_ID, "nonexistent")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_trigger_cron_success(self):
        from app.api.dashboard import trigger_cron_job

        mock_job = MagicMock()
        mock_job.job_id = "job-123"
        mock_arq = AsyncMock()
        mock_arq.enqueue_job = AsyncMock(return_value=mock_job)

        with patch("app.api.dashboard.get_arq_client", return_value=mock_arq):
            result = await trigger_cron_job(FAKE_USER_ID, "poll_mail_accounts")
            assert result.status == "enqueued"

    @pytest.mark.asyncio
    async def test_trigger_cron_already_queued(self):
        from app.api.dashboard import trigger_cron_job

        mock_arq = AsyncMock()
        mock_arq.enqueue_job = AsyncMock(return_value=None)

        with patch("app.api.dashboard.get_arq_client", return_value=mock_arq):
            result = await trigger_cron_job(FAKE_USER_ID, "poll_mail_accounts")
            assert result.status == "already_queued"


class TestDashboardJobParseId:
    """Unit tests for _parse_job_id."""

    def test_parse_process_mail_job(self):
        from app.api.dashboard import _parse_job_id

        fn, mail_uid, account_id = _parse_job_id("process_mail:acc-1:uid-2")
        assert fn == "process_mail"
        assert mail_uid == "uid-2"
        assert account_id == "acc-1"

    def test_parse_cron_job(self):
        from app.api.dashboard import _parse_job_id

        fn, mail_uid, _account_id = _parse_job_id("cron:poll_mail_accounts:abc123")
        assert fn == "poll_mail_accounts"
        assert mail_uid is None

    def test_parse_empty(self):
        from app.api.dashboard import _parse_job_id

        fn, mail_uid, _account_id = _parse_job_id("unknown")
        assert fn == "unknown"
        assert mail_uid is None


# ===========================================================================
# Mail Accounts API
# ===========================================================================


class TestMailAccountsList:
    """GET /api/mail-accounts"""

    @pytest.mark.asyncio
    async def test_list_accounts_empty(self):
        from app.api.mail_accounts import list_mail_accounts

        db = _async_db()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)

        result = await list_mail_accounts(db, FAKE_USER_ID)
        assert result == []


class TestMailAccountsCreate:
    """POST /api/mail-accounts"""

    @pytest.mark.asyncio
    async def test_create_account_success(self):
        from app.api.mail_accounts import create_mail_account

        db = _async_db()
        data = MagicMock()
        data.name = "My Mail"
        data.email_address = "me@example.com"
        data.imap_host = "imap.example.com"
        data.imap_port = 993
        data.imap_use_ssl = True
        data.username = "user"
        data.password = "pass"
        data.polling_enabled = True
        data.polling_interval_minutes = 5
        data.idle_enabled = False
        data.scan_existing_emails = False
        data.model_fields_set = {"polling_interval_minutes"}

        fake_enc = MagicMock()
        fake_enc.encrypt.return_value = b"encrypted"
        mock_arq = AsyncMock()
        mock_arq.enqueue_job = AsyncMock()

        with (
            patch("app.api.mail_accounts.get_encryption", return_value=fake_enc),
            patch("app.core.redis.get_arq_client", return_value=mock_arq),
            patch("app.api.mail_accounts.MailAccountResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await create_mail_account(data, db, FAKE_USER_ID)
            db.add.assert_called_once()
            mock_arq.enqueue_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_create_account_uses_default_interval(self):
        from app.api.mail_accounts import create_mail_account

        db = _async_db()
        data = MagicMock()
        data.name = "My Mail"
        data.email_address = "me@example.com"
        data.imap_host = "imap.example.com"
        data.imap_port = 993
        data.imap_use_ssl = True
        data.username = "user"
        data.password = "pass"
        data.polling_enabled = True
        data.polling_interval_minutes = 5
        data.idle_enabled = False
        data.scan_existing_emails = False
        data.model_fields_set = set()  # polling_interval not explicitly set

        fake_enc = MagicMock()
        fake_enc.encrypt.return_value = b"encrypted"
        mock_arq = AsyncMock()
        mock_arq.enqueue_job = AsyncMock()

        settings_mock = MagicMock()
        settings_mock.default_polling_interval_minutes = 10

        with (
            patch("app.api.mail_accounts.get_encryption", return_value=fake_enc),
            patch("app.core.redis.get_arq_client", return_value=mock_arq),
            patch("app.api.mail_accounts.get_or_create", new_callable=AsyncMock, return_value=settings_mock),
            patch("app.api.mail_accounts.MailAccountResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await create_mail_account(data, db, FAKE_USER_ID)


class TestMailAccountsGet:
    """GET /api/mail-accounts/{id}"""

    @pytest.mark.asyncio
    async def test_get_account_success(self):
        from app.api.mail_accounts import get_mail_account

        account = _make_account_model()
        db = _async_db()

        with (
            patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account),
            patch("app.api.mail_accounts.MailAccountResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await get_mail_account(account.id, db, FAKE_USER_ID)


class TestMailAccountsUpdate:
    """PUT /api/mail-accounts/{id}"""

    @pytest.mark.asyncio
    async def test_update_account_fields(self):
        from app.api.mail_accounts import update_mail_account

        account = _make_account_model()
        db = _async_db()
        data = MagicMock()
        data.model_dump.return_value = {"name": "Updated Name"}

        with (
            patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account),
            patch("app.api.mail_accounts.get_encryption"),
            patch("app.api.mail_accounts.MailAccountResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await update_mail_account(account.id, data, db, FAKE_USER_ID)
            assert account.name == "Updated Name"

    @pytest.mark.asyncio
    async def test_update_account_credentials(self):
        from app.api.mail_accounts import update_mail_account

        account = _make_account_model()
        db = _async_db()
        data = MagicMock()
        data.model_dump.return_value = {"username": "new_user", "password": "new_pass"}

        fake_enc = MagicMock()
        fake_enc.decrypt.return_value = '{"username":"old","password":"old"}'
        fake_enc.encrypt.return_value = b"new_encrypted"

        with (
            patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account),
            patch("app.api.mail_accounts.get_encryption", return_value=fake_enc),
            patch("app.api.mail_accounts.MailAccountResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await update_mail_account(account.id, data, db, FAKE_USER_ID)
            fake_enc.encrypt.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_account_decrypt_failure_raises_500(self):
        from fastapi import HTTPException

        from app.api.mail_accounts import update_mail_account

        account = _make_account_model()
        db = _async_db()
        data = MagicMock()
        data.model_dump.return_value = {"username": "new_user"}

        fake_enc = MagicMock()
        fake_enc.decrypt.side_effect = RuntimeError("decrypt failed")

        with (
            patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account),
            patch("app.api.mail_accounts.get_encryption", return_value=fake_enc),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await update_mail_account(account.id, data, db, FAKE_USER_ID)
            assert exc_info.value.status_code == 500


class TestMailAccountsDelete:
    """DELETE /api/mail-accounts/{id}"""

    @pytest.mark.asyncio
    async def test_delete_account(self):
        from app.api.mail_accounts import delete_mail_account

        account = _make_account_model()
        db = _async_db()

        with patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account):
            await delete_mail_account(account.id, db, FAKE_USER_ID)
            db.delete.assert_awaited_once_with(account)


class TestMailAccountsResetHealth:
    """POST /api/mail-accounts/{id}/reset-health"""

    @pytest.mark.asyncio
    async def test_reset_health_success(self):
        from app.api.mail_accounts import reset_account_health

        account = _make_account_model(consecutive_errors=10, is_paused=True)
        db = _async_db()

        mock_arq = AsyncMock()

        with (
            patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account),
            patch("app.core.redis.get_arq_client", return_value=mock_arq),
            patch("app.workers.scheduler.schedule_now", new_callable=AsyncMock),
            patch("app.api.mail_accounts.MailAccountResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await reset_account_health(account.id, db, FAKE_USER_ID)
            assert account.consecutive_errors == 0
            assert account.is_paused is False


class TestMailAccountsPause:
    """PATCH /api/mail-accounts/{id}/pause"""

    @pytest.mark.asyncio
    async def test_pause_account(self):
        from app.api.mail_accounts import update_pause_state

        account = _make_account_model()
        db = _async_db()
        data = MagicMock()
        data.paused = True
        data.pause_reason = "maintenance"

        with (
            patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account),
            patch("app.api.mail_accounts.MailAccountResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await update_pause_state(account.id, data, db, FAKE_USER_ID)
            assert account.is_paused is True
            assert account.manually_paused is True

    @pytest.mark.asyncio
    async def test_unpause_account(self):
        from app.api.mail_accounts import update_pause_state

        account = _make_account_model(is_paused=True)
        db = _async_db()
        data = MagicMock()
        data.paused = False

        mock_arq = AsyncMock()

        with (
            patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account),
            patch("app.core.redis.get_arq_client", return_value=mock_arq),
            patch("app.workers.scheduler.schedule_now", new_callable=AsyncMock),
            patch("app.api.mail_accounts.MailAccountResponse") as MockResp,
        ):
            MockResp.model_validate.return_value = MagicMock()
            await update_pause_state(account.id, data, db, FAKE_USER_ID)
            assert account.is_paused is False


class TestMailAccountsPoll:
    """POST /api/mail-accounts/{id}/poll"""

    @pytest.mark.asyncio
    async def test_poll_success(self):
        from app.api.mail_accounts import poll_account_now

        account = _make_account_model(is_paused=False)
        db = _async_db()

        mock_job = MagicMock()
        mock_job.job_id = "job-1"
        mock_arq = AsyncMock()
        mock_arq.enqueue_job = AsyncMock(return_value=mock_job)

        with (
            patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account),
            patch("app.core.redis.get_arq_client", return_value=mock_arq),
        ):
            result = await poll_account_now(account.id, db, FAKE_USER_ID)
            assert result.status == "queued"

    @pytest.mark.asyncio
    async def test_poll_paused_raises_400(self):
        from fastapi import HTTPException

        from app.api.mail_accounts import poll_account_now

        account = _make_account_model(is_paused=True)
        db = _async_db()

        with patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account):
            with pytest.raises(HTTPException) as exc_info:
                await poll_account_now(account.id, db, FAKE_USER_ID)
            assert exc_info.value.status_code == 400


class TestMailAccountsExcludedFolders:
    """PUT /api/mail-accounts/{id}/excluded-folders"""

    @pytest.mark.asyncio
    async def test_update_excluded_folders(self):
        from app.api.mail_accounts import update_excluded_folders

        account = _make_account_model()
        db = _async_db()
        data = MagicMock()
        data.excluded_folders = ["Trash", "Spam"]

        with patch("app.api.mail_accounts.get_or_404", new_callable=AsyncMock, return_value=account):
            result = await update_excluded_folders(account.id, data, db, FAKE_USER_ID)
            assert result.excluded_folders == ["Trash", "Spam"]


# ===========================================================================
# Auth API
# ===========================================================================


class TestAuthMe:
    """GET /auth/me"""

    @pytest.mark.asyncio
    async def test_me_no_session_raises_401(self):
        from fastapi import HTTPException

        from app.api.auth import get_current_user

        request = MagicMock()
        request.cookies = {}

        mock_settings = MagicMock()
        mock_settings.auth_disabled = False

        with (
            patch("app.api.auth.get_settings", return_value=mock_settings),
            patch("app.api.auth.get_session_client") as mock_client_fn,
        ):
            mock_client_fn.return_value = AsyncMock()
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(request)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_me_expired_session_raises_401(self):
        from fastapi import HTTPException

        from app.api.auth import get_current_user

        request = MagicMock()
        request.cookies = {"session_id": "expired-session"}

        mock_settings = MagicMock()
        mock_settings.auth_disabled = False

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)

        with (
            patch("app.api.auth.get_settings", return_value=mock_settings),
            patch("app.api.auth.get_session_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(request)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_me_valid_session(self):
        import json

        from app.api.auth import get_current_user

        request = MagicMock()
        request.cookies = {"session_id": "valid-session"}

        mock_settings = MagicMock()
        mock_settings.auth_disabled = False

        session_data = json.dumps(
            {
                "user_id": str(uuid4()),
                "email": "user@example.com",
                "display_name": "User",
            }
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=session_data)

        with (
            patch("app.api.auth.get_settings", return_value=mock_settings),
            patch("app.api.auth.get_session_client", return_value=mock_client),
        ):
            result = await get_current_user(request)
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_me_auth_disabled(self):
        from app.api.auth import get_current_user

        request = MagicMock()
        mock_settings = MagicMock()
        mock_settings.auth_disabled = True

        with (
            patch("app.api.auth.get_settings", return_value=mock_settings),
            patch("app.api.auth._get_or_create_no_auth_user", new_callable=AsyncMock, return_value=uuid4()),
        ):
            result = await get_current_user(request)
            assert result.status_code == 200


class TestAuthLogin:
    """GET /auth/login"""

    @pytest.mark.asyncio
    async def test_login_auth_disabled_redirects(self):
        from app.api.auth import login

        request = MagicMock()
        mock_settings = MagicMock()
        mock_settings.auth_disabled = True

        with patch("app.api.auth.get_settings", return_value=mock_settings):
            result = await login(request)
            assert result.status_code == 302

    @pytest.mark.asyncio
    async def test_login_rate_limited(self):
        from fastapi import HTTPException

        from app.api.auth import login

        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "1.2.3.4"

        mock_settings = MagicMock()
        mock_settings.auth_disabled = False
        mock_settings.auth_rate_limit = 5
        mock_settings.oidc_issuer_url = "https://auth.example.com"
        mock_settings.oidc_client_id = "client"
        mock_settings.oidc_redirect_uri = "https://app/callback"

        mock_session = AsyncMock()
        mock_session.eval = AsyncMock(return_value=100)  # over limit

        with (
            patch("app.api.auth.get_settings", return_value=mock_settings),
            patch(
                "app.api.auth._get_oidc_config",
                new_callable=AsyncMock,
                return_value={
                    "authorization_endpoint": "https://auth.example.com/auth",
                },
            ),
            patch("app.api.auth.get_session_client", return_value=mock_session),
            patch("app.api.auth.get_client_ip", return_value="1.2.3.4"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await login(request)
            assert exc_info.value.status_code == 429


class TestAuthLogout:
    """POST /auth/logout"""

    @pytest.mark.asyncio
    async def test_logout_no_session(self):
        from app.api.auth import logout

        request = MagicMock()
        request.cookies = {}

        mock_session = AsyncMock()

        with (
            patch("app.api.auth.get_session_client", return_value=mock_session),
            patch("app.api.auth._get_oidc_config", new_callable=AsyncMock, return_value={}),
        ):
            result = await logout(request)
            assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_logout_with_session(self):
        import json

        from app.api.auth import logout

        request = MagicMock()
        request.cookies = {"session_id": "sess-123"}

        fake_enc = MagicMock()
        fake_enc.decrypt.return_value = json.dumps(
            {
                "access_token": "at",
                "refresh_token": "rt",
                "id_token": "idt",
            }
        )

        session_data = json.dumps(
            {
                "user_id": str(uuid4()),
                "email": "user@example.com",
                "display_name": "User",
                "encrypted_tokens": "encrypted-blob",
            }
        )

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=session_data)
        mock_session.delete = AsyncMock()

        with (
            patch("app.api.auth.get_session_client", return_value=mock_session),
            patch("app.api.auth.get_encryption", return_value=fake_enc),
            patch(
                "app.api.auth._get_oidc_config",
                new_callable=AsyncMock,
                return_value={
                    "end_session_endpoint": "https://auth.example.com/logout",
                },
            ),
        ):
            result = await logout(request)
            assert result.status_code == 200
            mock_session.delete.assert_awaited_once()


class TestAuthCallback:
    """GET /auth/callback"""

    @pytest.mark.asyncio
    async def test_callback_error_redirects(self):
        from app.api.auth import callback

        request = MagicMock()
        result = await callback(request, error="access_denied", error_description="User denied")
        assert result.status_code == 302
        assert "error" in str(result.headers.get("location", ""))

    @pytest.mark.asyncio
    async def test_callback_missing_code_raises_400(self):
        from fastapi import HTTPException

        from app.api.auth import callback

        request = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            await callback(request, code=None, state=None)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_invalid_state_raises_400(self):
        from fastapi import HTTPException

        from app.api.auth import callback

        request = MagicMock()
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)

        mock_settings = MagicMock()
        mock_settings.auth_disabled = False

        with (
            patch("app.api.auth.get_settings", return_value=mock_settings),
            patch(
                "app.api.auth._get_oidc_config",
                new_callable=AsyncMock,
                return_value={
                    "token_endpoint": "https://auth.example.com/token",
                },
            ),
            patch("app.api.auth.get_session_client", return_value=mock_session),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await callback(request, code="code123", state="bad-state")
            assert exc_info.value.status_code == 400


class TestGetCurrentUserId:
    """get_current_user_id dependency function."""

    @pytest.mark.asyncio
    async def test_no_session_raises_401(self):
        from fastapi import HTTPException

        from app.api.auth import get_current_user_id

        request = MagicMock()
        request.cookies = {}

        mock_settings = MagicMock()
        mock_settings.auth_disabled = False

        mock_client = AsyncMock()

        with (
            patch("app.api.auth.get_settings", return_value=mock_settings),
            patch("app.api.auth.get_session_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_id(request)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_session_raises_401(self):

        from fastapi import HTTPException

        from app.api.auth import get_current_user_id

        request = MagicMock()
        request.cookies = {"session_id": "expired"}

        mock_settings = MagicMock()
        mock_settings.auth_disabled = False

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)

        with (
            patch("app.api.auth.get_settings", return_value=mock_settings),
            patch("app.api.auth.get_session_client", return_value=mock_client),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_id(request)
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_session_returns_uuid(self):
        import json

        from app.api.auth import get_current_user_id

        uid = uuid4()
        request = MagicMock()
        request.cookies = {"session_id": "valid"}

        mock_settings = MagicMock()
        mock_settings.auth_disabled = False

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=json.dumps({"user_id": str(uid)}))

        with (
            patch("app.api.auth.get_settings", return_value=mock_settings),
            patch("app.api.auth.get_session_client", return_value=mock_client),
        ):
            result = await get_current_user_id(request)
            assert result == uid

    @pytest.mark.asyncio
    async def test_auth_disabled_returns_default_user(self):
        from app.api.auth import get_current_user_id

        request = MagicMock()
        mock_settings = MagicMock()
        mock_settings.auth_disabled = True

        uid = uuid4()

        with (
            patch("app.api.auth.get_settings", return_value=mock_settings),
            patch("app.api.auth._get_or_create_no_auth_user", new_callable=AsyncMock, return_value=uid),
        ):
            result = await get_current_user_id(request)
            assert result == uid
