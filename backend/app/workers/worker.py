"""ARQ worker configuration and task definitions.

Provides the WorkerSettings class consumed by `arq` CLI.
Defines periodic tasks for mail polling, contact sync, and draft cleanup.
"""

from arq import cron, func
from arq.connections import RedisSettings

from app.core.config import get_settings


def get_redis_settings() -> RedisSettings:
    """Parse Valkey URL into ARQ RedisSettings."""
    settings = get_settings()
    url = settings.valkey_url
    # Parse redis://:password@host:port/db
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        password=parsed.password,
        database=int(parsed.path.lstrip("/") or "0"),
    )


async def startup(ctx: dict) -> None:
    """Worker startup: initialize shared resources."""
    # Configure structlog stdlib bridge so ARQ and third-party logs are formatted.
    from app.main import _configure_structlog
    _configure_structlog()

    import structlog
    logger = structlog.get_logger()
    logger.info("worker_starting")

    settings = get_settings()

    from app.core.database import init_db
    from app.core.security import init_encryption
    from app.core.redis import init_valkey
    from app.core.events import init_event_bus
    from app.core.templating import init_template_engine
    from app.plugins.registry import init_plugin_registry

    init_db(settings)
    init_valkey(settings)
    init_encryption(settings.app_secret_key, settings.app_secret_key_old)
    init_event_bus()
    init_template_engine()
    init_plugin_registry()

    # Write initial heartbeat so monitors detect the worker immediately
    from app.workers.health import write_heartbeat
    await write_heartbeat()

    # Start IDLE monitoring for all eligible mail accounts.
    # Retry with backoff: if the worker starts before DB migrations complete,
    # the mail_accounts table may not exist yet (ProgrammingError).
    import asyncio as _aio
    from app.workers.idle_monitor import start_idle_manager

    for _attempt in range(1, 6):
        try:
            await start_idle_manager()
            break
        except Exception:
            if _attempt == 5:
                logger.error("start_idle_manager_failed_after_retries")
                break
            delay = 2 ** _attempt  # 2, 4, 8, 16 s
            logger.warning(
                "start_idle_manager_retry",
                attempt=_attempt,
                delay_s=delay,
            )
            await _aio.sleep(delay)

    # Register event handlers for immediate scheduling on reactivation
    from app.core.events import (
        AccountReactivatedEvent,
        ProviderReactivatedEvent,
        get_event_bus,
    )
    from app.workers.scheduler import schedule_now

    bus = get_event_bus()

    async def _on_reactivation(event) -> None:
        """Trigger immediate scheduling when account/provider is reactivated."""
        from arq import ArqRedis
        from app.core.redis import get_task_client
        client = get_task_client()
        # get_task_client returns a redis.asyncio.Redis; ARQ needs its pool
        # We use the worker's own redis from ctx if possible, but during
        # event handling we may not have ctx, so we create a lightweight
        # ArqRedis from the existing Valkey connection.
        redis_settings = get_redis_settings()
        from arq import create_pool
        pool = await create_pool(redis_settings)
        try:
            await schedule_now(pool)
        finally:
            await pool.close()

    bus.subscribe(AccountReactivatedEvent, _on_reactivation)
    bus.subscribe(ProviderReactivatedEvent, _on_reactivation)

    # Register notification handlers so send_notification() is actually
    # called when the AI pipeline completes.
    from app.workers.notification_handler import register_notification_handlers
    register_notification_handlers()

    # Reset mails orphaned by the previous worker process (stuck in
    # PROCESSING/QUEUED with no ARQ job behind them) so the scheduler
    # can re-dispatch them immediately.
    from app.workers.health import reset_orphaned_jobs
    await reset_orphaned_jobs()

    # Trigger the scheduler right away so QUEUED mails are dispatched
    # without waiting for the first cron tick (up to 60 s).
    try:
        await schedule_now(ctx["redis"])
    except Exception:
        logger.warning("startup_schedule_now_failed", exc_info=True)

    logger.info("worker_started")


