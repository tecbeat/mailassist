"""Mail scheduler.

Periodically (every ~1 min via ARQ cron) loads tracked emails in ``QUEUED``
status, enforces per-user LLM slot limits, filters out paused accounts and
providers, and enqueues ``process_mail`` ARQ jobs in fair-queuing order.

Also exposes ``schedule_now()`` for immediate triggering after account or
provider reactivation.

Design overview
---------------
The scheduler is the single point of dispatch control.  It enforces:

1. **Per-user concurrency** — each user's ``max_concurrent_processing``
   setting caps how many mails can be in ``PROCESSING`` simultaneously.
2. **Plugin-aware provider filtering** — mails from paused or inactive
   accounts are skipped; users are skipped only when none of their
   *enabled* plugins have a healthy (active + unpaused) provider.
3. **Global worker capacity** — the total number of ARQ process_mail jobs
   is capped at ``worker_max_jobs - scheduler_reserved_slots``.
4. **Fair queuing** — round-robin across users, oldest mails first.

The status transition ``QUEUED → PROCESSING`` happens here (not in the
worker) so that slot counting is accurate.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import cycle
from uuid import UUID

import structlog
from arq import ArqRedis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import PIPELINE_PLUGIN_NAMES, PLUGIN_TO_APPROVAL_COLUMN
from app.core.database import get_session_ctx
from app.models import (
    AIProvider,
    MailAccount,
    TrackedEmail,
    TrackedEmailStatus,
    UserSettings,
)
from app.models.user import ApprovalMode

logger = structlog.get_logger()


async def schedule_pending_mails(ctx: dict) -> None:
    """Main entry point called by ARQ cron every minute.

    1. Reset stale PROCESSING mails (orphan recovery).
    2. Enforce per-user LLM slot limits.
    3. Filter out paused/inactive accounts and providers.
    4. Fair-queue (round-robin per user, oldest first) into ARQ.
    5. Transition dispatched mails from QUEUED to PROCESSING.
    """
    arq_redis: ArqRedis = ctx["redis"]

    async with get_session_ctx() as db:
        await _reset_stale_processing(db)
        await _schedule(db, arq_redis)


async def schedule_now(arq_redis: ArqRedis) -> None:
    """Immediately schedule queued mails (event-driven, e.g. reactivation)."""
    async with get_session_ctx() as db:
        await _schedule(db, arq_redis)


async def _reset_stale_processing(db: AsyncSession) -> None:
    """Reset mails stuck in PROCESSING longer than the stale threshold.

    A mail can get stuck when an ARQ job crashes, times out, or is lost
    after a worker restart.  Resetting to QUEUED lets the scheduler
    re-enqueue it on the next run.
    """
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.stale_job_threshold_seconds)

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
            "scheduler_stale_processing_reset",
            count=len(reset_ids),
            threshold_seconds=settings.stale_job_threshold_seconds,
        )


async def _schedule(db: AsyncSession, arq_redis: ArqRedis) -> None:
    """Core scheduling logic.

    Steps:
      0. Count currently PROCESSING mails (global) to determine remaining
         worker capacity.
      1. Load QUEUED tracked emails (limited to batch size).
      2. Filter accounts: exclude paused accounts.
      3. Filter providers: skip users with no healthy, non-paused provider.
      4. Per-user slot enforcement: count PROCESSING mails per user, compare
         to ``max_concurrent_processing`` from UserSettings.
      5. Round-robin across users, dispatch up to ``free_slots`` per user.
      6. Transition each dispatched mail to PROCESSING, then enqueue ARQ job.
    """

    settings = get_settings()
    max_process_slots = max(1, settings.worker_max_jobs - settings.scheduler_reserved_slots)

    # --- 0. Global capacity: count mails already in PROCESSING ---
    # Only PROCESSING counts against worker capacity (QUEUED mails are
    # waiting in the DB, not occupying ARQ slots).
    processing_stmt = (
        select(func.count())
        .select_from(TrackedEmail)
        .where(TrackedEmail.status == TrackedEmailStatus.PROCESSING)
    )
    processing_result = await db.execute(processing_stmt)
    global_processing = processing_result.scalar() or 0

    global_available = max(0, max_process_slots - global_processing)
    if global_available == 0:
        logger.debug(
            "scheduler_no_capacity",
            processing=global_processing,
            max_process_slots=max_process_slots,
        )
        return

    # --- 1. Load QUEUED tracked emails ---
    # Fetch more candidates than global_available to account for potential
    # dedup failures that won't consume slots.
    batch_limit = min(global_available * 3, settings.scheduler_max_batch)
    stmt = (
        select(
            TrackedEmail.id,
            TrackedEmail.user_id,
            TrackedEmail.mail_account_id,
            TrackedEmail.mail_uid,
            TrackedEmail.current_folder,
        )
        .where(TrackedEmail.status == TrackedEmailStatus.QUEUED)
        .order_by(TrackedEmail.retry_count.asc(), TrackedEmail.created_at.asc())
        .limit(batch_limit)
    )
    result = await db.execute(stmt)
    queued_rows = result.all()

    if not queued_rows:
        return

    logger.info("scheduler_queued_mails_found", count=len(queued_rows))

    # --- 2. Collect unique IDs ---
    account_ids = {row.mail_account_id for row in queued_rows}
    user_ids = {row.user_id for row in queued_rows}

    # --- 3. Filter accounts: active AND not paused ---
    acct_stmt = (
        select(MailAccount.id)
        .where(
            MailAccount.id.in_(account_ids),
            MailAccount.is_paused.is_(False),
        )
    )
    acct_result = await db.execute(acct_stmt)
    healthy_account_ids: set[UUID] = {row[0] for row in acct_result.all()}

    # --- 4. Load providers and user settings for plugin-aware filtering ---
    # Instead of checking whether a user has ANY healthy provider, we check
    # whether the providers actually assigned to their enabled plugins are
    # healthy.  This prevents a single unhealthy provider (that isn't even
    # used) from blocking the entire pipeline.

    provider_stmt = (
        select(AIProvider)
        .where(AIProvider.user_id.in_(user_ids))
    )
    provider_result = await db.execute(provider_stmt)
    all_providers: list[AIProvider] = list(provider_result.scalars().all())

    # Index providers by user → {str(provider.id): provider}
    user_providers: dict[UUID, dict[str, AIProvider]] = defaultdict(dict)
    for p in all_providers:
        user_providers[p.user_id][str(p.id)] = p

    # Load full UserSettings for enabled-plugin + provider-map resolution
    user_settings_stmt = select(UserSettings).where(UserSettings.user_id.in_(user_ids))
    user_settings_result = await db.execute(user_settings_stmt)
    user_settings_map: dict[UUID, UserSettings] = {
        us.user_id: us for us in user_settings_result.scalars().all()
    }

    def _user_has_healthy_provider(uid: UUID) -> bool:
        """Check that ALL enabled plugins have a healthy provider.

        Returns False as soon as any enabled plugin lacks a healthy
        provider — otherwise a mail would be dispatched but fail
        mid-pipeline when that plugin tries to call its provider.
        """
        us = user_settings_map.get(uid)
        if us is None:
            return False  # no settings → can't run plugins

        providers_by_id = user_providers.get(uid, {})
        ppm = us.plugin_provider_map or {}

        # Find the default provider (active, prefer is_default)
        default_provider: AIProvider | None = None
        for p in sorted(providers_by_id.values(), key=lambda x: x.created_at):
            if not p.is_paused:
                if p.is_default:
                    default_provider = p
                    break
                if default_provider is None:
                    default_provider = p

        has_any_enabled = False
        for plugin_name in PIPELINE_PLUGIN_NAMES:
            approval_col = PLUGIN_TO_APPROVAL_COLUMN.get(plugin_name)
            if not approval_col:
                continue
            approval_mode = getattr(us, approval_col, ApprovalMode.DISABLED)
            if approval_mode == ApprovalMode.DISABLED:
                continue
            has_any_enabled = True
            # This plugin is enabled — resolve its provider
            assigned_id = ppm.get(plugin_name)
            provider: AIProvider | None = None
            if assigned_id and assigned_id in providers_by_id:
                provider = providers_by_id[assigned_id]
            else:
                provider = default_provider
            if not (provider and not provider.is_paused):
                return False  # this enabled plugin has no healthy provider

        return has_any_enabled

    users_with_healthy_provider: set[UUID] = {
        uid for uid in user_ids if _user_has_healthy_provider(uid)
    }

    # --- 5. Per-user slot enforcement ---
    # 5a. Count PROCESSING mails per user
    per_user_processing_stmt = (
        select(TrackedEmail.user_id, func.count())
        .where(
            TrackedEmail.user_id.in_(user_ids),
            TrackedEmail.status == TrackedEmailStatus.PROCESSING,
        )
        .group_by(TrackedEmail.user_id)
    )
    per_user_result = await db.execute(per_user_processing_stmt)
    user_processing_counts: dict[UUID, int] = {
        row[0]: row[1] for row in per_user_result.all()
    }

    # 5b. Per-user max_concurrent_processing (from settings loaded in step 4)
    user_max_concurrent: dict[UUID, int] = {
        uid: us.max_concurrent_processing for uid, us in user_settings_map.items()
    }

    # 5c. Calculate free slots per user
    user_free_slots: dict[UUID, int] = {}
    for uid in user_ids:
        max_conc = user_max_concurrent.get(uid, settings.scheduler_default_max_concurrent)
        current = user_processing_counts.get(uid, 0)
        user_free_slots[uid] = max(0, max_conc - current)

    # --- 6. Group eligible mails by user ---
    # We collect ALL eligible mails per user (not limited by free_slots here)
    # because dedup failures should not consume capacity.  The round-robin
    # dispatch loop enforces per-user limits using a live slot counter.
    user_mail_queues: dict[UUID, list[tuple[UUID, UUID, str, str]]] = defaultdict(list)
    skipped_account = 0
    skipped_provider = 0

    for row in queued_rows:
        if row.mail_account_id not in healthy_account_ids:
            skipped_account += 1
            continue
        if row.user_id not in users_with_healthy_provider:
            skipped_provider += 1
            continue
        user_mail_queues[row.user_id].append(
            (row.id, row.mail_account_id, row.mail_uid, row.current_folder)
        )

    if not user_mail_queues:
        if skipped_account or skipped_provider:
            logger.info(
                "scheduler_all_skipped",
                skipped_paused_account=skipped_account,
                skipped_paused_provider=skipped_provider,
            )
        return

    # --- 7. Round-robin across users, dispatch with QUEUED→PROCESSING ---
    # Per-user slots are enforced here (not during grouping) so that a
    # dedup failure does not consume a slot and starve other mails.
    enqueued = 0
    failed = 0
    skipped_capacity = 0

    user_iters: dict[UUID, list[tuple[UUID, UUID, str, str]]] = dict(user_mail_queues)
    rr_users = list(user_iters.keys())
    rr_cycle = cycle(range(len(rr_users)))
    empty_passes = 0

    while empty_passes < len(rr_users) and enqueued < global_available:
        idx = next(rr_cycle)
        uid = rr_users[idx]
        queue = user_iters[uid]

        if not queue:
            empty_passes += 1
            continue

        # Enforce per-user capacity at dispatch time (not during grouping)
        # so that dedup failures don't consume slots.
        free = user_free_slots.get(uid, 0)
        if free <= 0:
            skipped_capacity += len(queue)
            queue.clear()  # No point iterating this user further
            empty_passes += 1
            continue

        empty_passes = 0
        tracked_id, account_id, mail_uid, current_folder = queue.pop(0)

        # Transition QUEUED → PROCESSING before dispatching the ARQ job.
        # This ensures the slot count is accurate immediately.
        try:
            update_stmt = (
                select(TrackedEmail)
                .where(
                    TrackedEmail.id == tracked_id,
                    TrackedEmail.status == TrackedEmailStatus.QUEUED,
                )
                .with_for_update(skip_locked=True)
            )
            te_result = await db.execute(update_stmt)
            tracked = te_result.scalar_one_or_none()
            if tracked is None:
                # Mail was picked up by another scheduler run or changed status
                logger.debug(
                    "scheduler_mail_already_taken",
                    tracked_id=str(tracked_id),
                    mail_uid=mail_uid,
                )
                continue
            tracked.status = TrackedEmailStatus.PROCESSING
            await db.flush()
        except Exception:
            failed += 1
            logger.exception(
                "scheduler_status_update_failed",
                tracked_id=str(tracked_id),
                mail_uid=mail_uid,
            )
            continue

        # Enqueue ARQ job
        try:
            job = await arq_redis.enqueue_job(
                "process_mail",
                str(uid),
                str(account_id),
                mail_uid,
                current_folder,
                _job_id=f"process_mail:{account_id}:{mail_uid}:{current_folder}",
            )
            if job is None:
                # Dedup hit — an ARQ result/job key with this ID already
                # exists.  This is likely a *stale* key from a previous
                # worker run.  Delete the result key so the next scheduler
                # run (or retry below) can enqueue successfully.
                job_id = f"process_mail:{account_id}:{mail_uid}:{current_folder}"
                result_key = f"arq:result:{job_id}"
                try:
                    await arq_redis.delete(result_key)
                    logger.info(
                        "scheduler_dedup_key_cleared",
                        job_id=job_id,
                        account_id=str(account_id),
                        mail_uid=mail_uid,
                    )
                except Exception:
                    logger.warning(
                        "scheduler_dedup_key_clear_failed",
                        job_id=job_id,
                    )
                # Revert to QUEUED — the stale key is now gone, so the
                # next scheduler cycle will enqueue successfully.
                tracked.status = TrackedEmailStatus.QUEUED
                await db.flush()
                failed += 1
            else:
                enqueued += 1
                user_free_slots[uid] = user_free_slots.get(uid, 0) - 1
        except Exception:
            # ARQ enqueue failed — revert status to QUEUED so the mail
            # is retried on the next scheduler run.
            failed += 1
            logger.exception(
                "scheduler_enqueue_failed",
                account_id=str(account_id),
                mail_uid=mail_uid,
            )
            try:
                tracked.status = TrackedEmailStatus.QUEUED
                await db.flush()
            except Exception:
                logger.exception("scheduler_revert_status_failed", mail_uid=mail_uid)

    # Commit all status transitions.
    await db.commit()

    logger.info(
        "scheduler_run_complete",
        enqueued=enqueued,
        failed=failed,
        skipped_paused_account=skipped_account,
        skipped_paused_provider=skipped_provider,
        skipped_user_capacity=skipped_capacity,
        global_processing=global_processing,
        global_available=global_available,
    )
