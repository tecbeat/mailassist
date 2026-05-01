"""Pydantic schemas for dashboard API responses.

Typed response models ensure OpenAPI docs are generated correctly and
Orval produces concrete TypeScript interfaces instead of ``{ [key: string]: unknown }``.
"""

from pydantic import BaseModel, Field


class DashboardStatsResponse(BaseModel):
    """Aggregated statistics for the dashboard overview cards."""

    active_accounts: int = 0
    unhealthy_accounts: int = 0
    total_accounts: int = 0
    pending_approvals: int = 0
    actions_24h: int = 0
    actions_7d: int = 0
    actions_30d: int = 0
    processed_mails_24h: int = 0
    processed_mails_7d: int = 0
    processed_mails_30d: int = 0
    total_rule_matches: int = 0
    token_usage_today: int = 0
    token_usage_7d: int = 0
    token_usage_30d: int = 0
    total_ai_providers: int = 0
    unhealthy_ai_providers: int = 0
    paused_ai_providers: int = 0
    failed_mails: int = 0
    partial_completed_mails: int = 0
    mails_without_summary: int = Field(
        default=0,
        description=(
            "Completed mails that lack an email summary record. "
            "Excludes spam-detected mails (completion_reason='spam_short_circuit')."
        ),
    )


class RecentActionItem(BaseModel):
    """A single label or folder change action."""

    id: str
    type: str = Field(description="Either 'label_change' or 'folder_change'")
    mail_account_id: str
    detail: str
    created_at: str | None = None


class RecentActionsResponse(BaseModel):
    """Paginated list of recent AI actions (label + folder changes)."""

    items: list[RecentActionItem]
    total: int
    page: int
    per_page: int
    pages: int


class DashboardErrorItem(BaseModel):
    """A mail account with a recent error."""

    account_id: str
    account_name: str
    error: str
    error_at: str | None = None
    consecutive_errors: int = 0
    is_active: bool = True


class DashboardErrorsResponse(BaseModel):
    """Paginated list of account errors."""

    items: list[DashboardErrorItem]
    total: int
    page: int
    per_page: int
    pages: int


class InProgressJob(BaseModel):
    """An ARQ job currently being processed."""

    job_id: str
    function: str
    mail_uid: str | None = None
    account_id: str | None = None
    # Pipeline progress (populated from Valkey for process_mail jobs)
    phase: str | None = None
    current_plugin: str | None = None
    current_plugin_display: str | None = None
    plugin_index: int | None = None
    plugins_total: int | None = None


class QueuedJob(BaseModel):
    """A job waiting in the ARQ queue."""

    job_id: str
    function: str
    mail_uid: str | None = None
    account_id: str | None = None


class JobQueueStatusResponse(BaseModel):
    """ARQ job queue depth, in-progress job details, and DB-based completion metrics."""

    queued: int = Field(
        default=0,
        description="Mails waiting to be processed (DB status 'queued')",
    )
    queued_total: int = Field(
        default=0,
        description="Total jobs in the ARQ queue (all types, for debugging)",
    )
    in_progress: int = Field(
        default=0,
        description=("Mail jobs currently being processed (IMAP fetch, AI pipeline, etc.)"),
    )
    in_progress_system: int = Field(
        default=0,
        description="System/cron jobs currently in progress (polling, scheduling, etc.)",
    )
    in_progress_jobs: list[InProgressJob] = Field(default_factory=list)
    queued_jobs: list[QueuedJob] = Field(default_factory=list)
    queue_page: int = 1
    queue_pages: int = 1
    results_stored: int = Field(default=0, description="Transient Valkey result count (TTL-based, for debugging)")
    completed_total: int = Field(default=0, description="Total completed mails from DB (persistent)")
    completed_today: int = Field(default=0, description="Mails completed in the last 24 hours")
    completed_last_hour: int = Field(default=0, description="Mails completed in the last hour")
    failed_total: int = Field(default=0, description="Total failed mails from DB (persistent)")
    error: str | None = None


class CronJobInfo(BaseModel):
    """Status information for a single ARQ cron job."""

    name: str = Field(description="Internal cron function name")
    display_name: str = Field(description="Human-readable name")
    description: str = Field(description="What this cron job does")
    schedule: str = Field(description="Human-readable schedule description")
    last_run: str | None = Field(default=None, description="ISO timestamp of last successful run")
    is_running: bool = Field(default=False, description="Whether this cron is currently executing")


class CronJobsResponse(BaseModel):
    """List of all cron jobs with their current status."""

    jobs: list[CronJobInfo]
    interval_minutes: int = Field(description="Current cron interval in minutes (from CRON_INTERVAL_MINUTES env var)")


class FailedMailItem(BaseModel):
    """A mail that exhausted all processing retries (dead-letter queue)."""

    id: str
    mail_account_id: str
    mail_uid: str
    subject: str | None = None
    sender: str | None = None
    folder: str | None = None
    last_error: str
    error_type: str | None = None
    retry_count: int = 0
    plugins_completed: list[str] | None = None
    plugins_failed: list[str] | None = None
    plugins_skipped: list[str] | None = None
    completion_reason: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class FailedMailsResponse(BaseModel):
    """Paginated list of failed mails."""

    items: list[FailedMailItem]
    total: int
    page: int
    per_page: int
    pages: int


class CronTriggerResponse(BaseModel):
    """Confirmation of a manually triggered cron job."""

    status: str
    job_id: str


class FailedMailActionResponse(BaseModel):
    """Confirmation of a failed-mail retry or resolve action."""

    status: str
    tracked_email_id: str
