"""Coverage tests for app.workers.health.

Covers: write_cron_last_run, write_heartbeat, reset_orphaned_jobs,
cleanup_stale_running_jobs, recover_circuit_broken_providers,
log_queue_depth, timed_operation, recover_paused_providers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


# ---------------------------------------------------------------------------
# write_cron_last_run
# ---------------------------------------------------------------------------


class TestWriteCronLastRun:
    @pytest.mark.asyncio
    async def test_write_cron_last_run_success(self):
        from app.workers.health import write_cron_last_run

        mock_cache = AsyncMock()
        with (
            patch("app.workers.health.get_cache_client", return_value=mock_cache),
            patch("app.workers.health.get_settings") as mock_settings,
        ):
            mock_settings.return_value.cron_last_run_ttl_seconds = 3600
            await write_cron_last_run("health_check")

        mock_cache.set.assert_awaited_once()
        call_args = mock_cache.set.call_args
        assert call_args[0][0] == "cron:last_run:health_check"
        assert call_args[1]["ex"] == 3600

    @pytest.mark.asyncio
    async def test_write_cron_last_run_exception_swallowed(self):
        from app.workers.health import write_cron_last_run

        with patch("app.workers.health.get_cache_client", side_effect=RuntimeError("down")):
            await write_cron_last_run("boom")  # should not raise


# ---------------------------------------------------------------------------
# write_heartbeat
# ---------------------------------------------------------------------------


class TestWriteHeartbeat:
    @pytest.mark.asyncio
    async def test_write_heartbeat_success(self):
        from app.workers.health import write_heartbeat

        mock_cache = AsyncMock()
        with (
            patch("app.workers.health.get_cache_client", return_value=mock_cache),
            patch("app.workers.health.get_settings") as mock_settings,
        ):
            mock_settings.return_value.heartbeat_ttl_seconds = 120
            await write_heartbeat("worker-99")

        mock_cache.set.assert_awaited_once()
        assert "worker:heartbeat:worker-99" in mock_cache.set.call_args[0][0]

    @pytest.mark.asyncio
    async def test_write_heartbeat_default_worker_id(self):
        from app.workers.health import write_heartbeat

        mock_cache = AsyncMock()
        with (
            patch("app.workers.health.get_cache_client", return_value=mock_cache),
            patch("app.workers.health.get_settings") as mock_settings,
        ):
            mock_settings.return_value.heartbeat_ttl_seconds = 60
            await write_heartbeat()

        assert "arq-worker-1" in mock_cache.set.call_args[0][0]

    @pytest.mark.asyncio
    async def test_write_heartbeat_exception_swallowed(self):
        from app.workers.health import write_heartbeat

        with patch("app.workers.health.get_cache_client", side_effect=RuntimeError):
            await write_heartbeat()


# ---------------------------------------------------------------------------
# reset_orphaned_jobs
# ---------------------------------------------------------------------------


class TestResetOrphanedJobs:
    @pytest.mark.asyncio
    async def test_reset_orphaned_jobs_with_results(self):
        from app.workers.health import reset_orphaned_jobs

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [uuid4(), uuid4()]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        mock_task = AsyncMock()
        mock_task.keys = AsyncMock(return_value=["arq:result:process_mail:1"])
        mock_task.delete = AsyncMock()

        with (
            patch("app.workers.health.get_session_ctx", fake_session),
            patch("app.workers.health.get_task_client", return_value=mock_task),
        ):
            await reset_orphaned_jobs()

        mock_db.commit.assert_awaited_once()
        mock_task.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reset_orphaned_jobs_no_results(self):
        from app.workers.health import reset_orphaned_jobs

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        mock_task = AsyncMock()
        mock_task.keys = AsyncMock(return_value=[])

        with (
            patch("app.workers.health.get_session_ctx", fake_session),
            patch("app.workers.health.get_task_client", return_value=mock_task),
        ):
            await reset_orphaned_jobs()

        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reset_orphaned_jobs_stale_key_clear_fails(self):
        from app.workers.health import reset_orphaned_jobs

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with (
            patch("app.workers.health.get_session_ctx", fake_session),
            patch("app.workers.health.get_task_client", side_effect=RuntimeError("redis down")),
        ):
            await reset_orphaned_jobs()  # should not raise


# ---------------------------------------------------------------------------
# cleanup_stale_running_jobs
# ---------------------------------------------------------------------------


class TestCleanupStaleRunningJobs:
    @pytest.mark.asyncio
    async def test_cleanup_stale_with_stale_ids(self):
        from app.workers.health import cleanup_stale_running_jobs

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [uuid4()]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with (
            patch("app.workers.health.get_session_ctx", fake_session),
            patch("app.workers.health.get_settings") as mock_s,
        ):
            mock_s.return_value.stale_job_threshold_seconds = 600
            await cleanup_stale_running_jobs()

        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cleanup_stale_no_stale_ids(self):
        from app.workers.health import cleanup_stale_running_jobs

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with (
            patch("app.workers.health.get_session_ctx", fake_session),
            patch("app.workers.health.get_settings") as mock_s,
        ):
            mock_s.return_value.stale_job_threshold_seconds = 600
            await cleanup_stale_running_jobs()

        mock_db.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# recover_circuit_broken_providers
# ---------------------------------------------------------------------------


class TestRecoverCircuitBrokenProviders:
    @pytest.mark.asyncio
    async def test_recover_no_providers_returns_early(self):
        from app.workers.health import recover_circuit_broken_providers

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with (
            patch("app.workers.health.get_session_ctx", fake_session),
            patch("app.workers.health.get_settings") as mock_s,
        ):
            mock_s.return_value.provider_recovery_cooldown_seconds = 300
            await recover_circuit_broken_providers()

        mock_db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_recover_providers_unpaused_and_event_emitted(self):
        from app.workers.health import recover_circuit_broken_providers

        provider = MagicMock()
        provider.id = uuid4()
        provider.user_id = uuid4()
        provider.name = "test"
        provider.is_paused = True
        provider.paused_reason = "circuit_breaker"
        provider.last_error_at = datetime.now(UTC) - timedelta(hours=1)
        provider.consecutive_errors = 5

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [provider]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        mock_bus = AsyncMock()

        with (
            patch("app.workers.health.get_session_ctx", fake_session),
            patch("app.workers.health.get_settings") as mock_s,
            patch("app.workers.health.get_event_bus", return_value=mock_bus),
        ):
            mock_s.return_value.provider_recovery_cooldown_seconds = 300
            await recover_circuit_broken_providers()

        assert provider.is_paused is False
        assert provider.paused_reason is None
        assert provider.paused_at is None
        assert provider.consecutive_errors == 0
        mock_db.commit.assert_awaited_once()
        mock_bus.emit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recover_providers_event_emit_failure_swallowed(self):
        from app.workers.health import recover_circuit_broken_providers

        provider = MagicMock()
        provider.id = uuid4()
        provider.user_id = uuid4()
        provider.name = "broken"
        provider.is_paused = True
        provider.last_error_at = datetime.now(UTC) - timedelta(hours=1)

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [provider]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        mock_bus = AsyncMock()
        mock_bus.emit = AsyncMock(side_effect=RuntimeError("bus error"))

        with (
            patch("app.workers.health.get_session_ctx", fake_session),
            patch("app.workers.health.get_settings") as mock_s,
            patch("app.workers.health.get_event_bus", return_value=mock_bus),
        ):
            mock_s.return_value.provider_recovery_cooldown_seconds = 300
            await recover_circuit_broken_providers()  # should not raise


# ---------------------------------------------------------------------------
# log_queue_depth
# ---------------------------------------------------------------------------


class TestLogQueueDepth:
    @pytest.mark.asyncio
    async def test_log_queue_depth_zset(self):
        from app.workers.health import log_queue_depth

        mock_client = AsyncMock()
        mock_client.type = AsyncMock(return_value="zset")
        mock_client.zcard = AsyncMock(return_value=5)
        mock_client.keys = AsyncMock(side_effect=[["k1"], ["r1", "r2"]])

        with patch("app.workers.health.get_task_client", return_value=mock_client):
            await log_queue_depth()

        mock_client.zcard.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_log_queue_depth_not_zset(self):
        from app.workers.health import log_queue_depth

        mock_client = AsyncMock()
        mock_client.type = AsyncMock(return_value="none")
        mock_client.keys = AsyncMock(return_value=[])

        with patch("app.workers.health.get_task_client", return_value=mock_client):
            await log_queue_depth()

        mock_client.zcard.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_log_queue_depth_exception_swallowed(self):
        from app.workers.health import log_queue_depth

        with patch("app.workers.health.get_task_client", side_effect=RuntimeError):
            await log_queue_depth()


# ---------------------------------------------------------------------------
# timed_operation
# ---------------------------------------------------------------------------


class TestTimedOperation:
    @pytest.mark.asyncio
    async def test_timed_operation_success(self):
        from app.workers.health import timed_operation

        async with timed_operation("test_op", foo="bar"):
            pass  # no error

    @pytest.mark.asyncio
    async def test_timed_operation_failure_reraises(self):
        from app.workers.health import timed_operation

        with pytest.raises(ValueError, match="boom"):
            async with timed_operation("failing_op"):
                raise ValueError("boom")


# ---------------------------------------------------------------------------
# recover_paused_providers (top-level dispatcher)
# ---------------------------------------------------------------------------


class TestRecoverPausedProviders:
    @pytest.mark.asyncio
    async def test_recover_paused_providers_calls_both(self):
        from app.workers.health import recover_paused_providers

        with (
            patch("app.workers.health._recover_paused_accounts", new_callable=AsyncMock) as mock_accts,
            patch("app.workers.health._recover_paused_ai_providers", new_callable=AsyncMock) as mock_provs,
            patch("app.workers.health.get_settings") as mock_s,
        ):
            mock_s.return_value.imap_pause_cooldown_seconds = 300
            mock_s.return_value.ai_pause_cooldown_seconds = 120
            await recover_paused_providers()

        mock_accts.assert_awaited_once()
        mock_provs.assert_awaited_once()


# ---------------------------------------------------------------------------
# _recover_paused_accounts — event emit failure
# ---------------------------------------------------------------------------


class TestRecoverPausedAccountsEventFailure:
    @pytest.mark.asyncio
    async def test_account_event_emit_failure_swallowed(self):
        from app.workers.health import _recover_paused_accounts

        now = datetime.now(UTC)
        account = MagicMock()
        account.id = uuid4()
        account.user_id = uuid4()
        account.email_address = "u@e.com"
        account.is_paused = True
        account.paused_at = now - timedelta(minutes=10)
        account.paused_reason = "imap_error"
        account.consecutive_errors = 3

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [account]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        mock_bus = AsyncMock()
        mock_bus.emit = AsyncMock(side_effect=RuntimeError("emit failed"))

        with (
            patch("app.workers.health.get_session_ctx", fake_session),
            patch("app.workers.health.probe_imap_account", AsyncMock(return_value=True)),
            patch("app.workers.health.get_event_bus", return_value=mock_bus),
        ):
            await _recover_paused_accounts(now, cooldown_seconds=300)

        assert account.is_paused is False


# ---------------------------------------------------------------------------
# _recover_paused_ai_providers — no providers
# ---------------------------------------------------------------------------


class TestRecoverPausedAiProvidersEmpty:
    @pytest.mark.asyncio
    async def test_no_providers_returns_early(self):
        from app.workers.health import _recover_paused_ai_providers

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with patch("app.workers.health.get_session_ctx", fake_session):
            await _recover_paused_ai_providers(datetime.now(UTC), cooldown_seconds=120)

        mock_db.commit.assert_not_awaited()


class TestRecoverPausedAiProvidersEventFailure:
    @pytest.mark.asyncio
    async def test_provider_event_emit_failure_swallowed(self):
        from app.workers.health import _recover_paused_ai_providers

        now = datetime.now(UTC)
        provider = MagicMock()
        provider.id = uuid4()
        provider.user_id = uuid4()
        provider.name = "prov"
        provider.is_paused = True
        provider.paused_at = now - timedelta(minutes=10)
        provider.paused_reason = "llm_error"
        provider.consecutive_errors = 3

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [provider]
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        mock_bus = AsyncMock()
        mock_bus.emit = AsyncMock(side_effect=RuntimeError("emit failed"))

        with (
            patch("app.workers.health.get_session_ctx", fake_session),
            patch("app.workers.health.probe_ai_provider", AsyncMock(return_value=True)),
            patch("app.workers.health.get_event_bus", return_value=mock_bus),
        ):
            await _recover_paused_ai_providers(now, cooldown_seconds=120)

        assert provider.is_paused is False


# ---------------------------------------------------------------------------
# _recover_paused_accounts — no accounts
# ---------------------------------------------------------------------------


class TestRecoverPausedAccountsEmpty:
    @pytest.mark.asyncio
    async def test_no_accounts_returns_early(self):
        from app.workers.health import _recover_paused_accounts

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        @asynccontextmanager
        async def fake_session():
            yield mock_db

        with patch("app.workers.health.get_session_ctx", fake_session):
            await _recover_paused_accounts(datetime.now(UTC), cooldown_seconds=300)

        mock_db.commit.assert_not_awaited()
