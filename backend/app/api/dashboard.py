"""Dashboard API endpoints.

Provides real statistics, recent actions, errors, and job queue status.
Pulls data from PostgreSQL (models) and Valkey (token usage counters).
"""

import io
import math
import pickle as _pickle
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, literal_column, select, union_all

from app.api.deps import CurrentUserId, DbSession, paginate
from app.core.config import get_settings
from app.core.redis import get_arq_client, get_cache_client, get_task_binary_client, get_task_client
from app.models import (
    AIProvider,
    Approval,
    ApprovalStatus,
    EmailSummary,
    FolderChangeLog,
    LabelChangeLog,
    MailAccount,
    Rule,
    TrackedEmail,
    TrackedEmailStatus,
)
from app.models.mail import CompletionReason
from app.schemas.dashboard import (
    CronJobInfo,
    CronJobsResponse,
    CronTriggerResponse,
    DashboardErrorItem,
    DashboardErrorsResponse,
    DashboardStatsResponse,
    FailedMailActionResponse,
    FailedMailItem,
    FailedMailsResponse,
    InProgressJob,
    JobQueueStatusResponse,
    QueuedJob,
    RecentActionItem,
    RecentActionsResponse,
)

logger = structlog.get_logger()


class _RestrictedUnpickler(_pickle.Unpickler):
    """Unpickler that only allows primitive types.

    Prevents arbitrary code execution if Valkey data is tampered with.
    """

    _SAFE_BUILTINS = frozenset({
        "builtins.dict",
        "builtins.list",
        "builtins.tuple",
        "builtins.set",
        "builtins.frozenset",
        "builtins.str",
        "builtins.bytes",
        "builtins.int",
        "builtins.float",
        "builtins.bool",
        "builtins.complex",
        "builtins.type",
        "datetime.datetime",
        "datetime.timedelta",
        "datetime.date",
        "datetime.time",
        "uuid.UUID",
    })

    def find_class(self, module: str, name: str) -> type:
        fqn = f"{module}.{name}"
        if fqn in self._SAFE_BUILTINS:
            return super().find_class(module, name)
        raise _pickle.UnpicklingError(
            f"Restricted unpickler: {fqn!r} is not allowed"
        )


