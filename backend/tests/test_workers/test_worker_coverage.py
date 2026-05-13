"""Tests for app.workers.worker — task definitions and lifecycle hooks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# get_redis_settings
# ---------------------------------------------------------------------------


@patch("app.workers.worker.get_settings")
def test_get_redis_settings_parses_url_returns_redis_settings(mock_settings: MagicMock) -> None:
    mock_settings.return_value.valkey_url = "redis://:secret@myhost:6380/2"
    from app.workers.worker import get_redis_settings

    rs = get_redis_settings()
    assert rs.host == "myhost"
    assert rs.port == 6380
    assert rs.password == "secret"
    assert rs.database == 2


@patch("app.workers.worker.get_settings")
def test_get_redis_settings_defaults_when_minimal_url(mock_settings: MagicMock) -> None:
    mock_settings.return_value.valkey_url = "redis://localhost/"
    from app.workers.worker import get_redis_settings

    rs = get_redis_settings()
    assert rs.host == "localhost"
    assert rs.port == 6379
    assert rs.database == 0
    assert rs.password is None


# ---------------------------------------------------------------------------
# startup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("app.workers.worker.get_settings")
@patch("app.workers.worker._configure_structlog")
async def test_startup_initialises_all_systems_succeeds(
    mock_structlog: MagicMock,
    mock_settings: MagicMock,
) -> None:
    settings = MagicMock()
    settings.app_secret_key = "k"
    settings.app_secret_key_old = None
    mock_settings.return_value = settings

    ctx: dict = {"redis": AsyncMock()}

    with (
        patch("app.workers.worker.init_db") as m_db,
        patch("app.workers.worker.init_valkey") as m_valkey,
        patch("app.workers.worker.init_encryption") as m_enc,
        patch("app.workers.worker.init_event_bus") as m_bus,
        patch("app.workers.worker.init_template_engine") as m_tpl,
        patch("app.workers.worker.init_plugin_registry") as m_plug,
        patch("app.workers.worker.write_heartbeat", new_callable=AsyncMock) as m_hb,
        patch("app.workers.worker.start_idle_manager", new_callable=AsyncMock) as m_idle,
        patch("app.workers.worker.reset_orphaned_jobs", new_callable=AsyncMock) as m_orphan,
        patch("app.workers.worker.schedule_now", new_callable=AsyncMock) as m_sched,
        patch("app.workers.worker.get_event_bus") as m_get_bus,
        patch("app.workers.worker.register_notification_handlers"),
    ):
        m_get_bus.return_value = MagicMock()
        from app.workers.worker import startup

        await startup(ctx)

        m_db.assert_called_once()
        m_valkey.assert_called_once()
        m_enc.assert_called_once()
        m_bus.assert_called_once()
        m_tpl.assert_called_once()
        m_plug.assert_called_once()
        m_hb.assert_awaited_once()
        m_idle.assert_awaited_once()
        m_orphan.assert_awaited_once()
        m_sched.assert_awaited_once_with(ctx["redis"])


@pytest.mark.asyncio
@patch("app.workers.worker.get_settings")
@patch("app.workers.worker._configure_structlog")
async def test_startup_idle_manager_retries_on_failure(
    mock_structlog: MagicMock,
    mock_settings: MagicMock,
) -> None:
    settings = MagicMock()
    settings.app_secret_key = "k"
    settings.app_secret_key_old = None
    mock_settings.return_value = settings

    ctx: dict = {"redis": AsyncMock()}

    with (
        patch("app.workers.worker.init_db"),
        patch("app.workers.worker.init_valkey"),
        patch("app.workers.worker.init_encryption"),
        patch("app.workers.worker.init_event_bus"),
        patch("app.workers.worker.init_template_engine"),
        patch("app.workers.worker.init_plugin_registry"),
        patch("app.workers.worker.write_heartbeat", new_callable=AsyncMock),
        patch(
            "app.workers.worker.start_idle_manager",
            new_callable=AsyncMock,
            side_effect=[RuntimeError("not ready"), None],
        ) as m_idle,
        patch("app.workers.worker.reset_orphaned_jobs", new_callable=AsyncMock),
        patch("app.workers.worker.schedule_now", new_callable=AsyncMock),
        patch("app.workers.worker.get_event_bus", return_value=MagicMock()),
        patch("app.workers.worker.register_notification_handlers"),
        patch("app.workers.worker._aio") as m_aio,
    ):
        m_aio.sleep = AsyncMock()
        from app.workers.worker import startup

        await startup(ctx)

        assert m_idle.await_count == 2


@pytest.mark.asyncio
@patch("app.workers.worker.get_settings")
@patch("app.workers.worker._configure_structlog")
async def test_startup_schedule_now_failure_does_not_raise(
    mock_structlog: MagicMock,
    mock_settings: MagicMock,
) -> None:
    settings = MagicMock()
    settings.app_secret_key = "k"
    settings.app_secret_key_old = None
    mock_settings.return_value = settings

    ctx: dict = {"redis": AsyncMock()}

    with (
        patch("app.workers.worker.init_db"),
        patch("app.workers.worker.init_valkey"),
        patch("app.workers.worker.init_encryption"),
        patch("app.workers.worker.init_event_bus"),
        patch("app.workers.worker.init_template_engine"),
        patch("app.workers.worker.init_plugin_registry"),
        patch("app.workers.worker.write_heartbeat", new_callable=AsyncMock),
        patch("app.workers.worker.start_idle_manager", new_callable=AsyncMock),
        patch("app.workers.worker.reset_orphaned_jobs", new_callable=AsyncMock),
        patch(
            "app.workers.worker.schedule_now",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ),
        patch("app.workers.worker.get_event_bus", return_value=MagicMock()),
        patch("app.workers.worker.register_notification_handlers"),
    ):
        from app.workers.worker import startup

        # Should not raise
        await startup(ctx)


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_stops_idle_and_closes_resources() -> None:
    ctx: dict = {}
    with (
        patch("app.workers.worker.stop_all_idle", new_callable=AsyncMock) as m_idle,
        patch("app.workers.worker.close_db", new_callable=AsyncMock) as m_db,
        patch("app.workers.worker.close_valkey", new_callable=AsyncMock) as m_valkey,
    ):
        from app.workers.worker import shutdown

        await shutdown(ctx)

        m_idle.assert_awaited_once()
        m_db.assert_awaited_once()
        m_valkey.assert_awaited_once()


# ---------------------------------------------------------------------------
# Delegating task functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_poll_mail_accounts_delegates_and_writes_cron() -> None:
    ctx: dict = {}
    with (
        patch("app.workers.worker._poll", new_callable=AsyncMock) as m_poll,
        patch("app.workers.worker.write_cron_last_run", new_callable=AsyncMock) as m_cron,
    ):
        from app.workers.worker import poll_mail_accounts

        await poll_mail_accounts(ctx)
        m_poll.assert_awaited_once_with(ctx)
        m_cron.assert_awaited_once_with("poll_mail_accounts")


@pytest.mark.asyncio
async def test_poll_single_account_delegates() -> None:
    ctx: dict = {}
    with patch(
        "app.workers.worker._poll_single", new_callable=AsyncMock
    ) as m:
        from app.workers.worker import poll_single_account

        await poll_single_account(ctx, "u1", "a1")
        m.assert_awaited_once_with(ctx, "u1", "a1")


@pytest.mark.asyncio
async def test_process_mail_delegates_and_enqueues_scheduler() -> None:
    mock_redis = AsyncMock()
    ctx: dict = {"redis": mock_redis}
    with patch("app.workers.worker._process", new_callable=AsyncMock) as m:
        from app.workers.worker import process_mail

        await process_mail(ctx, "u1", "a1", "uid1", "INBOX", None)
        m.assert_awaited_once()
        mock_redis.enqueue_job.assert_awaited_once_with("schedule_pending_mails")


@pytest.mark.asyncio
async def test_process_mail_enqueue_failure_does_not_raise() -> None:
    mock_redis = AsyncMock()
    mock_redis.enqueue_job = AsyncMock(side_effect=RuntimeError("fail"))
    ctx: dict = {"redis": mock_redis}
    with patch("app.workers.worker._process", new_callable=AsyncMock):
        from app.workers.worker import process_mail

        await process_mail(ctx, "u1", "a1", "uid1")


@pytest.mark.asyncio
async def test_sync_contacts_delegates_and_writes_cron() -> None:
    ctx: dict = {}
    with (
        patch("app.workers.worker.sync_all_contacts", new_callable=AsyncMock) as m,
        patch("app.workers.worker.write_cron_last_run", new_callable=AsyncMock) as m_cron,
    ):
        from app.workers.worker import sync_contacts

        await sync_contacts(ctx)
        m.assert_awaited_once_with(ctx)
        m_cron.assert_awaited_once_with("sync_contacts")


@pytest.mark.asyncio
async def test_cleanup_drafts_delegates_and_writes_cron() -> None:
    ctx: dict = {}
    with (
        patch("app.workers.worker.cleanup_all_drafts", new_callable=AsyncMock) as m,
        patch("app.workers.worker.write_cron_last_run", new_callable=AsyncMock) as m_cron,
    ):
        from app.workers.worker import cleanup_drafts

        await cleanup_drafts(ctx)
        m.assert_awaited_once_with(ctx)
        m_cron.assert_awaited_once_with("cleanup_drafts")


@pytest.mark.asyncio
async def test_schedule_pending_mails_delegates_and_writes_cron() -> None:
    ctx: dict = {}
    with (
        patch("app.workers.worker._schedule", new_callable=AsyncMock) as m,
        patch("app.workers.worker.write_cron_last_run", new_callable=AsyncMock) as m_cron,
    ):
        from app.workers.worker import schedule_pending_mails

        await schedule_pending_mails(ctx)
        m.assert_awaited_once_with(ctx)
        m_cron.assert_awaited_once_with("schedule_pending_mails")
