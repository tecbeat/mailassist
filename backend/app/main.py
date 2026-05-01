"""FastAPI application factory with lifespan management.

Initializes all core services on startup and cleans up on shutdown.
Runs Alembic migrations automatically, then ensures any new tables exist.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import (
    ai_providers,
    approvals,
    auth,
    auto_replies,
    calendar,
    calendar_events,
    contacts,
    coupons,
    dashboard,
    folders,
    health,
    labels,
    mail_accounts,
    newsletters,
    notifications,
    pipeline,
    prompts,
    rules,
    spam,
    summaries,
)
from app.api import (
    settings as settings_api,
)
from app.core.config import get_settings
from app.core.database import close_db, init_db
from app.core.events import init_event_bus
from app.core.exceptions import register_exception_handlers
from app.core.middleware import (
    CorrelationIdMiddleware,
    CSRFMiddleware,
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.redis import close_valkey, init_valkey
from app.core.security import init_encryption
from app.core.templating import init_template_engine
from app.plugins.registry import init_plugin_registry

logger = structlog.get_logger()


def _configure_structlog() -> None:
    """Configure structlog for structured JSON logging with secret filtering.

    Bridges Python's stdlib logging through structlog so that third-party
    libraries (uvicorn, ARQ, alembic, SQLAlchemy) all emit the same format.
    """
    import logging

    def _filter_secrets(
        _logger: structlog.types.WrappedLogger,
        _method_name: str,
        event_dict: structlog.types.EventDict,
    ) -> structlog.types.EventDict:
        """Remove sensitive fields from log output."""
        sensitive_keys = {"password", "secret", "api_key", "token", "credentials", "cookie"}
        for key in list(event_dict.keys()):
            if any(s in key.lower() for s in sensitive_keys):
                event_dict[key] = "***REDACTED***"
        return event_dict

    is_debug = get_settings().debug

    # Shared processors for both structlog-native and stdlib log records.
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        _filter_secrets,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # Final renderer depends on debug mode.
    renderer: structlog.types.Processor = (
        structlog.dev.ConsoleRenderer() if is_debug else structlog.processors.JSONRenderer()
    )

    # Configure structlog itself (for structlog.get_logger() callers).
    structlog.configure(
        processors=[
            *shared_processors,
            # Prepare for the stdlib ProcessorFormatter when needed.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(min_level="DEBUG"),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Build a ProcessorFormatter that renders both structlog and stdlib records.
    formatter = structlog.stdlib.ProcessorFormatter(
        # For foreign (stdlib) log records that did not originate from structlog.
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    # Replace the root logger's handler so ALL stdlib loggers go through structlog.
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG if is_debug else logging.INFO)

    # Suppress noisy third-party loggers.
    for name in ("httpcore", "httpx", "hpack", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)

    # Force uvicorn loggers to propagate through the root handler
    # instead of using their own formatters.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True


async def _run_migrations() -> None:
    """Run Alembic migrations, then ensure any new tables exist.

    Runs ``alembic upgrade head`` to apply pending migrations (schema
    changes to existing tables).  Afterwards ``create_all`` is called as a
    safety net to create any brand-new tables that don't have a migration
    yet.
    """
    import os
    from concurrent.futures import ThreadPoolExecutor

    from alembic.config import Config

    # Import all model modules so Base.metadata knows about them
    import app.models  # noqa: F401
    from alembic import command
    from app.core.database import get_engine
    from app.models.base import Base

    # --- Alembic upgrade (runs in thread because env.py uses asyncio.run) ---
    backend_dir = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(backend_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    # Prevent alembic's env.py from resetting our structlog-based logging config.
    alembic_cfg.attributes["skip_file_config"] = True
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    def _upgrade() -> None:
        command.upgrade(alembic_cfg, "head")

    try:
        import asyncio

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as pool:
            await loop.run_in_executor(pool, _upgrade)
        logger.info("alembic_migrations_applied")
    except Exception:
        logger.warning("alembic_migration_failed", exc_info=True)

    # --- Fallback: create any missing tables ---
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_tables_ensured")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan: startup and shutdown hooks."""
    settings = get_settings()

    # Startup
    logger.info("app_starting", app_name=settings.app_name)

    init_db(settings)
    init_valkey(settings)
    init_encryption(settings.app_secret_key, settings.app_secret_key_old)
    init_event_bus()
    init_template_engine()
    init_plugin_registry()

    await _run_migrations()

    logger.info("app_started")

    yield

    # Shutdown
    logger.info("app_shutting_down")
    await close_db()
    await close_valkey()
    logger.info("app_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    _configure_structlog()
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # CORS middleware
    allowed_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security & operational middleware (outermost first)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(RequestLoggingMiddleware)
    application.add_middleware(CSRFMiddleware)
    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(RequestSizeLimitMiddleware)

    # Exception handlers
    register_exception_handlers(application)

    # API routes
    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(mail_accounts.router)
    application.include_router(contacts.router)
    application.include_router(dashboard.router, prefix="/api")
    application.include_router(ai_providers.router)
    application.include_router(prompts.router)
    application.include_router(approvals.router)
    application.include_router(notifications.router)
    application.include_router(calendar.router)
    application.include_router(summaries.router)
    application.include_router(newsletters.router)
    application.include_router(coupons.router)
    application.include_router(labels.router)
    application.include_router(folders.router)
    application.include_router(calendar_events.router)
    application.include_router(auto_replies.router)
    application.include_router(rules.router)
    application.include_router(settings_api.router)
    application.include_router(spam.router)
    application.include_router(pipeline.router)

    # Serve frontend static files (if built)
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        # Serve actual static assets (JS, CSS, images)
        application.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="static-assets")

        # SPA fallback: serve index.html for any non-API path
        index_html = static_dir / "index.html"

        @application.get("/{full_path:path}")
        async def spa_fallback(request: Request, full_path: str) -> FileResponse:
            """Serve index.html for client-side routing (SPA fallback)."""
            # Serve actual files if they exist (e.g. favicon.ico)
            file_path = static_dir / full_path
            if full_path and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(index_html)

    return application


# ASGI entry point
app = create_app()