async def shutdown(ctx: dict) -> None:
    """Worker shutdown: cleanup resources."""
    import structlog
    logger = structlog.get_logger()
    logger.info("worker_shutting_down")

    # Stop all IDLE monitoring tasks before closing connections
    from app.workers.idle_monitor import stop_all_idle
    await stop_all_idle()

    from app.core.database import close_db
    from app.core.redis import close_valkey

    await close_db()
    await close_valkey()
    logger.info("worker_stopped")


# Task functions delegate to actual implementations
async def poll_mail_accounts(ctx: dict) -> None:
    """Poll all active mail accounts for new messages."""
    from app.workers.mail_poller import poll_mail_accounts as _poll
    await _poll(ctx)
    from app.workers.health import write_cron_last_run
    await write_cron_last_run("poll_mail_accounts")


async def poll_single_account(ctx: dict, user_id: str, account_id: str) -> None:
    """Poll a single mail account for new messages (manual trigger)."""
    from app.workers.mail_poller import poll_single_account as _poll_single
    await _poll_single(ctx, user_id, account_id)


async def process_mail(
    ctx: dict,
    user_id: str,
    account_id: str,
    mail_uid: str,
    current_folder: str = "INBOX",
    skip_plugins: list[str] | None = None,
) -> None:
    """Process a single email through the AI pipeline."""
    from app.workers.mail_processor import process_mail as _process
    try:
        await _process(
            ctx, user_id, account_id, mail_uid,
            current_folder=current_folder, skip_plugins=skip_plugins,
        )
    finally:
        # Trigger the scheduler so the next queued mail is dispatched
        # without waiting for the 1-minute cron tick — even when the
        # pipeline raised an unhandled exception.
        #
        # We enqueue ``schedule_pending_mails`` rather than calling
        # ``schedule_now`` inline for two reasons:
        #
        # 1. The current ARQ slot is still occupied while this ``finally``
        #    runs.  An inline ``schedule_now`` may observe the just-finished
        #    mail still as ``PROCESSING`` (depending on session/commit
        #    timing) and decide there is no free capacity, leaving the
        #    next mail stranded until the cron ticks.
        # 2. The enqueued path goes through ``schedule_pending_mails``,
        #    which also runs ``_reset_stale_processing`` — the same
        #    safety net the cron path provides.
        #
        # No fixed ``_job_id`` is used: ARQ's default ``keep_result``
        # would dedup further finishers for ~12 min, defeating the
        # purpose.  ``schedule_pending_mails`` is idempotent (QUEUED
        # rows are picked with ``FOR UPDATE SKIP LOCKED``), so multiple
        # parallel runs are safe.
        import structlog
        _log = structlog.get_logger()
        try:
            await ctx["redis"].enqueue_job("schedule_pending_mails")
        except Exception:
            # Best-effort; the 1-minute cron will catch up.  Log so the
            # failure is visible instead of silently swallowed.
            _log.warning(
                "post_process_mail_schedule_enqueue_failed",
                exc_info=True,
            )


async def sync_contacts(ctx: dict) -> None:
    """Sync contacts from CardDAV for all active configurations."""
    from app.workers.contact_sync import sync_all_contacts
    await sync_all_contacts(ctx)
    from app.workers.health import write_cron_last_run
    await write_cron_last_run("sync_contacts")


async def cleanup_drafts(ctx: dict) -> None:
    """Clean up stale AI-generated drafts."""
    from app.workers.draft_monitor import cleanup_all_drafts
    await cleanup_all_drafts(ctx)
    from app.workers.health import write_cron_last_run
    await write_cron_last_run("cleanup_drafts")


async def schedule_pending_mails(ctx: dict) -> None:
    """Schedule pending tracked emails into the ARQ processing queue."""
    from app.workers.scheduler import schedule_pending_mails as _schedule
    await _schedule(ctx)
    from app.workers.health import write_cron_last_run
    await write_cron_last_run("schedule_pending_mails")


