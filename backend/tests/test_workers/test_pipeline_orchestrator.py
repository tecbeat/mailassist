from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.pipeline_orchestrator import (
    EmailParseError,
    FetchResult,
    IMAPFetchError,
    IMAPFolderError,
    PipelineResult,
    PluginResultEntry,
    UIDNotFoundError,
    _cancel_key,
    _clear_pipeline_progress,
    _is_cancelled,
    _progress_key,
    _set_pipeline_progress,
    fetch_account,
)

# ---------------------------------------------------------------------------
# _progress_key / _cancel_key
# ---------------------------------------------------------------------------


class TestProgressKey:
    def test_default_folder(self) -> None:
        key = _progress_key("acc1", "uid1")
        assert key == "pipeline:progress:process_mail:acc1:uid1:INBOX"

    def test_custom_folder(self) -> None:
        key = _progress_key("acc1", "uid1", "Sent")
        assert key == "pipeline:progress:process_mail:acc1:uid1:Sent"


class TestCancelKey:
    def test_default_folder(self) -> None:
        key = _cancel_key("acc1", "uid1")
        assert key == "pipeline:cancel:process_mail:acc1:uid1:INBOX"

    def test_custom_folder(self) -> None:
        key = _cancel_key("acc1", "uid1", "Trash")
        assert key == "pipeline:cancel:process_mail:acc1:uid1:Trash"


# ---------------------------------------------------------------------------
# _is_cancelled
# ---------------------------------------------------------------------------


class TestIsCancelled:
    @pytest.mark.asyncio
    async def test_returns_true_when_key_exists(self) -> None:
        mock_client = AsyncMock()
        mock_client.exists = AsyncMock(return_value=1)
        with patch("app.core.redis.get_task_client", return_value=mock_client):
            result = await _is_cancelled("acc1", "uid1", "INBOX")
        assert result is True
        mock_client.exists.assert_awaited_once_with(_cancel_key("acc1", "uid1", "INBOX"))

    @pytest.mark.asyncio
    async def test_returns_false_when_key_missing(self) -> None:
        mock_client = AsyncMock()
        mock_client.exists = AsyncMock(return_value=0)
        with patch("app.core.redis.get_task_client", return_value=mock_client):
            result = await _is_cancelled("acc1", "uid1", "INBOX")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_exception(self) -> None:
        with patch(
            "app.core.redis.get_task_client",
            side_effect=RuntimeError("connection lost"),
        ):
            result = await _is_cancelled("acc1", "uid1", "INBOX")
        assert result is False


# ---------------------------------------------------------------------------
# _set_pipeline_progress
# ---------------------------------------------------------------------------


class TestSetPipelineProgress:
    @pytest.mark.asyncio
    async def test_writes_progress_to_valkey(self) -> None:
        mock_client = AsyncMock()
        mock_settings = MagicMock()
        mock_settings.pipeline_progress_ttl_seconds = 120
        with (
            patch("app.core.redis.get_task_client", return_value=mock_client),
            patch("app.workers.pipeline_orchestrator.get_settings", return_value=mock_settings),
        ):
            await _set_pipeline_progress(
                "acc1",
                "uid1",
                current_folder="INBOX",
                phase="ai_pipeline",
                current_plugin="spam_detection",
                current_plugin_display="Spam Detection",
                plugin_index=1,
                plugins_total=5,
            )
        mock_client.set.assert_awaited_once()
        call_args = mock_client.set.call_args
        assert call_args[0][0] == _progress_key("acc1", "uid1", "INBOX")
        assert call_args[1]["ex"] == 120

    @pytest.mark.asyncio
    async def test_includes_plugin_names_and_results(self) -> None:
        mock_client = AsyncMock()
        mock_settings = MagicMock()
        mock_settings.pipeline_progress_ttl_seconds = 60
        with (
            patch("app.core.redis.get_task_client", return_value=mock_client),
            patch("app.workers.pipeline_orchestrator.get_settings", return_value=mock_settings),
        ):
            await _set_pipeline_progress(
                "acc1",
                "uid1",
                phase="ai_pipeline",
                plugin_names=[{"name": "spam", "display_name": "Spam"}],
                plugin_results={"spam": {"status": "completed"}},
            )
        mock_client.set.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_swallows_exception(self) -> None:
        with patch(
            "app.core.redis.get_task_client",
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise
            await _set_pipeline_progress("acc1", "uid1", phase="ai_pipeline")


# ---------------------------------------------------------------------------
# _clear_pipeline_progress
# ---------------------------------------------------------------------------


class TestClearPipelineProgress:
    @pytest.mark.asyncio
    async def test_deletes_both_keys(self) -> None:
        mock_client = AsyncMock()
        with patch("app.core.redis.get_task_client", return_value=mock_client):
            await _clear_pipeline_progress("acc1", "uid1", "INBOX")
        assert mock_client.delete.await_count == 2
        mock_client.delete.assert_any_await(_progress_key("acc1", "uid1", "INBOX"))
        mock_client.delete.assert_any_await(_cancel_key("acc1", "uid1", "INBOX"))

    @pytest.mark.asyncio
    async def test_swallows_exception(self) -> None:
        with patch(
            "app.core.redis.get_task_client",
            side_effect=RuntimeError("boom"),
        ):
            await _clear_pipeline_progress("acc1", "uid1")


# ---------------------------------------------------------------------------
# fetch_account
# ---------------------------------------------------------------------------


class TestFetchAccount:
    @pytest.mark.asyncio
    async def test_returns_account_when_found(self) -> None:
        fake_account = MagicMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = fake_account
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        user_id = str(uuid4())
        account_id = str(uuid4())
        log = MagicMock()

        with patch("app.workers.pipeline_orchestrator.get_session_ctx", return_value=mock_ctx):
            result = await fetch_account(user_id, account_id, log)
        assert result is fake_account

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self) -> None:
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("app.workers.pipeline_orchestrator.get_session_ctx", return_value=mock_ctx):
            result = await fetch_account(str(uuid4()), str(uuid4()), MagicMock())
        assert result is None


