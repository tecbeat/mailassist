"""Comprehensive tests for app.services.mail to cover uncovered lines.

Covers: safe_imap_logout, connect_imap, imap_connection, folder cache,
resolve_folder, update_account_sync_status, check_circuit_breaker,
store_flags, _parse_copyuid, move_message, move_all_to_inbox,
delete_folder, rename_folder, get_folder_status, list_folders_with_counts,
fetch_raw_message, search_uids, fetch_envelopes, fetch_message_ids,
relocate_mail_across_folders.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.services.mail import (
    ImapConnection,
    MoveResult,
    RelocatedMail,
    _parse_copyuid,
    check_circuit_breaker,
    delete_folder,
    fetch_envelopes,
    fetch_message_ids,
    fetch_raw_message,
    get_cached_folders,
    get_folder_status,
    imap_connection,
    invalidate_folder_cache,
    list_folders_with_counts,
    move_all_to_inbox,
    move_message,
    relocate_mail_across_folders,
    rename_folder,
    resolve_folder,
    safe_imap_logout,
    search_uids,
    set_cached_folders,
    store_flags,
    update_account_sync_status,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(
    capabilities: list[str] | None = None,
    separator: str = "/",
) -> ImapConnection:
    mb = MagicMock()
    mb.folder = MagicMock()
    mb.client = MagicMock()
    return ImapConnection(
        mailbox=mb,
        account_id=uuid4(),
        host="imap.example.com",
        separator=separator,
        capabilities=capabilities,
    )


def _make_account(**overrides):
    acct = MagicMock()
    acct.id = overrides.get("id", uuid4())
    acct.imap_host = overrides.get("imap_host", "imap.example.com")
    acct.imap_port = overrides.get("imap_port", 993)
    acct.imap_use_ssl = overrides.get("imap_use_ssl", True)
    acct.encrypted_credentials = b"encrypted"
    return acct


# ---------------------------------------------------------------------------
# safe_imap_logout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_imap_logout_success_calls_logout() -> None:
    mb = MagicMock()
    with patch("app.services.mail.asyncio.to_thread", new_callable=AsyncMock) as mock_tt:
        await safe_imap_logout(mb)
    mock_tt.assert_awaited_once_with(mb.logout)


@pytest.mark.asyncio
async def test_safe_imap_logout_exception_suppressed() -> None:
    mb = MagicMock()
    with patch("app.services.mail.asyncio.to_thread", new_callable=AsyncMock, side_effect=OSError("gone")):
        await safe_imap_logout(mb)  # should not raise


# ---------------------------------------------------------------------------
# connect_imap
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_imap_no_ssl_raises() -> None:
    from app.services.mail import connect_imap

    acct = _make_account(imap_use_ssl=False)
    with patch("app.services.mail.decrypt_credentials", return_value={"username": "u", "password": "p"}):
        with pytest.raises(ValueError, match="SSL/TLS required"):
            await connect_imap(acct)


@pytest.mark.asyncio
async def test_connect_imap_success_flow() -> None:
    from app.services.mail import connect_imap

    acct = _make_account()
    mock_mb = MagicMock()
    folder_info = MagicMock()
    folder_info.delim = "."
    mock_mb.folder.list.return_value = [folder_info]
    mock_mb.client.capability.return_value = ("OK", [b"IMAP4rev1 MOVE IDLE"])

    call_count = 0

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # _connect
            return mock_mb
        return fn(*args, **kwargs)

    with (
        patch("app.services.mail.decrypt_credentials", return_value={"username": "u", "password": "p"}),
        patch("app.services.mail.get_settings") as mock_settings,
        patch("app.services.mail.asyncio.to_thread", side_effect=fake_to_thread),
    ):
        mock_settings.return_value.imap_timeout_seconds = 30
        conn = await connect_imap(acct)

    assert conn.separator == "."
    assert "MOVE" in conn.capabilities


@pytest.mark.asyncio
async def test_connect_imap_separator_detection_failure() -> None:
    from app.services.mail import connect_imap

    acct = _make_account()
    mock_mb = MagicMock()
    mock_mb.folder.list.side_effect = Exception("fail")
    mock_mb.client.capability.return_value = ("OK", [b"IMAP4rev1"])

    call_count = 0

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_mb
        return fn(*args, **kwargs)

    with (
        patch("app.services.mail.decrypt_credentials", return_value={"username": "u", "password": "p"}),
        patch("app.services.mail.get_settings") as mock_settings,
        patch("app.services.mail.asyncio.to_thread", side_effect=fake_to_thread),
    ):
        mock_settings.return_value.imap_timeout_seconds = 30
        conn = await connect_imap(acct)

    assert conn.separator == "/"


# ---------------------------------------------------------------------------
# imap_connection context manager
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_imap_connection_yields_and_cleans_up() -> None:
    acct = _make_account()
    fake_conn = _make_conn()

    with (
        patch("app.services.mail.connect_imap", new_callable=AsyncMock, return_value=fake_conn),
        patch("app.services.mail.safe_imap_logout", new_callable=AsyncMock) as mock_logout,
    ):
        async with imap_connection(acct) as conn:
            assert conn is fake_conn
        mock_logout.assert_awaited_once_with(fake_conn.mailbox)


@pytest.mark.asyncio
async def test_imap_connection_cleans_up_on_exception() -> None:
    acct = _make_account()
    fake_conn = _make_conn()

    with (
        patch("app.services.mail.connect_imap", new_callable=AsyncMock, return_value=fake_conn),
        patch("app.services.mail.safe_imap_logout", new_callable=AsyncMock) as mock_logout,
    ):
        with pytest.raises(RuntimeError):
            async with imap_connection(acct) as conn:
                raise RuntimeError("boom")
        mock_logout.assert_awaited_once()


# ---------------------------------------------------------------------------
# Folder cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_cached_folders_hit() -> None:
    mock_cache = AsyncMock()
    mock_cache.get.return_value = json.dumps(["INBOX", "Sent"])
    with patch("app.core.redis.get_cache_client", return_value=mock_cache):
        result = await get_cached_folders(uuid4())
    assert result == ["INBOX", "Sent"]


@pytest.mark.asyncio
async def test_get_cached_folders_miss() -> None:
    mock_cache = AsyncMock()
    mock_cache.get.return_value = None
    with patch("app.core.redis.get_cache_client", return_value=mock_cache):
        result = await get_cached_folders(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_folders_invalid_json() -> None:
    mock_cache = AsyncMock()
    mock_cache.get.return_value = "not-json{{"
    with patch("app.core.redis.get_cache_client", return_value=mock_cache):
        result = await get_cached_folders(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_set_cached_folders_stores_with_ttl() -> None:
    mock_cache = AsyncMock()
    with (
        patch("app.core.redis.get_cache_client", return_value=mock_cache),
        patch("app.services.mail.get_settings") as ms,
    ):
        ms.return_value.imap_folder_cache_ttl_seconds = 600
        aid = uuid4()
        await set_cached_folders(aid, ["INBOX"])
    mock_cache.setex.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalidate_folder_cache_deletes_key() -> None:
    mock_cache = AsyncMock()
    with patch("app.core.redis.get_cache_client", return_value=mock_cache):
        aid = uuid4()
        await invalidate_folder_cache(aid)
    mock_cache.delete.assert_awaited_once()


# ---------------------------------------------------------------------------
# resolve_folder
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_folder_first_match_found() -> None:
    conn = _make_conn()
    with patch("app.services.mail.list_folders", new_callable=AsyncMock, return_value=["INBOX", "Spam", "Junk"]):
        result = await resolve_folder(conn, ("Junk", "Spam"))
    assert result == "Junk"


@pytest.mark.asyncio
async def test_resolve_folder_none_found_returns_fallback() -> None:
    conn = _make_conn()
    with patch("app.services.mail.list_folders", new_callable=AsyncMock, return_value=["INBOX"]):
        result = await resolve_folder(conn, ("Junk", "Spam"), fallback="INBOX")
    assert result == "INBOX"


@pytest.mark.asyncio
async def test_resolve_folder_none_found_no_fallback() -> None:
    conn = _make_conn()
    with patch("app.services.mail.list_folders", new_callable=AsyncMock, return_value=["INBOX"]):
        result = await resolve_folder(conn, ("Junk",))
    assert result is None


@pytest.mark.asyncio
async def test_resolve_folder_create_if_missing() -> None:
    conn = _make_conn()
    with (
        patch("app.services.mail.list_folders", new_callable=AsyncMock, return_value=["INBOX"]),
        patch("app.services.mail.create_folder", new_callable=AsyncMock, return_value=True),
    ):
        result = await resolve_folder(conn, ("Junk",), create_if_missing=True)
    assert result == "Junk"


# ---------------------------------------------------------------------------
# update_account_sync_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_account_sync_status_success() -> None:
    db = AsyncMock()
    await update_account_sync_status(db, uuid4(), error=None)
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_account_sync_status_error() -> None:
    db = AsyncMock()
    await update_account_sync_status(db, uuid4(), error="timeout")
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# check_circuit_breaker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_check_circuit_breaker_under_limit_returns_false() -> None:
    db = AsyncMock()
    acct = MagicMock()
    acct.consecutive_errors = 3
    acct.is_paused = False
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = acct
    db.execute.return_value = result_mock

    result = await check_circuit_breaker(db, uuid4(), max_errors=10)
    assert result is False


@pytest.mark.asyncio
async def test_check_circuit_breaker_at_limit_trips() -> None:
    db = AsyncMock()
    acct = MagicMock()
    acct.consecutive_errors = 10
    acct.is_paused = False
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = acct
    db.execute.return_value = result_mock

    result = await check_circuit_breaker(db, uuid4(), max_errors=10)
    assert result is True
    assert acct.is_paused is True
    assert acct.paused_reason == "circuit_breaker"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_circuit_breaker_already_paused_returns_false() -> None:
    db = AsyncMock()
    acct = MagicMock()
    acct.consecutive_errors = 20
    acct.is_paused = True
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = acct
    db.execute.return_value = result_mock

    result = await check_circuit_breaker(db, uuid4(), max_errors=10)
    assert result is False


@pytest.mark.asyncio
async def test_check_circuit_breaker_no_account_returns_false() -> None:
    db = AsyncMock()
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = None
    db.execute.return_value = result_mock

    result = await check_circuit_breaker(db, uuid4())
    assert result is False


# ---------------------------------------------------------------------------
# store_flags
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_flags_success() -> None:
    conn = _make_conn()
    with patch("app.services.mail.asyncio.to_thread", new_callable=AsyncMock):
        result = await store_flags(conn, "123", ["\\Seen"])
    assert result is True


@pytest.mark.asyncio
async def test_store_flags_failure_returns_false() -> None:
    conn = _make_conn()
    with patch("app.services.mail.asyncio.to_thread", new_callable=AsyncMock, side_effect=Exception("fail")):
        result = await store_flags(conn, "123", ["\\Seen"])
    assert result is False


# ---------------------------------------------------------------------------
# _parse_copyuid
# ---------------------------------------------------------------------------

def test_parse_copyuid_from_client_response() -> None:
    client = MagicMock()
    client.response.return_value = ("OK", [b"1234567890 5 42"])
    result = _parse_copyuid([None], client)
    assert result == "42"


def test_parse_copyuid_from_data_fallback() -> None:
    result = _parse_copyuid([b"[COPYUID 123 5 99]"])
    assert result == "99"


def test_parse_copyuid_none_when_empty() -> None:
    result = _parse_copyuid([None])
    assert result is None


def test_parse_copyuid_client_exception_falls_through() -> None:
    client = MagicMock()
    client.response.side_effect = Exception("nope")
    result = _parse_copyuid([None], client)
    assert result is None


def test_parse_copyuid_client_returns_none_data() -> None:
    client = MagicMock()
    client.response.return_value = ("OK", [None])
    result = _parse_copyuid([None], client)
    assert result is None


# ---------------------------------------------------------------------------
# move_message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_message_with_move_capability() -> None:
    conn = _make_conn(capabilities=["IMAP4rev1", "MOVE"])
    conn.mailbox.client.uid.return_value = ("OK", [None])
    conn.mailbox.client.response.return_value = ("OK", [b"111 5 77"])

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await move_message(conn, "5", "Trash")
    assert result.success is True
    assert result.new_uid == "77"


@pytest.mark.asyncio
async def test_move_message_copy_delete_fallback() -> None:
    conn = _make_conn(capabilities=["IMAP4rev1"])
    conn.mailbox.client.uid.side_effect = [
        ("OK", [None]),  # COPY
        ("OK", [None]),  # STORE
    ]
    conn.mailbox.client.response.return_value = ("OK", [b"111 5 88"])
    conn.mailbox.client.expunge.return_value = None

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await move_message(conn, "5", "Trash")
    assert result.success is True
    assert result.new_uid == "88"


@pytest.mark.asyncio
async def test_move_message_copy_fails() -> None:
    conn = _make_conn(capabilities=[])
    conn.mailbox.client.uid.return_value = ("NO", [None])

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await move_message(conn, "5", "Trash")
    assert result.success is False


@pytest.mark.asyncio
async def test_move_message_delete_flag_fails() -> None:
    conn = _make_conn(capabilities=[])
    conn.mailbox.client.uid.side_effect = [
        ("OK", [None]),  # COPY OK
        ("NO", [None]),  # STORE fails
    ]
    conn.mailbox.client.response.return_value = ("OK", [None])

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await move_message(conn, "5", "Trash")
    assert result.success is False


@pytest.mark.asyncio
async def test_move_message_move_fails_falls_back_to_copy() -> None:
    conn = _make_conn(capabilities=["MOVE"])
    # First uid call (MOVE) raises, then COPY succeeds, then STORE succeeds
    conn.mailbox.client.uid.side_effect = [
        Exception("MOVE failed"),
        ("OK", [None]),  # COPY
        ("OK", [None]),  # STORE
    ]
    conn.mailbox.client.response.return_value = ("OK", [None])
    conn.mailbox.client.expunge.return_value = None

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await move_message(conn, "5", "Trash")
    assert result.success is True


# ---------------------------------------------------------------------------
# move_all_to_inbox
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_move_all_to_inbox_with_move_capability() -> None:
    conn = _make_conn(capabilities=["MOVE"])
    conn.mailbox.uids.return_value = ["1", "2", "3"]
    conn.mailbox.client.uid.return_value = ("OK", [None])

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        moved = await move_all_to_inbox(conn, "Spam")
    assert moved == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_move_all_to_inbox_empty_folder() -> None:
    conn = _make_conn()
    conn.mailbox.uids.return_value = []

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        moved = await move_all_to_inbox(conn, "Spam")
    assert moved == []


@pytest.mark.asyncio
async def test_move_all_to_inbox_select_fails() -> None:
    conn = _make_conn()

    async def fail_fn(fn, *a, **kw):
        raise Exception("select failed")

    with patch("app.services.mail.asyncio.to_thread", side_effect=fail_fn):
        moved = await move_all_to_inbox(conn, "Spam")
    assert moved == []


@pytest.mark.asyncio
async def test_move_all_to_inbox_copy_fallback() -> None:
    conn = _make_conn(capabilities=[])
    conn.mailbox.uids.return_value = ["10"]
    conn.mailbox.client.uid.side_effect = [
        ("OK", [None]),  # COPY
        ("OK", [None]),  # STORE
    ]
    conn.mailbox.client.expunge.return_value = None

    call_count = 0

    async def run_fn(fn, *a, **kw):
        nonlocal call_count
        call_count += 1
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        moved = await move_all_to_inbox(conn, "Spam")
    assert moved == ["10"]


@pytest.mark.asyncio
async def test_move_all_to_inbox_batch_copy_fails() -> None:
    conn = _make_conn(capabilities=[])
    conn.mailbox.uids.return_value = ["10"]
    conn.mailbox.client.uid.return_value = ("NO", [None])

    call_count = 0

    async def run_fn(fn, *a, **kw):
        nonlocal call_count
        call_count += 1
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        moved = await move_all_to_inbox(conn, "Spam")
    assert moved == []


# ---------------------------------------------------------------------------
# delete_folder / rename_folder
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_folder_success() -> None:
    conn = _make_conn()
    with patch("app.services.mail.asyncio.to_thread", new_callable=AsyncMock):
        result = await delete_folder(conn, "OldFolder")
    assert result is True


@pytest.mark.asyncio
async def test_delete_folder_failure() -> None:
    conn = _make_conn()
    with patch("app.services.mail.asyncio.to_thread", new_callable=AsyncMock, side_effect=Exception("fail")):
        result = await delete_folder(conn, "OldFolder")
    assert result is False


@pytest.mark.asyncio
async def test_rename_folder_success() -> None:
    conn = _make_conn()
    with patch("app.services.mail.asyncio.to_thread", new_callable=AsyncMock):
        result = await rename_folder(conn, "Old", "New")
    assert result is True


@pytest.mark.asyncio
async def test_rename_folder_failure() -> None:
    conn = _make_conn()
    with patch("app.services.mail.asyncio.to_thread", new_callable=AsyncMock, side_effect=Exception("fail")):
        result = await rename_folder(conn, "Old", "New")
    assert result is False


# ---------------------------------------------------------------------------
# get_folder_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_folder_status_success() -> None:
    conn = _make_conn()
    conn.mailbox.folder.status.return_value = {"MESSAGES": 42, "UNSEEN": 5}

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await get_folder_status(conn, "INBOX")
    assert result == {"messages": 42, "unseen": 5}


@pytest.mark.asyncio
async def test_get_folder_status_exception_returns_zeros() -> None:
    conn = _make_conn()
    with patch("app.services.mail.asyncio.to_thread", new_callable=AsyncMock, side_effect=Exception("fail")):
        result = await get_folder_status(conn, "INBOX")
    assert result == {"messages": 0, "unseen": 0}


# ---------------------------------------------------------------------------
# list_folders_with_counts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_folders_with_counts_success() -> None:
    conn = _make_conn()
    with (
        patch("app.services.mail.list_folders", new_callable=AsyncMock, return_value=["INBOX", "Sent"]),
        patch(
            "app.services.mail.get_folder_status",
            new_callable=AsyncMock,
            side_effect=[
                {"messages": 10, "unseen": 2},
                {"messages": 5, "unseen": 0},
            ],
        ),
    ):
        result = await list_folders_with_counts(conn)
    assert len(result) == 2
    assert result[0]["name"] == "INBOX"
    assert result[0]["messages"] == 10


@pytest.mark.asyncio
async def test_list_folders_with_counts_status_exception() -> None:
    conn = _make_conn()
    with (
        patch("app.services.mail.list_folders", new_callable=AsyncMock, return_value=["INBOX"]),
        patch("app.services.mail.get_folder_status", new_callable=AsyncMock, side_effect=Exception("fail")),
    ):
        result = await list_folders_with_counts(conn)
    assert result == [{"name": "INBOX", "messages": 0, "unseen": 0}]


# ---------------------------------------------------------------------------
# fetch_raw_message (additional to existing tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_raw_message_imap_fetch_failed() -> None:
    conn = _make_conn()
    conn.mailbox.client.uid.return_value = ("NO", [None])

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        with pytest.raises(ValueError, match="imap_fetch_failed"):
            await fetch_raw_message(conn, "5")


# ---------------------------------------------------------------------------
# search_uids
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_uids_unseen() -> None:
    conn = _make_conn()
    conn.mailbox.uids.return_value = ["1", "2"]
    conn.mailbox.folder.uid_validity = 12345

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        uids, uidval = await search_uids(conn, "INBOX", "UNSEEN")
    assert uids == ["1", "2"]


@pytest.mark.asyncio
async def test_search_uids_all() -> None:
    conn = _make_conn()
    conn.mailbox.uids.return_value = ["1"]

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        uids, _ = await search_uids(conn, "INBOX", "ALL")
    assert uids == ["1"]


@pytest.mark.asyncio
async def test_search_uids_custom_criteria() -> None:
    conn = _make_conn()
    conn.mailbox.uids.return_value = []

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        uids, _ = await search_uids(conn, "INBOX", "FLAGGED")
    assert uids == []


# ---------------------------------------------------------------------------
# fetch_envelopes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_envelopes_empty_uids() -> None:
    conn = _make_conn()
    result = await fetch_envelopes(conn, [])
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_envelopes_with_messages() -> None:
    conn = _make_conn()
    msg = MagicMock()
    msg.uid = "5"
    msg.subject = "Hello"
    msg.from_values = MagicMock()
    msg.from_values.name = "Alice"
    msg.from_values.email = "alice@example.com"
    msg.date = datetime(2024, 1, 1, tzinfo=UTC)
    conn.mailbox.fetch.return_value = [msg]

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await fetch_envelopes(conn, ["5"])
    assert "5" in result
    assert result["5"][0] == "Hello"


@pytest.mark.asyncio
async def test_fetch_envelopes_sender_no_name() -> None:
    conn = _make_conn()
    msg = MagicMock()
    msg.uid = "6"
    msg.subject = "Hi"
    msg.from_values = MagicMock()
    msg.from_values.name = ""
    msg.from_values.email = "bob@example.com"
    msg.date = None
    conn.mailbox.fetch.return_value = [msg]

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await fetch_envelopes(conn, ["6"])
    assert result["6"][1] == "bob@example.com"


@pytest.mark.asyncio
async def test_fetch_envelopes_exception_returns_defaults() -> None:
    conn = _make_conn()
    conn.mailbox.fetch.side_effect = Exception("fail")

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await fetch_envelopes(conn, ["7", "8"])
    assert result["7"] == (None, None, None)
    assert result["8"] == (None, None, None)


@pytest.mark.asyncio
async def test_fetch_envelopes_fills_missing_uids() -> None:
    conn = _make_conn()
    msg = MagicMock()
    msg.uid = "10"
    msg.subject = "X"
    msg.from_values = None
    msg.date = None
    conn.mailbox.fetch.return_value = [msg]

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await fetch_envelopes(conn, ["10", "11"])
    assert result["10"][1] is None  # no from_values
    assert result["11"] == (None, None, None)


# ---------------------------------------------------------------------------
# fetch_message_ids
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_message_ids_empty() -> None:
    result = await fetch_message_ids(_make_conn(), [])
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_message_ids_success() -> None:
    conn = _make_conn()
    msg = MagicMock()
    msg.uid = "5"
    msg.headers = {"message-id": ("<abc@example.com>",)}
    conn.mailbox.fetch.return_value = [msg]

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await fetch_message_ids(conn, ["5", "6"])
    assert result["5"] == "<abc@example.com>"
    assert result["6"] is None


@pytest.mark.asyncio
async def test_fetch_message_ids_exception() -> None:
    conn = _make_conn()
    conn.mailbox.fetch.side_effect = Exception("fail")

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with patch("app.services.mail.asyncio.to_thread", side_effect=run_fn):
        result = await fetch_message_ids(conn, ["5"])
    assert result["5"] is None


# ---------------------------------------------------------------------------
# relocate_mail_across_folders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_relocate_mail_empty_subject_returns_none() -> None:
    conn = _make_conn()
    result = await relocate_mail_across_folders(conn, "", "INBOX")
    assert result is None


@pytest.mark.asyncio
async def test_relocate_mail_found_in_other_folder() -> None:
    conn = _make_conn()
    conn.mailbox.uids.return_value = ["99"]

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with (
        patch("app.services.mail.list_folders", new_callable=AsyncMock, return_value=["INBOX", "Spam"]),
        patch("app.services.mail.asyncio.to_thread", side_effect=run_fn),
        patch("app.services.mail.fetch_raw_message", new_callable=AsyncMock, return_value=b"raw email"),
    ):
        result = await relocate_mail_across_folders(conn, "Test Subject", "INBOX")
    assert result is not None
    assert result.folder == "Spam"
    assert result.uid == "99"
    assert result.raw_bytes == b"raw email"


@pytest.mark.asyncio
async def test_relocate_mail_not_found() -> None:
    conn = _make_conn()
    conn.mailbox.uids.return_value = []

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with (
        patch("app.services.mail.list_folders", new_callable=AsyncMock, return_value=["INBOX", "Spam"]),
        patch("app.services.mail.asyncio.to_thread", side_effect=run_fn),
    ):
        result = await relocate_mail_across_folders(conn, "Missing", "INBOX")
    assert result is None


@pytest.mark.asyncio
async def test_relocate_mail_fetch_fails_returns_none() -> None:
    conn = _make_conn()
    conn.mailbox.uids.return_value = ["99"]

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with (
        patch("app.services.mail.list_folders", new_callable=AsyncMock, return_value=["INBOX", "Spam"]),
        patch("app.services.mail.asyncio.to_thread", side_effect=run_fn),
        patch("app.services.mail.fetch_raw_message", new_callable=AsyncMock, side_effect=ValueError("gone")),
    ):
        result = await relocate_mail_across_folders(conn, "Test", "INBOX")
    assert result is None


@pytest.mark.asyncio
async def test_relocate_mail_skips_excluded_folders() -> None:
    conn = _make_conn()
    conn.mailbox.uids.return_value = []

    async def run_fn(fn, *a, **kw):
        return fn(*a, **kw)

    with (
        patch("app.services.mail.list_folders", new_callable=AsyncMock, return_value=["INBOX", "Trash", "Spam"]),
        patch("app.services.mail.asyncio.to_thread", side_effect=run_fn),
    ):
        result = await relocate_mail_across_folders(
            conn, "Test", "INBOX", excluded_folders=["Trash", "Spam"]
        )
    assert result is None