router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    db: DbSession,
    user_id: CurrentUserId,
) -> DashboardStatsResponse:
    """Get dashboard statistics for 24h / 7d / 30d time ranges.

    Aggregates: mail processing actions, pending approvals, active accounts,
    AI token usage, matched rules.
    """
    uid = UUID(user_id)
    now = datetime.now(UTC)

    # -- Account health --
    accounts_stmt = select(MailAccount).where(MailAccount.user_id == uid)
    accounts_result = await db.execute(accounts_stmt)
    accounts = accounts_result.scalars().all()

    active_accounts = sum(1 for a in accounts if not a.is_paused)
    unhealthy_accounts = sum(1 for a in accounts if a.consecutive_errors >= 5)

    # -- AI provider health --
    providers_stmt = select(AIProvider).where(AIProvider.user_id == uid)
    providers_result = await db.execute(providers_stmt)
    providers = providers_result.scalars().all()

    total_ai_providers = len(providers)
    paused_ai_providers = sum(1 for p in providers if p.is_paused)
    unhealthy_ai_providers = sum(
        1 for p in providers if not p.is_paused and p.consecutive_errors >= 3
    )

    # -- Pending approvals --
    pending_stmt = select(func.count()).select_from(
        select(Approval)
        .where(Approval.user_id == uid, Approval.status == ApprovalStatus.PENDING)
        .subquery()
    )
    pending_approvals = (await db.execute(pending_stmt)).scalar_one()

    # -- AI actions (label changes + folder changes) by time range --
    actions_24h = await _count_actions_since(db, uid, now - timedelta(hours=24))
    actions_7d = await _count_actions_since(db, uid, now - timedelta(days=7))
    actions_30d = await _count_actions_since(db, uid, now - timedelta(days=30))

    # -- Processed mails (email summaries as proxy) by time range --
    processed_24h = await _count_processed_since(db, uid, now - timedelta(hours=24))
    processed_7d = await _count_processed_since(db, uid, now - timedelta(days=7))
    processed_30d = await _count_processed_since(db, uid, now - timedelta(days=30))

    # -- Rule matches (30d) --
    rules_stmt = select(func.sum(Rule.match_count)).where(Rule.user_id == uid)
    total_rule_matches = (await db.execute(rules_stmt)).scalar_one() or 0

    # -- Token usage from Valkey --
    token_usage_today = await _get_token_usage(user_id, days=1)
    token_usage_7d = await _get_token_usage(user_id, days=7)
    token_usage_30d = await _get_token_usage(user_id, days=30)

    # -- Failed mails (tracked_emails with status 'failed') --
    failed_mails_stmt = select(func.count()).select_from(
        select(TrackedEmail.id)
        .where(TrackedEmail.user_id == uid, TrackedEmail.status == TrackedEmailStatus.FAILED)
        .subquery()
    )
    failed_mails_count = (await db.execute(failed_mails_stmt)).scalar_one()

    # -- Partial completions and summary gap --
    # These queries depend on columns added in recent migrations
    # (plugins_completed, completion_reason, etc.).  If the migrations
    # have not been applied yet, the queries will fail.  We catch the
    # error and return 0 so the rest of the dashboard stays functional.
    partial_completed_count = 0
    mails_without_summary_count = 0
    try:
        partial_completed_stmt = select(func.count()).select_from(
            select(TrackedEmail.id)
            .where(
                TrackedEmail.user_id == uid,
                TrackedEmail.status == TrackedEmailStatus.COMPLETED,
                TrackedEmail.completion_reason.in_([CompletionReason.PARTIAL_WITH_ERRORS, CompletionReason.ALL_PLUGINS_FAILED]),
            )
            .subquery()
        )
        partial_completed_count = (await db.execute(partial_completed_stmt)).scalar_one()

        # LEFT JOIN tracked_emails with email_summaries, keeping only rows
        # where no summary exists.  Spam-detected mails (short-circuited
        # before the summary plugin could run) are excluded since they are
        # expected to lack summaries.
        without_summary_stmt = (
            select(func.count(TrackedEmail.id))
            .select_from(TrackedEmail)
            .outerjoin(
                EmailSummary,
                (TrackedEmail.mail_account_id == EmailSummary.mail_account_id)
                & (TrackedEmail.mail_uid == EmailSummary.mail_uid),
            )
            .where(
                TrackedEmail.user_id == uid,
                TrackedEmail.status == TrackedEmailStatus.COMPLETED,
                TrackedEmail.completion_reason != CompletionReason.SPAM_SHORT_CIRCUIT,
                EmailSummary.id.is_(None),
            )
        )
        mails_without_summary_count = (await db.execute(without_summary_stmt)).scalar_one()
    except Exception:
        logger.warning(
            "dashboard_stats_partial_query_failed",
            user_id=user_id,
            exc_info=True,
        )

    return DashboardStatsResponse(
        active_accounts=active_accounts,
        unhealthy_accounts=unhealthy_accounts,
        total_accounts=len(accounts),
        pending_approvals=pending_approvals,
        actions_24h=actions_24h,
        actions_7d=actions_7d,
        actions_30d=actions_30d,
        processed_mails_24h=processed_24h,
        processed_mails_7d=processed_7d,
        processed_mails_30d=processed_30d,
        total_rule_matches=total_rule_matches,
        token_usage_today=token_usage_today,
        token_usage_7d=token_usage_7d,
        token_usage_30d=token_usage_30d,
        total_ai_providers=total_ai_providers,
        unhealthy_ai_providers=unhealthy_ai_providers,
        paused_ai_providers=paused_ai_providers,
        failed_mails=failed_mails_count,
        partial_completed_mails=partial_completed_count,
        mails_without_summary=mails_without_summary_count,
    )