async def worker_health_check(ctx: dict) -> None:
    """Periodic health check: heartbeat, stale job cleanup, queue metrics, IDLE health."""
    from app.workers.health import (
        cleanup_stale_running_jobs,
        log_queue_depth,
        write_cron_last_run,
        write_heartbeat,
    )
    from app.workers.idle_monitor import check_idle_health

    await write_heartbeat()
    await cleanup_stale_running_jobs()
    await log_queue_depth()
    await check_idle_health()
    await write_cron_last_run("worker_health_check")


async def recover_paused(ctx: dict) -> None:
    """Probe paused IMAP accounts and AI providers, unpause on success."""
    from app.workers.health import recover_paused_providers, write_cron_last_run
    await recover_paused_providers()
    await write_cron_last_run("recover_paused")


async def execute_approved_actions(ctx: dict, approval_id: str) -> None:
    """Execute IMAP actions for an approved approval."""
    from app.workers.approval_executor import execute_approved_actions as _execute
    await _execute(ctx, approval_id)


async def handle_spam_rejection(ctx: dict, user_id: str, account_id: str, mail_uid: str) -> None:
    """Re-process email after spam rejection (not spam), skipping spam plugin."""
    from app.workers.approval_executor import handle_spam_rejection as _handle
    await _handle(ctx, user_id, account_id, mail_uid)


def _cron_minute_set(offset: int = 0) -> set[int]:
    """Build a minute-set for cron scheduling from config.

    For a 10-minute interval with offset 0: {0, 10, 20, 30, 40, 50}
    For a 10-minute interval with offset 1: {1, 11, 21, 31, 41, 51}
    """
    settings = get_settings()
    interval = settings.cron_interval_minutes
    return {m + offset for m in range(0, 60, interval) if m + offset < 60}


class WorkerSettings:
    """ARQ worker configuration.

    ``max_jobs`` defaults to 10 to allow the 5 periodic cron jobs and
    several ``process_mail`` tasks to run concurrently.  IMAP safety is
    ensured at the job-ID level: the poller deduplicates jobs per
    account+UID, so two ``process_mail`` calls for the same email never
    run in parallel.  Override via ``WORKER_MAX_JOBS`` env var.
    """

    redis_settings = get_redis_settings()

    functions = [
        # Cron-triggered tasks: no retry (next cron run catches up)
        func(poll_mail_accounts, timeout=300, max_tries=1),
        func(sync_contacts, timeout=300, max_tries=1),
        func(cleanup_drafts, timeout=120, max_tries=1),
        func(worker_health_check, timeout=30, max_tries=1),
        func(schedule_pending_mails, timeout=120, max_tries=1),
        func(recover_paused, timeout=60, max_tries=1),

        # On-demand tasks
        func(poll_single_account, timeout=120, max_tries=2),
        func(process_mail, timeout=600, max_tries=1),
        func(execute_approved_actions, timeout=120, max_tries=3),
        func(handle_spam_rejection, timeout=600, max_tries=3),
    ]

    # Each cron job is staggered by 1-minute offset to avoid all running
    # simultaneously.  Interval is driven by CRON_INTERVAL_MINUTES env var.
    cron_jobs = [
        cron(poll_mail_accounts, minute=_cron_minute_set(0)),
        cron(sync_contacts, minute=_cron_minute_set(1)),
        cron(cleanup_drafts, minute=_cron_minute_set(2)),
        cron(worker_health_check, minute=_cron_minute_set(3)),
        # Scheduler and paused-provider recovery run every minute
        cron(schedule_pending_mails, minute=set(range(60))),
        cron(recover_paused, minute=set(range(60))),
    ]

    on_startup = startup
    on_shutdown = shutdown

    _settings = get_settings()
    max_jobs = _settings.worker_max_jobs
    job_timeout = _settings.worker_job_timeout
    # Global fallback — per-function overrides above take precedence
    max_tries = 3
    # Keep results long enough that a dedup key survives until the next
    # poll cycle even for max-duration jobs.  Previously set to 60 s
    # which was shorter than the 600 s job timeout, creating a window
    # for double-enqueue when the result key expired before the next
    # poll.  Using ``job_timeout + 120`` gives comfortable headroom.
    keep_result = _settings.worker_job_timeout + 120