# ---------------------------------------------------------------------------
# PluginResultEntry
# ---------------------------------------------------------------------------


class TestPluginResultEntry:
    def test_to_dict_minimal(self) -> None:
        entry = PluginResultEntry(status="completed", display_name="Spam Detection")
        d = entry.to_dict()
        assert d == {"status": "completed", "display_name": "Spam Detection"}
        assert "summary" not in d
        assert "details" not in d

    def test_to_dict_with_summary(self) -> None:
        entry = PluginResultEntry(status="completed", display_name="Summary", summary="Short text")
        d = entry.to_dict()
        assert d["summary"] == "Short text"
        assert "details" not in d

    def test_to_dict_with_details(self) -> None:
        entry = PluginResultEntry(status="failed", display_name="X", details={"key": "val"})
        d = entry.to_dict()
        assert d["details"] == {"key": "val"}
        assert "summary" not in d

    def test_to_dict_full(self) -> None:
        entry = PluginResultEntry(
            status="completed",
            display_name="Labels",
            summary="3 labels",
            details={"labels": ["a", "b", "c"]},
        )
        d = entry.to_dict()
        assert d == {
            "status": "completed",
            "display_name": "Labels",
            "summary": "3 labels",
            "details": {"labels": ["a", "b", "c"]},
        }


# ---------------------------------------------------------------------------
# PipelineResult
# ---------------------------------------------------------------------------


class TestPipelineResult:
    def test_defaults(self) -> None:
        r = PipelineResult()
        assert r.plugins_executed == []
        assert r.plugins_completed == []
        assert r.plugins_failed == []
        assert r.plugins_skipped == []
        assert r.plugin_results == {}
        assert r.approvals_created == 0
        assert r.auto_actions == []
        assert r.completion_reason is None
        assert r.transient_reenqueue_reason is None
        assert r.current_folder == "INBOX"
        assert r.provider_error is False
        assert r.failed_provider_id is None
        assert r.mail_id is None

    def test_independent_defaults(self) -> None:
        """Each instance gets its own list/dict (no shared mutable defaults)."""
        r1 = PipelineResult()
        r2 = PipelineResult()
        r1.plugins_executed.append("x")
        assert r2.plugins_executed == []


# ---------------------------------------------------------------------------
# FetchResult
# ---------------------------------------------------------------------------


class TestFetchResult:
    def test_defaults(self) -> None:
        fr = FetchResult(raw_bytes=b"data", imap_folders=["INBOX"], folder_separator="/")
        assert fr.relocated is False
        assert fr.new_folder is None
        assert fr.new_uid is None

    def test_relocated(self) -> None:
        fr = FetchResult(
            raw_bytes=b"x",
            imap_folders=[],
            folder_separator=".",
            relocated=True,
            new_folder="Archive",
            new_uid="42",
        )
        assert fr.relocated is True
        assert fr.new_folder == "Archive"
        assert fr.new_uid == "42"


# ---------------------------------------------------------------------------
# Exception classes
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_imap_fetch_error(self) -> None:
        e = IMAPFetchError("fetch failed")
        assert str(e) == "fetch failed"

    def test_imap_folder_error(self) -> None:
        e = IMAPFolderError("folder gone")
        assert str(e) == "folder gone"
        assert isinstance(e, Exception)

    def test_uid_not_found_error(self) -> None:
        e = UIDNotFoundError("uid 123 missing")
        assert "123" in str(e)

    def test_email_parse_error(self) -> None:
        e = EmailParseError("bad bytes")
        assert str(e) == "bad bytes"
        assert isinstance(e, Exception)