@router.get("/dashboard/recent-actions")
async def get_recent_actions(
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> RecentActionsResponse:
    """Get recent AI actions (label + folder changes), paginated.

    Uses a SQL UNION with ORDER BY / OFFSET / LIMIT so the database
    handles sorting and pagination instead of loading everything into memory.
    """
    uid = UUID(user_id)

    label_q = (
        select(
            LabelChangeLog.id,
            literal_column("'label_change'").label("type"),
            LabelChangeLog.mail_account_id,
            LabelChangeLog.label.label("detail"),
            LabelChangeLog.created_at,
        )
        .where(LabelChangeLog.user_id == uid)
    )
    folder_q = (
        select(
            FolderChangeLog.id,
            literal_column("'folder_change'").label("type"),
            FolderChangeLog.mail_account_id,
            FolderChangeLog.folder.label("detail"),
            FolderChangeLog.created_at,
        )
        .where(FolderChangeLog.user_id == uid)
    )

    combined = union_all(label_q, folder_q).subquery()

    base_stmt = select(combined).order_by(combined.c.created_at.desc())
    result = await paginate(db, base_stmt, page, per_page, scalars=False)

    items = [
        RecentActionItem(
            id=str(row.id),
            type=row.type,
            mail_account_id=str(row.mail_account_id),
            detail=row.detail,
            created_at=row.created_at.isoformat() if row.created_at else None,
        )
        for row in result.items
    ]

    return RecentActionsResponse(
        items=items,
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
    )


@router.get("/dashboard/errors")
async def get_dashboard_errors(
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> DashboardErrorsResponse:
    """Get recent account errors with timestamps, paginated in SQL."""
    uid = UUID(user_id)

    base_filter = [MailAccount.user_id == uid, MailAccount.last_error.is_not(None)]

    base_stmt = (
        select(MailAccount)
        .where(*base_filter)
        .order_by(MailAccount.last_error_at.desc())
    )
    result = await paginate(db, base_stmt, page, per_page)

    items = [
        DashboardErrorItem(
            account_id=str(account.id),
            account_name=account.name,
            error=account.last_error,
            error_at=account.last_error_at.isoformat() if account.last_error_at else None,
            consecutive_errors=account.consecutive_errors,
            is_active=not account.is_paused,
        )
        for account in result.items
    ]

    return DashboardErrorsResponse(
        items=items,
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
    )


@router.get("/dashboard/jobs")
async def get_job_queue_status(
    db: DbSession,
    user_id: CurrentUserId,
    queue_page: int = Query(default=1, ge=1),
    queue_per_page: int = Query(default=10, ge=1, le=100),
) -> JobQueueStatusResponse:
    """Get ARQ job queue status from Valkey plus DB-based completion metrics.

    Returns queue depth, in-progress jobs with mail UIDs, paginated
    queued jobs, transient Valkey result counts, and persistent
    DB-based completion/failure counters from ``TrackedEmail``.
    """
    uid = UUID(user_id)
    now = datetime.now(UTC)

    # -- DB-based metrics (persistent) --
    # The "queued" count comes from the DB (TrackedEmail with status QUEUED),
    # NOT from the ARQ queue in Valkey.  Mails spend most of their waiting
    # time in the DB; the ARQ queue is nearly always empty because the
    # scheduler dispatches jobs immediately.
    queued_in_db = await _count_tracked(db, uid, TrackedEmailStatus.QUEUED)
    completed_total = await _count_tracked(db, uid, TrackedEmailStatus.COMPLETED)
    completed_today = await _count_tracked(
        db, uid, TrackedEmailStatus.COMPLETED, since=now - timedelta(hours=24),
    )
    completed_last_hour = await _count_tracked(
        db, uid, TrackedEmailStatus.COMPLETED, since=now - timedelta(hours=1),
    )
    failed_total = await _count_tracked(db, uid, TrackedEmailStatus.FAILED)

    try:
        task_client = get_task_client()

        # Queue is a sorted set in ARQ
        queue_type = await task_client.type("arq:queue")
        if queue_type == "zset":
            queued_total = await task_client.zcard("arq:queue")
        else:
            queued_total = 0

        # In-progress jobs: arq:in-progress:<job_id> keys
        in_progress_keys: list[str] = await task_client.keys("arq:in-progress:*")

        # Decode in-progress jobs to extract function name and mail_uid
        in_progress_jobs: list[InProgressJob] = []
        if in_progress_keys:
            await _collect_in_progress_jobs(in_progress_keys, in_progress_jobs)

        # Enrich process_mail jobs with plugin progress from Valkey
        await _enrich_with_pipeline_progress(in_progress_jobs)

        # Separate mail-processing jobs from system/cron jobs so the
        # "Processing" tile accurately reflects emails being processed,
        # not total ARQ concurrency (which includes cron tasks).
        mail_jobs = [j for j in in_progress_jobs if j.function == "process_mail"]
        system_jobs = [j for j in in_progress_jobs if j.function != "process_mail"]
        in_progress_system = len(system_jobs)

        # All mail jobs in ARQ in-progress are counted as processing.
        # Concurrency is controlled by the scheduler via per-user LLM slots.
        in_progress_mail = len(mail_jobs)

        # Paginated queued jobs from the arq:queue sorted set.
        # Exclude jobs that are already in-progress so they don't
        # appear in both lists on the dashboard.
        in_progress_ids = {
            k.removeprefix("arq:in-progress:") for k in in_progress_keys
        } if in_progress_keys else set()

        # Count only process_mail jobs in the queue (exclude cron/system).
        # We scan the full queue to get an accurate count and filter in
        # one pass, then paginate the filtered list in memory.
        queued_mail_ids: list[str] = []
        if queued_total > 0:
            all_job_ids: list[str] = await task_client.zrange(
                "arq:queue", 0, -1,
            )
            queued_mail_ids = [
                jid for jid in all_job_ids
                if jid not in in_progress_ids and jid.startswith("process_mail:")
            ]

        queued_mail_count = len(queued_mail_ids)
        queued_jobs: list[QueuedJob] = []
        queue_pages = max(1, math.ceil(queued_mail_count / queue_per_page))
        if queued_mail_ids:
            offset = (queue_page - 1) * queue_per_page
            page_ids = queued_mail_ids[offset:offset + queue_per_page]
            if page_ids:
                await _collect_queued_jobs(page_ids, queued_jobs)

        # Result counters: count total and recent failures
        result_keys: list[str] = await task_client.keys("arq:result:*")
        results_stored = len(result_keys) if result_keys else 0

        return JobQueueStatusResponse(
            queued=queued_in_db,
            queued_total=queued_total,
            in_progress=in_progress_mail,
            in_progress_system=in_progress_system,
            in_progress_jobs=mail_jobs,
            queued_jobs=queued_jobs,
            queue_page=queue_page,
            queue_pages=queue_pages,
            results_stored=results_stored,
            completed_total=completed_total,
            completed_today=completed_today,
            completed_last_hour=completed_last_hour,
            failed_total=failed_total,
        )
    except Exception:
        logger.exception("job_queue_status_failed")
        return JobQueueStatusResponse(
            error="Could not query job queue",
            queued=queued_in_db,
            completed_total=completed_total,
            completed_today=completed_today,
            completed_last_hour=completed_last_hour,
            failed_total=failed_total,
        )


def _parse_job_id(job_id: str) -> tuple[str, str | None, str | None]:
    """Extract function name, mail_uid, and account_id from an ARQ job ID.

    Handles both custom IDs (``process_mail:<account_id>:<uid>``) and
    ARQ cron IDs (``cron:<function_name>:<hex>``).

    Returns:
        (function_name, mail_uid, account_id)
    """
    parts = job_id.split(":")
    if not parts:
        return ("unknown", None, None)

    # ARQ cron jobs use the pattern "cron:<function_name>:<hex>"
    if parts[0] == "cron" and len(parts) >= 2:
        return (parts[1], None, None)

    # Custom task IDs: "process_mail:<account_id>:<uid>"
    fn = parts[0]
    account_id = parts[1] if len(parts) >= 3 else None
    mail_uid = parts[2] if len(parts) >= 3 else None
    return (fn, mail_uid, account_id)


async def _collect_in_progress_jobs(
    keys: list[str],
    out: list[InProgressJob],
) -> None:
    """Decode in-progress ARQ jobs to extract function name and mail UID.

    Tries to read the pickle-serialized job payload from Valkey using the
    persistent binary-mode client.  Falls back to parsing the job ID
    when the payload is missing or cannot be safely deserialized.
    """
    raw_client = get_task_binary_client()

    for key in keys:
        job_id = key.removeprefix("arq:in-progress:")
        raw = await raw_client.get(f"arq:job:{job_id}".encode())
        if not raw:
            fn, mail_uid, account_id = _parse_job_id(job_id)
            out.append(InProgressJob(
                job_id=job_id,
                function=fn,
                mail_uid=mail_uid,
                account_id=account_id,
            ))
            continue
        try:
            data = _RestrictedUnpickler(io.BytesIO(raw)).load()
            fn = data.get("f", "")
            args = data.get("a", ())
            entry = InProgressJob(
                job_id=job_id,
                function=fn,
                mail_uid=str(args[2]) if fn == "process_mail" and len(args) >= 3 else None,
                account_id=str(args[1]) if fn == "process_mail" and len(args) >= 3 else None,
            )
            out.append(entry)
        except Exception:
            # Deserialization failed — fall back to job ID parsing
            fn, mail_uid, account_id = _parse_job_id(job_id)
            out.append(InProgressJob(
                job_id=job_id,
                function=fn,
                mail_uid=mail_uid,
                account_id=account_id,
            ))


async def _enrich_with_pipeline_progress(jobs: list[InProgressJob]) -> None:
    """Read pipeline progress from Valkey and attach to in-progress jobs.

    Progress keys are written by the pipeline orchestrator before each
    plugin execution.  They auto-expire after 5 minutes.
    """
    from app.workers.pipeline_orchestrator import PROGRESS_KEY_PREFIX

    mail_jobs = [j for j in jobs if j.function == "process_mail"]
    if not mail_jobs:
        return

    try:
        client = get_task_client()
        for job in mail_jobs:
            key = f"{PROGRESS_KEY_PREFIX}{job.job_id}"
            raw = await client.get(key)
            if not raw:
                continue
            try:
                import json
                data = json.loads(raw)
                job.phase = data.get("phase")
                job.current_plugin = data.get("current_plugin")
                job.current_plugin_display = data.get("current_plugin_display")
                job.plugin_index = data.get("plugin_index")
                job.plugins_total = data.get("plugins_total")
            except (ValueError, TypeError):
                continue
    except Exception:
        # Progress enrichment is best-effort
        pass


async def _collect_queued_jobs(
    job_ids: list[str],
    out: list[QueuedJob],
) -> None:
    """Decode queued ARQ jobs to extract function name and mail UID.

    The arq:queue sorted set stores job IDs as members.  The actual job
    payload lives in the ``arq:job:<job_id>`` key (pickle-serialized).
    Uses the persistent binary-mode Valkey client with a restricted
    unpickler to avoid RCE from tampered data.
    """
    raw_client = get_task_binary_client()

    for job_id in job_ids:
        raw = await raw_client.get(f"arq:job:{job_id}".encode())
        if not raw:
            fn, mail_uid, account_id = _parse_job_id(job_id)
            out.append(QueuedJob(
                job_id=job_id,
                function=fn,
                mail_uid=mail_uid,
                account_id=account_id,
            ))
            continue
        try:
            data = _RestrictedUnpickler(io.BytesIO(raw)).load()
            fn = data.get("f", "")
            args = data.get("a", ())
            entry = QueuedJob(
                job_id=job_id,
                function=fn,
                mail_uid=str(args[2]) if fn == "process_mail" and len(args) >= 3 else None,
                account_id=str(args[1]) if fn == "process_mail" and len(args) >= 3 else None,
            )
            out.append(entry)
        except Exception:
            # Deserialization failed — fall back to job ID parsing
            fn, mail_uid, account_id = _parse_job_id(job_id)
            out.append(QueuedJob(
                job_id=job_id,
                function=fn,
                mail_uid=mail_uid,
                account_id=account_id,
            ))


async def _count_actions_since(db, user_id: UUID, since: datetime) -> int:
    """Count label + folder changes since a timestamp."""
    label_count_stmt = select(func.count()).select_from(
        select(LabelChangeLog.id)
        .where(LabelChangeLog.user_id == user_id, LabelChangeLog.created_at >= since)
        .subquery()
    )
    folder_count_stmt = select(func.count()).select_from(
        select(FolderChangeLog.id)
        .where(FolderChangeLog.user_id == user_id, FolderChangeLog.created_at >= since)
        .subquery()
    )

    labels = (await db.execute(label_count_stmt)).scalar_one()
    folders = (await db.execute(folder_count_stmt)).scalar_one()
    return labels + folders


async def _count_processed_since(db, user_id: UUID, since: datetime) -> int:
    """Count mails completed since a timestamp via tracked_emails."""
    stmt = select(func.count()).select_from(
        select(TrackedEmail.id)
        .where(
            TrackedEmail.user_id == user_id,
            TrackedEmail.status == TrackedEmailStatus.COMPLETED,
            TrackedEmail.updated_at >= since,
        )
        .subquery()
    )
    return (await db.execute(stmt)).scalar_one()


async def _count_tracked(
    db,
    user_id: UUID,
    status: TrackedEmailStatus,
    *,
    since: datetime | None = None,
) -> int:
    """Count tracked emails by status, optionally filtered by time."""
    filters = [
        TrackedEmail.user_id == user_id,
        TrackedEmail.status == status,
    ]
    if since is not None:
        filters.append(TrackedEmail.updated_at >= since)
    stmt = select(func.count()).select_from(
        select(TrackedEmail.id).where(*filters).subquery()
    )
    return (await db.execute(stmt)).scalar_one()


async def _get_token_usage(user_id: str, days: int) -> int:
    """Aggregate token usage from Valkey daily counters."""
    try:
        cache = get_cache_client()
        total = 0
        now = datetime.now(UTC)

        for day_offset in range(days):
            date_str = (now - timedelta(days=day_offset)).strftime("%Y-%m-%d")
            key = f"token_usage:{user_id}:{date_str}"
            val = await cache.get(key)
            if val is not None:
                total += int(val)

        return total
    except Exception:
        logger.warning("token_usage_fetch_failed", user_id=user_id, days=days)
        return 0


# ---------------------------------------------------------------------------
# Cron job metadata
# ---------------------------------------------------------------------------

def _cron_schedule_label() -> str:
    """Return a human-readable schedule label from the configured interval."""
    interval = get_settings().cron_interval_minutes
    return f"Every {interval} minute{'s' if interval != 1 else ''}"


_CRON_JOBS: list[dict[str, str]] = [
    {
        "name": "poll_mail_accounts",
        "display_name": "Poll Mail Accounts",
        "description": "Checks all active IMAP accounts for new emails",
    },
    {
        "name": "sync_contacts",
        "display_name": "Sync Contacts",
        "description": "Syncs contacts from CardDAV for all active configs",
    },
    {
        "name": "cleanup_drafts",
        "display_name": "Cleanup Drafts",
        "description": "Removes stale AI-generated draft emails",
    },
    {
        "name": "worker_health_check",
        "display_name": "Worker Health Check",
        "description": "Heartbeat, stale job cleanup, queue metrics, IDLE health",
    },
    {
        "name": "schedule_pending_mails",
        "display_name": "Schedule Pending Mails",
        "description": "Checks pending tracked emails and enqueues them for AI processing",
    },
]

# Map cron names to the actual worker task function names for enqueuing
_CRON_FUNCTION_MAP: dict[str, str] = {
    job["name"]: job["name"] for job in _CRON_JOBS
}


@router.get("/dashboard/crons")
async def get_cron_jobs(
    user_id: CurrentUserId,
) -> CronJobsResponse:
    """Return status information for all ARQ cron jobs.

    Reads ``cron:last_run:<name>`` keys from Valkey to determine
    last execution time, and checks in-progress keys for running state.
    """
    try:
        cache = get_cache_client()
        task_client = get_task_client()

        # Check which functions are currently running via arq:in-progress:* keys
        in_progress_keys: list[str] = await task_client.keys("arq:in-progress:*") or []
        running_functions: set[str] = set()
        for key in in_progress_keys:
            # in-progress keys encode the job_id; for crons, ARQ uses the function name
            job_id = key.removeprefix("arq:in-progress:")
            # Cron job IDs in ARQ are just the function name
            if job_id in _CRON_FUNCTION_MAP:
                running_functions.add(job_id)

        jobs: list[CronJobInfo] = []
        schedule = _cron_schedule_label()
        for meta in _CRON_JOBS:
            last_run_val = await cache.get(f"cron:last_run:{meta['name']}")
            jobs.append(
                CronJobInfo(
                    name=meta["name"],
                    display_name=meta["display_name"],
                    description=meta["description"],
                    schedule=schedule,
                    last_run=last_run_val,
                    is_running=meta["name"] in running_functions,
                )
            )

        return CronJobsResponse(
            jobs=jobs,
            interval_minutes=get_settings().cron_interval_minutes,
        )
    except Exception:
        logger.exception("cron_jobs_status_failed")
        return CronJobsResponse(jobs=[], interval_minutes=10)


@router.post("/dashboard/crons/{cron_name}/trigger")
async def trigger_cron_job(
    user_id: CurrentUserId,
    cron_name: str,
) -> CronTriggerResponse:
    """Manually enqueue a cron job for immediate execution.

    Returns the ARQ job object's id on success.
    """
    if cron_name not in _CRON_FUNCTION_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown cron job: {cron_name}")

    arq = get_arq_client()
    job = await arq.enqueue_job(cron_name)

    if job is None:
        # ARQ returns None when a job with the same ID is already queued
        return CronTriggerResponse(status="already_queued", job_id=cron_name)

    return CronTriggerResponse(status="enqueued", job_id=job.job_id)


# ---------------------------------------------------------------------------
# Failed mails (tracked_emails with status 'failed')
# ---------------------------------------------------------------------------


@router.get("/dashboard/failed-mails")
async def get_failed_mails(
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> FailedMailsResponse:
    """Get failed mails from tracked_emails, paginated."""
    uid = UUID(user_id)

    base_filters = [
        TrackedEmail.user_id == uid,
        TrackedEmail.status == TrackedEmailStatus.FAILED,
    ]

    base_stmt = (
        select(TrackedEmail)
        .where(*base_filters)
        .order_by(TrackedEmail.updated_at.desc())
    )
    result = await paginate(db, base_stmt, page, per_page)

    items = [
        FailedMailItem(
            id=str(te.id),
            mail_account_id=str(te.mail_account_id),
            mail_uid=te.mail_uid,
            subject=te.subject,
            sender=te.sender,
            folder=te.current_folder,
            last_error=te.last_error or "",
            error_type=te.error_type,
            retry_count=te.retry_count,
            plugins_completed=te.plugins_completed,
            plugins_failed=te.plugins_failed,
            plugins_skipped=te.plugins_skipped,
            completion_reason=te.completion_reason,
            created_at=te.created_at.isoformat() if te.created_at else None,
            updated_at=te.updated_at.isoformat() if te.updated_at else None,
        )
        for te in result.items
    ]

    return FailedMailsResponse(
        items=items,
        total=result.total,
        page=result.page,
        per_page=result.per_page,
        pages=result.pages,
    )


@router.post("/dashboard/failed-mails/{tracked_email_id}/retry")
async def retry_failed_mail(
    db: DbSession,
    user_id: CurrentUserId,
    tracked_email_id: str,
) -> FailedMailActionResponse:
    """Retry a failed mail: set status back to pending and reset retry_count."""
    uid = UUID(user_id)
    stmt = select(TrackedEmail).where(
        TrackedEmail.id == UUID(tracked_email_id),
        TrackedEmail.user_id == uid,
        TrackedEmail.status == TrackedEmailStatus.FAILED,
    )
    result = await db.execute(stmt)
    te = result.scalar_one_or_none()

    if te is None:
        raise HTTPException(status_code=404, detail="Failed mail not found")

    te.status = TrackedEmailStatus.QUEUED
    te.retry_count = 0
    te.last_error = None
    te.updated_at = datetime.now(UTC)
    await db.flush()

    logger.info("failed_mail_retried", tracked_email_id=tracked_email_id, user_id=user_id)
    return FailedMailActionResponse(status="queued", tracked_email_id=tracked_email_id)


@router.post("/dashboard/failed-mails/{tracked_email_id}/resolve")
async def resolve_failed_mail(
    db: DbSession,
    user_id: CurrentUserId,
    tracked_email_id: str,
) -> FailedMailActionResponse:
    """Dismiss a failed mail: mark as completed (user considers it handled)."""
    uid = UUID(user_id)
    stmt = select(TrackedEmail).where(
        TrackedEmail.id == UUID(tracked_email_id),
        TrackedEmail.user_id == uid,
        TrackedEmail.status == TrackedEmailStatus.FAILED,
    )
    result = await db.execute(stmt)
    te = result.scalar_one_or_none()

    if te is None:
        raise HTTPException(status_code=404, detail="Failed mail not found")

    te.status = TrackedEmailStatus.COMPLETED
    te.updated_at = datetime.now(UTC)
    await db.flush()

    logger.info("failed_mail_resolved", tracked_email_id=tracked_email_id, user_id=user_id)
    return FailedMailActionResponse(status="completed", tracked_email_id=tracked_email_id)
