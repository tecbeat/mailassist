"""Worker health monitoring and observability.

Provides:
- Worker heartbeat: writes a Valkey key on every cron cycle so external
  monitors can detect a hung worker.
- IDLE task health checks: verifies IDLE tasks are still alive and
  restarts crashed ones.
- Stale tracked_email cleanup: resets mails stuck in ``processing`` or
  ``queued`` state due to a crashed worker back to ``queued``.
  Note: After issue #40, QUEUED means "ARQ picked up the job but has
  not entered the AI pipeline yet" (IMAP fetch / parse phase).  The
  same 30-minute threshold covers both states.
- AI provider auto-recovery: reactivates circuit-broken providers after
  a cooldown period so queued mails can be retried.
- Queue-depth metrics: logs the current ARQ queue size.
- Elapsed-time helpers: context manager for timing operations.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import litellm
import structlog
from imap_tools import MailBox
from sqlalchemy import or_, select, update

from app.core.config import get_settings
from app.core.database import get_session_ctx
from app.core.events import (
    AccountReactivatedEvent,
    ProviderReactivatedEvent,
    get_event_bus,
)
from app.core.redis import get_cache_client, get_task_client
from app.core.security import decrypt_credentials, get_encryption
from app.models import TrackedEmail, TrackedEmailStatus
from app.models.ai import AIProvider
from app.models.mail import MailAccount

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = structlog.get_logger()


async def write_cron_last_run(cron_name: str) -> None:
    """Write a ``cron:last_run:<name>`` key to Valkey after a cron executes.

    The dashboard reads these keys to show per-cron last-run timestamps.
    TTL is generous (1 h) so the key survives a missed cycle.
    """
    try:
        cache = get_cache_client()
        key = f"cron:last_run:{cron_name}"
        await cache.set(key, datetime.now(UTC).isoformat(), ex=get_settings().cron_last_run_ttl_seconds)
    except Exception:
        logger.warning("cron_last_run_write_failed", cron_name=cron_name)


async def write_heartbeat(worker_id: str = "arq-worker-1") -> None:
    """Write a heartbeat key to Valkey.

    Called at the start of each cron cycle (e.g. in ``startup`` or
    a dedicated cron task). External health monitors (Docker HEALTHCHECK,
    Prometheus, etc.) can check for the key's existence.
    """
    try:
        cache = get_cache_client()
        key = f"worker:heartbeat:{worker_id}"
        await cache.set(key, datetime.now(UTC).isoformat(), ex=get_settings().heartbeat_ttl_seconds)
        logger.debug("heartbeat_written", worker_id=worker_id)
    except Exception:
        logger.warning("heartbeat_write_failed", worker_id=worker_id)


async def reset_orphaned_jobs() -> None:
    """Reset all QUEUED and PROCESSING mails back to QUEUED on worker startup.

    When the worker restarts, any mails in QUEUED or PROCESSING state are
    orphans — their ARQ jobs died with the previous worker process.  Resetting
    them to QUEUED lets the scheduler re-enqueue them on its next cycle
    (within ~1 minute) instead of waiting for the 10-minute stale threshold.
    """
    async with get_session_ctx() as db:
        stmt = (
            update(TrackedEmail)
            .where(
                TrackedEmail.status == TrackedEmailStatus.PROCESSING,
            )
            .values(
                status=TrackedEmailStatus.QUEUED,
                updated_at=datetime.now(UTC),
            )
            .returning(TrackedEmail.id)
        )
        result = await db.execute(stmt)
        reset_ids = result.scalars().all()

        if reset_ids:
            await db.commit()
            logger.info(
                "orphaned_jobs_reset_on_startup",
                count=len(reset_ids),
                msg="Reset PROCESSING mails to QUEUED after worker restart",
            )
        else:
            logger.debug("no_orphaned_jobs_on_startup")

    # Clear stale ARQ result keys for process_mail jobs.
    # These dedup keys persist across worker restarts and block the
    # scheduler from re-enqueuing mails (ARQ returns None on dedup hit).
    try:
        task_client = get_task_client()
        stale_keys = await task_client.keys("arq:result:process_mail:*")
        if stale_keys:
            await task_client.delete(*stale_keys)
            logger.info(
                "stale_arq_result_keys_cleared",
                count=len(stale_keys),
                msg="Cleared stale ARQ result keys on startup to prevent dedup deadlock",
            )
    except Exception:
        logger.warning("stale_arq_result_keys_clear_failed")


async def cleanup_stale_running_jobs() -> None:
    """Reset tracked_emails stuck in ``processing`` or ``queued`` state.

    A mail is considered stale if it has been in ``processing`` or
    ``queued`` state longer than ``stale_job_threshold_seconds``.  This
    happens when the worker crashes mid-execution or an ARQ job is lost
    (e.g. Valkey restart).  The mail is reset to ``queued`` so the
    scheduler re-enqueues it.
    """
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.stale_job_threshold_seconds)

    async with get_session_ctx() as db:
        stmt = (
            update(TrackedEmail)
            .where(
                TrackedEmail.status == TrackedEmailStatus.PROCESSING,
                TrackedEmail.updated_at < cutoff,
            )
            .values(
                status=TrackedEmailStatus.QUEUED,
                updated_at=datetime.now(UTC),
            )
            .returning(TrackedEmail.id)
        )
        result = await db.execute(stmt)
        reset_ids = result.scalars().all()

        if reset_ids:
            await db.commit()
            logger.warning(
                "stale_tracked_emails_reset",
                count=len(reset_ids),
                ids=[str(eid) for eid in reset_ids],
                threshold_seconds=settings.stale_job_threshold_seconds,
            )


async def recover_circuit_broken_providers() -> None:
    """Reactivate AI providers whose circuit breaker tripped long enough ago.

    When a provider accumulates ``CIRCUIT_BREAKER_THRESHOLD`` consecutive
    errors, the circuit breaker sets ``is_paused=True`` with
    ``paused_reason='circuit_breaker'``.  Without recovery the provider
    stays dead forever and all pending mails for that user are stuck.

    This function queries providers where ``paused_reason='circuit_breaker'``
    and ``last_error_at`` is older than ``provider_recovery_cooldown_seconds``.
    It tentatively unpauses them so the scheduler can try again.  If the
    provider is still broken, the circuit breaker will trip again — this is
    safe and expected.

    Emits a ``ProviderReactivatedEvent`` for each reactivated provider so the
    scheduler triggers an immediate scheduling run.
    """
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.provider_recovery_cooldown_seconds)

    async with get_session_ctx() as db:
        stmt = select(AIProvider).where(
            AIProvider.is_paused.is_(True),
            AIProvider.paused_reason == "circuit_breaker",
            or_(
                # Cooldown elapsed since last error
                (AIProvider.last_error_at.isnot(None)) & (AIProvider.last_error_at < cutoff),
                # Error state already cleared but still paused
                (AIProvider.consecutive_errors == 0) & (AIProvider.last_error_at.is_(None)),
            ),
        )
        result = await db.execute(stmt)
        providers = result.scalars().all()

        if not providers:
            return

        bus = get_event_bus()

        for provider in providers:
            provider.is_paused = False
            provider.paused_reason = None
            provider.paused_at = None
            provider.consecutive_errors = 0
            provider.updated_at = datetime.now(UTC)
            logger.info(
                "provider_auto_recovered",
                provider_id=str(provider.id),
                provider_name=provider.name,
                user_id=str(provider.user_id),
                last_error_at=provider.last_error_at.isoformat() if provider.last_error_at else None,
                cooldown_seconds=settings.provider_recovery_cooldown_seconds,
            )

        await db.commit()

        # Emit events *after* commit so handlers see the updated state
        for provider in providers:
            try:
                await bus.emit(
                    ProviderReactivatedEvent(
                        user_id=provider.user_id,
                        provider_id=provider.id,
                    )
                )
            except Exception:
                logger.warning(
                    "provider_reactivated_event_failed",
                    provider_id=str(provider.id),
                )


# ---------------------------------------------------------------------------
# Paused-provider / paused-account recovery with active probes (Issue #50)
# ---------------------------------------------------------------------------


async def probe_imap_account(account: MailAccount) -> bool:
    """Probe an IMAP account by connecting, logging in, and logging out.

    Returns ``True`` if the full cycle succeeds within the timeout,
    ``False`` on any error.  This is intentionally lightweight — it
    verifies reachability, not mailbox health.
    """
    try:
        credentials = decrypt_credentials(account.encrypted_credentials)
        probe_timeout = get_settings().probe_timeout_seconds

        def _probe() -> bool:
            mb = MailBox(
                host=account.imap_host,
                port=account.imap_port,
                timeout=probe_timeout,
            )
            mb.login(credentials["username"], credentials["password"], initial_folder=None)
            with suppress(Exception):
                mb.logout()
            return True

        return await asyncio.wait_for(
            asyncio.to_thread(_probe),
            timeout=probe_timeout + 5,  # extra margin for thread scheduling
        )
    except (TimeoutError, OSError, Exception):
        return False


async def probe_ai_provider(provider: AIProvider) -> bool:
    """Probe an AI provider with a lightweight API call.

    - **OpenAI-compatible**: calls ``litellm.amodels()`` which hits
      the ``/v1/models`` endpoint (free, no tokens consumed).
    - **Ollama**: calls ``GET /api/tags`` via httpx (free, lists
      available models).

    Returns ``True`` if the provider responds successfully, ``False``
    on any error.
    """
    try:
        api_key: str | None = None
        if provider.api_key:
            api_key = get_encryption().decrypt(provider.api_key)

        if provider.provider_type.value == "ollama":
            return await _probe_ollama(provider.base_url)
        else:
            return await _probe_openai_compatible(
                provider.base_url,
                api_key,
            )
    except Exception:
        return False


async def _probe_ollama(base_url: str) -> bool:
    """Probe an Ollama instance via GET /api/tags."""
    # Normalise base_url: strip trailing slash
    url = f"{base_url.rstrip('/')}/api/tags"
    async with httpx.AsyncClient(timeout=get_settings().probe_timeout_seconds) as client:
        resp = await client.get(url)
        return resp.status_code == 200


async def _probe_openai_compatible(
    base_url: str,
    api_key: str | None,
) -> bool:
    """Probe an OpenAI-compatible provider via the models endpoint."""
    kwargs: dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["api_base"] = base_url
    response = await asyncio.wait_for(
        litellm.amodels(**kwargs),
        timeout=get_settings().probe_timeout_seconds,
    )
    # litellm.amodels returns a ModelResponse with a .data list
    return len(response.data) > 0


async def recover_paused_providers() -> None:
    """Probe paused IMAP accounts and AI providers, unpause on success.

    Runs every minute as a cron job.  For each paused entity whose
    cooldown has elapsed, an active probe verifies reachability:

    - **IMAP accounts**: connect + login + logout
    - **AI providers**: ``/v1/models`` (OpenAI) or ``/api/tags`` (Ollama)

    On successful probe the entity is unpaused and an event is emitted so
    the scheduler can immediately pick up queued mails.  On failure the
    ``paused_at`` timestamp is reset to restart the cooldown.
    """
    settings = get_settings()
    now = datetime.now(UTC)

    await _recover_paused_accounts(now, settings.imap_pause_cooldown_seconds)
    await _recover_paused_ai_providers(now, settings.ai_pause_cooldown_seconds)


async def _recover_paused_accounts(
    now: datetime,
    cooldown_seconds: int,
) -> None:
    """Check paused IMAP accounts and unpause those that pass the probe."""
    async with get_session_ctx() as db:
        stmt = select(MailAccount).where(
            MailAccount.is_paused.is_(True),
            MailAccount.manually_paused.is_(False),  # skip user-paused accounts
            MailAccount.paused_reason != "circuit_breaker",  # circuit breaker has its own recovery
        )
        result = await db.execute(stmt)
        accounts = result.scalars().all()

        if not accounts:
            return

        bus = get_event_bus()
        recovered: list[MailAccount] = []

        for account in accounts:
            # Skip if cooldown has not elapsed
            if account.paused_at and ((now - account.paused_at).total_seconds() < cooldown_seconds):
                continue

            if await probe_imap_account(account):
                account.is_paused = False
                account.paused_reason = None
                account.paused_at = None
                account.consecutive_errors = 0
                account.updated_at = now
                recovered.append(account)
                logger.info(
                    "imap_account_recovered",
                    account_id=str(account.id),
                    email=account.email_address,
                    user_id=str(account.user_id),
                )
            else:
                # Reset cooldown for next attempt
                account.paused_at = now
                account.updated_at = now
                logger.info(
                    "imap_account_still_unreachable",
                    account_id=str(account.id),
                    email=account.email_address,
                )

        await db.commit()

        for account in recovered:
            try:
                await bus.emit(
                    AccountReactivatedEvent(
                        user_id=account.user_id,
                        account_id=account.id,
                    )
                )
            except Exception:
                logger.warning(
                    "account_reactivated_event_failed",
                    account_id=str(account.id),
                )


async def _recover_paused_ai_providers(
    now: datetime,
    cooldown_seconds: int,
) -> None:
    """Check paused AI providers and unpause those that pass the probe."""
    async with get_session_ctx() as db:
        stmt = select(AIProvider).where(
            AIProvider.is_paused.is_(True),
            AIProvider.manually_paused.is_(False),  # skip user-paused providers
            AIProvider.paused_reason != "circuit_breaker",  # circuit breaker has its own recovery
        )
        result = await db.execute(stmt)
        providers = result.scalars().all()

        if not providers:
            return

        bus = get_event_bus()
        recovered: list[AIProvider] = []

        for provider in providers:
            if provider.paused_at and ((now - provider.paused_at).total_seconds() < cooldown_seconds):
                continue

            if await probe_ai_provider(provider):
                provider.is_paused = False
                provider.paused_reason = None
                provider.paused_at = None
                provider.consecutive_errors = 0
                provider.updated_at = now
                recovered.append(provider)
                logger.info(
                    "ai_provider_recovered",
                    provider_id=str(provider.id),
                    provider_name=provider.name,
                    user_id=str(provider.user_id),
                )
            else:
                provider.paused_at = now
                provider.updated_at = now
                logger.info(
                    "ai_provider_still_unreachable",
                    provider_id=str(provider.id),
                    provider_name=provider.name,
                )

        await db.commit()

        for provider in recovered:
            try:
                await bus.emit(
                    ProviderReactivatedEvent(
                        user_id=provider.user_id,
                        provider_id=provider.id,
                    )
                )
            except Exception:
                logger.warning(
                    "provider_reactivated_event_failed",
                    provider_id=str(provider.id),
                )


async def log_queue_depth() -> None:
    """Log the current ARQ queue depth for observability.

    Reports queued jobs, in-progress count, and stored results so
    dashboards and alerts can track processing backlog.
    """
    try:
        client = get_task_client()

        queue_type = await client.type("arq:queue")
        queued = await client.zcard("arq:queue") if queue_type == "zset" else 0

        in_progress_keys = await client.keys("arq:in-progress:*")
        in_progress = len(in_progress_keys) if in_progress_keys else 0

        result_keys = await client.keys("arq:result:*")
        results = len(result_keys) if result_keys else 0

        logger.info(
            "queue_depth",
            queued=queued,
            in_progress=in_progress,
            results_stored=results,
        )
    except Exception:
        logger.warning("queue_depth_check_failed")


@asynccontextmanager
async def timed_operation(operation: str, **extra: object) -> AsyncIterator[None]:
    """Context manager that logs elapsed time for an operation.

    Usage::

        async with timed_operation("imap_poll", account_id=str(account.id)):
            await do_expensive_work()

    Logs ``operation_completed`` with ``elapsed_ms`` on success and
    ``operation_failed`` with ``elapsed_ms`` on exception (then re-raises).
    """
    start = time.monotonic()
    try:
        yield
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            f"{operation}_completed",
            elapsed_ms=round(elapsed_ms, 1),
            **extra,
        )
    except Exception:
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.error(
            f"{operation}_failed",
            elapsed_ms=round(elapsed_ms, 1),
            **extra,
        )
        raise
