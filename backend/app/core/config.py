"""Application configuration via pydantic-settings.

Loads all settings from environment variables with type validation.
Settings are cached after first load to avoid repeated .env parsing.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Type-safe application configuration from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "mailassist"
    debug: bool = False

    # Database
    database_url: str = Field(
        description="PostgreSQL connection string (asyncpg)",
    )

    # Valkey (Redis-compatible)
    valkey_url: str = Field(
        default="redis://valkey:6379/0",
        description="Valkey connection URL (redis:// protocol)",
    )
    valkey_socket_timeout: float = Field(
        default=5.0,
        description="Valkey socket read/write timeout in seconds",
    )
    valkey_socket_connect_timeout: float = Field(
        default=3.0,
        description="Valkey socket connect timeout in seconds",
    )

    # Security
    app_secret_key: str = Field(
        min_length=32,
        description="Master encryption key (KEK). Min 32 characters.",
    )
    app_secret_key_old: str | None = Field(
        default=None,
        description="Previous master key for graceful key rotation.",
    )

    # OIDC / SSO (optional so the worker container can start without them)
    oidc_issuer_url: str | None = Field(default=None, description="OIDC provider discovery URL")
    oidc_client_id: str | None = Field(default=None, description="OIDC client ID")
    oidc_client_secret: str | None = Field(default=None, description="OIDC client secret")
    oidc_redirect_uri: str | None = Field(default=None, description="OIDC callback URL")
    oidc_scopes: str = "openid email profile"

    # CORS
    cors_allowed_origins: str = Field(
        default="",
        description=(
            "Comma-separated list of allowed CORS origins. "
            "Example: 'https://mail.example.com,https://mail.internal'. "
            "An empty value disallows all cross-origin requests."
        ),
    )

    # Session
    session_ttl_seconds: int = Field(default=86400, description="Session TTL in seconds (default 24h)")

    # Rate Limiting
    auth_rate_limit: int = Field(default=10, description="Max login attempts per minute per IP")
    api_rate_limit: int = Field(default=100, description="Max API requests per minute per user")
    trusted_proxies: list[str] = Field(
        default_factory=list,
        description=(
            "List of trusted reverse proxy IPs/CIDRs. "
            "X-Forwarded-For is only respected when the direct client IP "
            "is in this list. Example: ['10.0.0.0/8', '172.16.0.0/12']"
        ),
    )

    # AI defaults
    ai_max_tokens: int = Field(default=1024, description="Default max tokens for LLM responses")
    ai_temperature: float = Field(default=0.3, description="Default LLM temperature")
    ai_timeout_seconds: int = Field(default=120, description="LLM HTTP request timeout in seconds")
    ai_token_usage_ttl_days: int = Field(default=90, description="Token usage stats TTL in days")
    ai_pause_cooldown_seconds: int = Field(
        default=120,
        description="Seconds before auto-unpausing a paused AI provider",
    )

    # Mail defaults
    imap_timeout_seconds: int = Field(default=30, description="IMAP connection timeout in seconds")
    imap_pause_cooldown_seconds: int = Field(
        default=300,
        description="Seconds before auto-unpausing a paused mail account (IMAP errors)",
    )
    max_email_body_size: int = Field(default=51200, description="Max email body size in bytes (50KB)")
    max_jobs_per_user_per_minute: int = Field(default=20, description="Fair queuing limit")

    # Polling
    poll_concurrency: int = Field(default=5, description="Max concurrent IMAP connections during polling")
    poll_initial_scan_batch: int = Field(default=200, description="Batch size for envelope fetching during initial IMAP scan")

    # Contact sync
    contact_cache_ttl_seconds: int = Field(default=3600, description="Contact match cache TTL in seconds")

    # IMAP folder cache
    imap_folder_cache_ttl_seconds: int = Field(default=120, description="IMAP folder list cache TTL in seconds")
    contact_sync_max_errors: int = Field(default=10, description="Disable CardDAV config after this many consecutive failures")

    # Database pool
    db_pool_size: int = Field(default=10, description="SQLAlchemy connection pool size")
    db_max_overflow: int = Field(default=20, description="SQLAlchemy max overflow connections")
    db_pool_recycle: int = Field(default=1800, description="SQLAlchemy pool_recycle in seconds")

    # Worker
    worker_max_jobs: int = Field(
        default=10,
        description=(
            "Max concurrent ARQ jobs. Must be high enough for the 5 cron "
            "jobs to run without starving queued tasks. IMAP concurrency "
            "safety is ensured by deduplicating jobs per account, not by "
            "limiting total parallelism."
        ),
    )
    worker_job_timeout: int = Field(default=600, description="ARQ job timeout in seconds")

    # Scheduler
    scheduler_max_batch: int = Field(default=500, description="Max mails to schedule per cron run")
    scheduler_reserved_slots: int = Field(default=2, description="Worker slots reserved for cron jobs")
    scheduler_default_max_concurrent: int = Field(default=3, description="Default per-user concurrency limit")

    # Health monitoring
    heartbeat_ttl_seconds: int = Field(default=600, description="Worker heartbeat Valkey key TTL in seconds")
    stale_job_threshold_seconds: int = Field(default=660, description="Reset jobs stuck longer than this (seconds)")
    provider_recovery_cooldown_seconds: int = Field(default=600, description="Cooldown before auto-reactivating circuit-broken AI providers")
    cron_last_run_ttl_seconds: int = Field(default=3600, description="Valkey TTL for cron:last_run keys in seconds")
    probe_timeout_seconds: int = Field(default=10, description="Timeout for IMAP/AI provider liveness probes")

    # Pipeline
    pipeline_progress_ttl_seconds: int = Field(default=300, description="Valkey TTL for pipeline progress keys")
    approval_expiry_days: int = Field(default=7, description="Days before unapproved approvals expire")

    # Cron scheduling
    cron_interval_minutes: int = Field(
        default=10,
        ge=1,
        le=60,
        description=(
            "Base interval (minutes) for periodic cron jobs. "
            "Each cron is staggered by 1 minute offset from this base. "
            "Requires worker restart to take effect."
        ),
    )

    # Draft cleanup
    draft_expiry_days: int = Field(default=7, description="Auto-delete AI drafts after N days")
    draft_sent_folder_names: str = Field(
        default="Sent,INBOX.Sent,Sent Messages,Sent Items",
        description="Comma-separated IMAP Sent folder names to try",
    )
    draft_folder_names: str = Field(
        default="Drafts,INBOX.Drafts,Draft",
        description="Comma-separated IMAP Drafts folder names to try",
    )
    draft_lookback_days: int = Field(default=14, description="Days to look back in Sent for superseded drafts")
    draft_max_sent_scan: int = Field(default=100, description="Max recent Sent messages to scan for In-Reply-To headers")

    # Rate limiting
    rate_limit_fail_open: bool = Field(
        default=True,
        description=(
            "When True (default), requests are allowed through if Valkey is unreachable — "
            "preserving availability at the cost of rate limiting. "
            "When False, requests return 503 during Valkey outages — "
            "enforcing rate limits at the cost of availability."
        ),
    )

    # Calendar
    ical_product_id: str = Field(default="-//mailassist//EN", description="iCal PRODID for generated events")

    # Rules engine
    rules_max_pattern_length: int = Field(default=500, description="Max regex pattern length for rule matching")
    rules_max_text_length: int = Field(default=51200, description="Max text length (bytes) to search against rules")

    @field_validator("app_secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("APP_SECRET_KEY must be at least 32 characters")
        return v

    @field_validator("app_secret_key_old")
    @classmethod
    def validate_secret_key_old(cls, v: str | None) -> str | None:
        if v is not None and len(v) < 32:
            raise ValueError("APP_SECRET_KEY_OLD must be at least 32 characters")
        return v


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings singleton. Parses .env only on first call."""
    return Settings()  # type: ignore[call-arg]
