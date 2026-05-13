"""Pipeline orchestration for email processing.

Coordinates the four phases of the mail processing pipeline:

1. **Account fetch** — load the mail account from the database.
2. **IMAP fetch + parse** — connect to IMAP, download the raw message,
   parse headers/body, list folders.
3. **AI pipeline** — contact matching, rule evaluation, iterate enabled
   plugins via :mod:`plugin_executor`.
4. **Post-pipeline** — execute IMAP actions (moves, label changes),
   persist label/folder change logs, emit completion events.

Called by :func:`mail_processor.process_mail`, the ARQ task entry point.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_session_ctx
from app.core.events import (
    ContactMatchedEvent,
    MailParsedEvent,
    RulesEvaluatedEvent,
    get_event_bus,
)
from app.models import (
    AIProvider,
    CalDAVConfig,
    LabelChangeLog,
    MailAccount,
    TrackedEmail,
    UserSettings,
)
from app.models.mail import CompletionReason
from app.plugins.base import MailContext, PipelineContext
from app.plugins.registry import get_plugin_registry
from app.services.change_logger import save_new_folders, save_new_labels
from app.services.contacts import match_sender_to_contact
from app.services.contacts.matching import find_relevant_contacts_for_sender
from app.services.email_parser import parse_email
from app.services.header_analysis import analyze_headers
from app.services.imap_actions import execute_imap_actions
from app.services.mail import (
    ParsedEmail,
    RelocatedMail,
    fetch_raw_message,
    get_cached_folders,
    imap_connection,
    list_folders,
    relocate_mail_across_folders,
    set_cached_folders,
)
from app.services.provider_resolver import get_default_provider
from app.workers.plugin_executor import PluginOutcome, execute_plugin

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Result container returned to the entry point
# ---------------------------------------------------------------------------


@dataclass
class PluginResultEntry:
    """Summary of a single plugin's execution result."""

    status: str  # "completed", "failed", "skipped", "warning"
    display_name: str
    summary: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        d: dict[str, Any] = {"status": self.status, "display_name": self.display_name}
        if self.summary is not None:
            d["summary"] = self.summary
        if self.details is not None:
            d["details"] = self.details
        return d


@dataclass
class PipelineResult:
    """Aggregated result of the full pipeline."""

    plugins_executed: list[str] = field(default_factory=list)
    plugins_completed: list[str] = field(default_factory=list)
    plugins_failed: list[str] = field(default_factory=list)
    plugins_skipped: list[str] = field(default_factory=list)
    plugin_results: dict[str, PluginResultEntry] = field(default_factory=dict)
    approvals_created: int = 0
    auto_actions: list[str] = field(default_factory=list)
    completion_reason: CompletionReason | None = None
    transient_reenqueue_reason: str | None = None
    current_folder: str = "INBOX"
    # True when the pipeline encountered a provider error (transient
    # LLM failure, provider unavailable/inactive/paused).  All plugin
    # results have been rolled back via savepoint.  The mail must NOT
    # be marked completed — it stays QUEUED until the provider recovers.
    provider_error: bool = False
    # ID of the provider that caused a transient error (used by
    # mail_processor to pause the correct provider).
    failed_provider_id: str | None = None
    # UUID of the TrackedEmail aggregate (used for mail_id FK in events).
    mail_id: UUID | None = None


# ---------------------------------------------------------------------------
# Pipeline progress tracking (Valkey-backed, ephemeral)
# ---------------------------------------------------------------------------

PROGRESS_KEY_PREFIX = "pipeline:progress:"
CANCEL_KEY_PREFIX = "pipeline:cancel:"


def _progress_key(account_id: str, mail_uid: str, current_folder: str = "INBOX") -> str:
    """Build the Valkey key for pipeline progress of a specific mail job."""
    return f"{PROGRESS_KEY_PREFIX}process_mail:{account_id}:{mail_uid}:{current_folder}"


def _cancel_key(account_id: str, mail_uid: str, current_folder: str = "INBOX") -> str:
    """Build the Valkey key for pipeline cancellation of a specific mail job."""
    return f"{CANCEL_KEY_PREFIX}process_mail:{account_id}:{mail_uid}:{current_folder}"


async def _is_cancelled(account_id: str, mail_uid: str, current_folder: str) -> bool:
    """Check whether this pipeline run has been cancelled by the user."""
    try:
        from app.core.redis import get_task_client

        client = get_task_client()
        return bool(await client.exists(_cancel_key(account_id, mail_uid, current_folder)))
    except Exception:
        return False


async def _set_pipeline_progress(
    account_id: str,
    mail_uid: str,
    *,
    current_folder: str = "INBOX",
    phase: str,
    current_plugin: str | None = None,
    current_plugin_display: str | None = None,
    plugin_index: int | None = None,
    plugins_total: int | None = None,
    plugin_names: list[dict[str, str]] | None = None,
    plugin_results: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Write ephemeral pipeline progress to Valkey.

    Called before each plugin and at phase transitions so the dashboard
    can show which step the pipeline is on.  Keys auto-expire after
    ``pipeline_progress_ttl_seconds`` seconds.
    """
    try:
        from app.core.redis import get_task_client

        client = get_task_client()
        payload: dict[str, Any] = {
            "phase": phase,
            "current_plugin": current_plugin,
            "current_plugin_display": current_plugin_display,
            "plugin_index": plugin_index,
            "plugins_total": plugins_total,
        }
        if plugin_names is not None:
            payload["plugin_names"] = plugin_names
        if plugin_results is not None:
            payload["plugin_results"] = plugin_results
        value = json.dumps(payload)
        await client.set(
            _progress_key(account_id, mail_uid, current_folder),
            value,
            ex=get_settings().pipeline_progress_ttl_seconds,
        )
    except Exception:
        # Progress tracking is best-effort — never block the pipeline
        pass


async def _clear_pipeline_progress(
    account_id: str,
    mail_uid: str,
    current_folder: str = "INBOX",
) -> None:
    """Remove the pipeline progress key when processing completes."""
    try:
        from app.core.redis import get_task_client

        client = get_task_client()
        await client.delete(_progress_key(account_id, mail_uid, current_folder))
        await client.delete(_cancel_key(account_id, mail_uid, current_folder))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Phase 1 — Account fetch
# ---------------------------------------------------------------------------


async def fetch_account(
    user_id: str,
    account_id: str,
    log: structlog.stdlib.BoundLogger,
) -> MailAccount | None:
    """Load the mail account from the database.

    Returns:
        The ``MailAccount`` or ``None`` when not found.
    """
    account: MailAccount | None = None

    async with get_session_ctx() as db:
        stmt = select(MailAccount).where(
            MailAccount.id == UUID(account_id),
            MailAccount.user_id == UUID(user_id),
        )
        result = await db.execute(stmt)
        account = result.scalar_one_or_none()

    return account


# ---------------------------------------------------------------------------
# Phase 2 — IMAP fetch + parse
# ---------------------------------------------------------------------------


@dataclass
class FetchedMail:
    """Raw IMAP data + parsed result."""

    parsed: ParsedEmail
    raw_bytes: bytes
    imap_folders: list[str]
    folder_separator: str


class IMAPFetchError(Exception):
    """Raised when the IMAP fetch fails (non-OK or missing body)."""


class IMAPFolderError(Exception):
    """Raised when an IMAP folder cannot be selected (deleted/renamed)."""


class UIDNotFoundError(Exception):
    """Raised when a UID no longer exists in its folder.

    This typically happens when a server-side Sieve filter moves the
    mail before the worker can fetch it.  The caller should attempt
    relocation via :func:`~app.services.mail.relocate_mail_across_folders`.
    """


class EmailParseError(Exception):
    """Raised when the raw email bytes cannot be parsed.

    This is a permanent error — retrying will not help.
    """


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Result of IMAP fetch with optional relocation info.

    When a UID is not found in the expected folder and the mail is
    successfully relocated, ``relocated`` is ``True`` and ``new_folder``
    / ``new_uid`` contain the updated coordinates.
    """

    raw_bytes: bytes
    imap_folders: list[str]
    folder_separator: str
    relocated: bool = False
    new_folder: str | None = None
    new_uid: str | None = None


async def fetch_raw_mail(
    account: MailAccount,
    mail_uid: str,
    current_folder: str,
    log: structlog.stdlib.BoundLogger,
    *,
    subject_hint: str | None = None,
) -> FetchResult:
    """Connect to IMAP, download the raw message, list folders.

    When the UID is not found (moved by server-side filter), attempts
    to relocate the mail across all folders using the subject hint.

    Args:
        subject_hint: Subject of the mail (from TrackedEmail) used for
            relocation search when the UID no longer exists.

    Returns:
        A ``FetchResult`` containing raw bytes, folder list, and
        optional relocation info.

    Raises:
        IMAPFetchError: Non-OK IMAP response or missing message body.
        UIDNotFoundError: UID not found and relocation failed/not attempted.
        IMAPFolderError: Folder cannot be selected.
        Exception: IMAP connection failures (transient).
    """
    async with imap_connection(account) as conn:
        relocated: RelocatedMail | None = None
        raw_bytes: bytes | None = None

        try:
            raw_bytes = await fetch_raw_message(conn, mail_uid, folder=current_folder)
        except ValueError as e:
            error_msg = str(e)
            if "uid_not_found_in_folder" in error_msg:
                # UID vanished — attempt relocation by subject search
                if subject_hint:
                    log.info(
                        "uid_not_found_attempting_relocation",
                        mail_uid=mail_uid,
                        folder=current_folder,
                        subject=subject_hint[:80],
                    )
                    relocated = await relocate_mail_across_folders(
                        conn,
                        subject_hint,
                        current_folder,
                    )
                if relocated is None:
                    raise UIDNotFoundError(
                        f"uid_not_found_in_folder: UID {mail_uid} no longer in '{current_folder}'"
                        + (" and relocation failed" if subject_hint else " (no subject for relocation)")
                    ) from e
                raw_bytes = relocated.raw_bytes
            elif "imap_fetch_failed" in error_msg:
                raise IMAPFetchError(error_msg) from e
            else:
                raise IMAPFetchError("no_message_body_in_response") from e
        except Exception as e:
            # folder.set() failures indicate missing/deleted folder
            err_msg = str(e).lower()
            if "select" in err_msg or "folder" in err_msg or "mailbox" in err_msg:
                raise IMAPFolderError(
                    f"imap_select_failed: folder '{current_folder}' may have been deleted ({e})"
                ) from e
            raise

        assert raw_bytes is not None

        try:
            imap_folders = await get_cached_folders(account.id)
            if imap_folders is None:
                imap_folders = await list_folders(conn)
                await set_cached_folders(account.id, imap_folders)
        except Exception:
            log.warning("folder_list_failed_fallback_empty")
            imap_folders = []

        folder_sep = conn.separator or "/"

    if relocated:
        return FetchResult(
            raw_bytes=raw_bytes,
            imap_folders=imap_folders,
            folder_separator=folder_sep,
            relocated=True,
            new_folder=relocated.folder,
            new_uid=relocated.uid,
        )

    return FetchResult(
        raw_bytes=raw_bytes,
        imap_folders=imap_folders,
        folder_separator=folder_sep,
    )


def parse_raw_mail(
    raw_bytes: bytes,
    mail_uid: str,
    log: structlog.stdlib.BoundLogger,
) -> ParsedEmail:
    """Parse raw email bytes into a structured representation.

    Raises:
        EmailParseError: The raw bytes are unparseable (permanent).
    """
    try:
        parsed = parse_email(raw_bytes, mail_uid)
    except Exception as e:
        raise EmailParseError(f"email_parse_failed: {e}") from e
    log.info("mail_parsed", subject=parsed.subject, sender=parsed.sender)
    if not parsed.body_plain and not parsed.body_html:
        log.info(
            "mail_body_empty",
            subject=parsed.subject,
            sender=parsed.sender,
            size=parsed.size,
        )
    return parsed


# ---------------------------------------------------------------------------
# Phase 3 — AI pipeline
# ---------------------------------------------------------------------------


async def run_ai_pipeline(
    *,
    db: AsyncSession,
    user_id: str,
    account_id: str,
    mail_uid: str,
    current_folder: str = "INBOX",
    account: MailAccount,
    fetched: FetchedMail,
    skip_plugins: list[str] | None,
    log: structlog.stdlib.BoundLogger,
) -> PipelineResult:
    """Run contact matching, rules, and all enabled plugins.

    This is the core Phase 3 of the processing pipeline.  It operates
    within the caller-provided DB session (the caller commits).
    """
    result = PipelineResult()
    parsed = fetched.parsed
    event_bus = get_event_bus()

    await event_bus.emit(
        MailParsedEvent(
            user_id=UUID(user_id),
            account_id=UUID(account_id),
            mail_uid=mail_uid,
            sender=parsed.sender,
            subject=parsed.subject,
        )
    )

    # --- Contact matching ---
    contact_data = await _match_contact(db, user_id, account_id, mail_uid, parsed, event_bus, log)

    # --- Load relevant user contacts for AI contact assignment plugin ---
    # Pre-filter and score contacts by relevance to the sender to avoid
    # overflowing the LLM context window.
    user_contacts_data: list[dict[str, Any]] = []
    try:
        user_contacts_data = await find_relevant_contacts_for_sender(
            db,
            UUID(user_id),
            parsed.sender or "",
            parsed.sender_name,
        )
        if len(user_contacts_data) > 0:
            log.info(
                "contacts_filtered_for_prompt",
                included=len(user_contacts_data),
            )
    except Exception:
        log.warning("user_contacts_load_failed")

    # --- Fetch existing labels ---
    existing_labels_stmt = (
        select(LabelChangeLog.label)
        .where(
            LabelChangeLog.user_id == UUID(user_id),
            LabelChangeLog.mail_account_id == UUID(account_id),
        )
        .distinct()
    )
    existing_labels_result = await db.execute(existing_labels_stmt)
    existing_labels = [row[0] for row in existing_labels_result.all()]

    # --- Resolve mail aggregate ID ---
    tracked_stmt = select(TrackedEmail.id).where(
        TrackedEmail.mail_account_id == UUID(account_id),
        TrackedEmail.mail_uid == mail_uid,
    )
    tracked_result = await db.execute(tracked_stmt)
    tracked_email_id = tracked_result.scalar_one_or_none()

    # --- Build mail context ---
    excluded = {f.lower() for f in (account.excluded_folders or [])}
    filtered_folders = [f for f in fetched.imap_folders if f.lower() not in excluded]

    # --- Extract technical indicators from headers ---
    technical_indicators = analyze_headers(
        headers=parsed.headers,
        sender_email=parsed.sender,
        sender_name=parsed.sender_name,
    )

    context = MailContext(
        user_id=user_id,
        account_id=account_id,
        mail_uid=mail_uid,
        sender=parsed.sender,
        sender_name=parsed.sender_name,
        recipient=parsed.recipient,
        subject=parsed.subject,
        body=parsed.body_plain or parsed.body_html,
        body_plain=parsed.body_plain,
        body_html=parsed.body_html,
        headers=parsed.headers,
        date=parsed.date.isoformat() if parsed.date else "",
        has_attachments=parsed.has_attachments,
        attachment_names=parsed.attachment_names,
        account_name=account.name,
        account_email=account.email_address,
        existing_labels=existing_labels,
        existing_folders=filtered_folders,
        excluded_folders=account.excluded_folders or [],
        folder_separator=fetched.folder_separator,
        mail_size=parsed.size,
        thread_length=1,
        is_reply=parsed.is_reply,
        is_forwarded=parsed.is_forwarded,
        contact=contact_data,
        user_contacts=user_contacts_data,
        technical_indicators=technical_indicators,
        mail_id=str(tracked_email_id) if tracked_email_id else None,
    )

    result.mail_id = tracked_email_id

    # --- Load CalDAV config for calendar past-events setting ---
    caldav_stmt = select(CalDAVConfig).where(CalDAVConfig.user_id == UUID(user_id))
    caldav_result = await db.execute(caldav_stmt)
    caldav_config = caldav_result.scalar_one_or_none()
    if caldav_config:
        context.calendar_include_past_events = caldav_config.include_past_events

    # --- Rule evaluation ---
    await _evaluate_rules(db, user_id, account_id, mail_uid, context, event_bus, log, result)

    # --- Resolve providers ---
    default_provider = await get_default_provider(db, UUID(user_id))

    settings_stmt = select(UserSettings).where(UserSettings.user_id == UUID(user_id))
    settings_result = await db.execute(settings_stmt)
    user_settings = settings_result.scalar_one_or_none()

    plugin_provider_map = (user_settings.plugin_provider_map or {}) if user_settings else {}
    all_providers_stmt = select(AIProvider).where(AIProvider.user_id == UUID(user_id))
    all_providers_result = await db.execute(all_providers_stmt)
    providers_by_id = {str(p.id): p for p in all_providers_result.scalars().all()}

    if not providers_by_id:
        log.warning("no_ai_provider_configured", reason="skipping_ai_pipeline")
        return result

    # --- Iterate plugins inside a savepoint ---
    #
    # All plugin results are persisted within a database savepoint.
    # On provider error (transient LLM failure), the savepoint is
    # rolled back so that no partial results remain — all or nothing.
    # On mail-specific plugin errors, a manual-input approval is
    # created and the pipeline continues with remaining plugins.
    registry = get_plugin_registry()
    pipeline = PipelineContext()
    pipeline.set_result("header_analysis", technical_indicators)

    all_plugins = registry.get_all_plugins()
    if user_settings and user_settings.plugin_order:
        order_map = {name: idx for idx, name in enumerate(user_settings.plugin_order)}
        fallback = len(order_map)
        all_plugins = sorted(all_plugins, key=lambda p: order_map.get(p.name, fallback))

    # Pre-compute pipeline plugins for progress tracking (exclude
    # non-pipeline and explicitly skipped plugins).
    pipeline_plugins = [p for p in all_plugins if p.runs_in_pipeline and not (skip_plugins and p.name in skip_plugins)]
    plugins_total = len(pipeline_plugins)
    plugin_names_list = [{"name": p.name, "display_name": p.display_name} for p in pipeline_plugins]

    try:
        async with db.begin_nested():  # Savepoint
            plugin_index = 0
            for plugin in all_plugins:
                if not plugin.runs_in_pipeline:
                    continue

                if skip_plugins and plugin.name in skip_plugins:
                    log.debug("plugin_skipped_explicitly", plugin=plugin.name)
                    result.plugins_skipped.append(plugin.name)
                    result.plugin_results[plugin.name] = PluginResultEntry(
                        status="skipped",
                        display_name=plugin.display_name,
                        summary="Skipped (explicitly excluded)",
                    )
                    continue

                plugin_index += 1

                # Check for user-initiated cancellation between plugins
                if await _is_cancelled(account_id, mail_uid, current_folder):
                    log.info("pipeline_cancelled_by_user", plugin=plugin.name)
                    result.completion_reason = CompletionReason.CANCELLED
                    break

                await _set_pipeline_progress(
                    account_id,
                    mail_uid,
                    current_folder=current_folder,
                    phase="ai_pipeline",
                    current_plugin=plugin.name,
                    current_plugin_display=plugin.display_name,
                    plugin_index=plugin_index,
                    plugins_total=plugins_total,
                    plugin_names=plugin_names_list,
                    plugin_results={k: v.to_dict() for k, v in result.plugin_results.items()} or None,
                )

                try:
                    outcome = await execute_plugin(
                        db=db,
                        plugin=plugin,
                        context=context,
                        pipeline=pipeline,
                        user_settings=user_settings,  # type: ignore[arg-type]
                        plugin_provider_map=plugin_provider_map,
                        providers_by_id=providers_by_id,
                        default_provider=default_provider,
                        log=log,
                    )
                except Exception as exc:
                    log.exception("plugin_execution_failed", plugin=plugin.name)
                    result.plugins_failed.append(plugin.name)
                    result.plugin_results[plugin.name] = PluginResultEntry(
                        status="failed",
                        display_name=plugin.display_name,
                        summary=f"Unhandled error: {exc}",
                    )
                    # Update progress with accumulated results
                    await _set_pipeline_progress(
                        account_id,
                        mail_uid,
                        current_folder=current_folder,
                        phase="ai_pipeline",
                        current_plugin=plugin.name,
                        current_plugin_display=plugin.display_name,
                        plugin_index=plugin_index,
                        plugins_total=plugins_total,
                        plugin_names=plugin_names_list,
                        plugin_results={k: v.to_dict() for k, v in result.plugin_results.items()},
                    )
                    # Create manual_input approval for unhandled exception
                    try:
                        from app.workers.plugin_executor import _create_manual_input_approval

                        await _create_manual_input_approval(
                            db,
                            user_id=UUID(user_id),
                            account_id=UUID(account_id),
                            plugin=plugin,
                            context=context,
                            error=str(exc),
                        )
                        result.approvals_created += 1
                    except Exception:
                        log.exception("manual_input_approval_creation_failed", plugin=plugin.name)
                    continue

                _apply_outcome(result, outcome)

                # Update progress with accumulated plugin results
                await _set_pipeline_progress(
                    account_id,
                    mail_uid,
                    current_folder=current_folder,
                    phase="ai_pipeline",
                    current_plugin=plugin.name,
                    current_plugin_display=plugin.display_name,
                    plugin_index=plugin_index,
                    plugins_total=plugins_total,
                    plugin_names=plugin_names_list,
                    plugin_results={k: v.to_dict() for k, v in result.plugin_results.items()},
                )

                if outcome.skip_reason == "no_user_settings":
                    log.warning("no_user_settings", reason="skipping_all_plugins")
                    break

                if outcome.transient_error:
                    # Provider error — roll back all plugin results
                    # persisted so far by raising out of the savepoint.
                    result.transient_reenqueue_reason = outcome.transient_error_reason
                    result.failed_provider_id = outcome.failed_provider_id
                    result.provider_error = True
                    log.warning(
                        "provider_error_rollback",
                        plugin=outcome.plugin_name,
                        provider_id=outcome.failed_provider_id,
                        reason=outcome.transient_error_reason,
                    )
                    raise _SavepointRollback()

                if outcome.break_pipeline:
                    break

    except _SavepointRollback:
        # Savepoint was rolled back — all plugin DB writes discarded.
        # Clear result lists that are no longer accurate after rollback.
        result.plugins_executed.clear()
        result.plugins_completed.clear()
        result.plugins_failed.clear()
        result.approvals_created = 0
        result.auto_actions.clear()
        return result

    # Transaction is committed by the caller via get_session_ctx() — no
    # explicit commit here to avoid a double-commit.
    return result


# ---------------------------------------------------------------------------
# Phase 4 — Post-pipeline IMAP actions
# ---------------------------------------------------------------------------


async def execute_post_pipeline(
    *,
    account: MailAccount,
    account_id: str,
    mail_uid: str,
    current_folder: str,
    auto_actions: list[str],
    user_id: str,
    log: structlog.stdlib.BoundLogger,
) -> tuple[str, str | None]:
    """Execute IMAP actions and persist label/folder change logs.

    Returns a tuple of (updated_current_folder, new_mail_uid).
    ``new_mail_uid`` is the UID assigned in the destination folder after
    an IMAP MOVE, or ``None`` if no move occurred or the server did not
    return a COPYUID response.
    """
    await save_new_labels(
        user_id=UUID(user_id),
        account_id=UUID(account_id),
        actions=auto_actions,
    )
    await save_new_folders(
        user_id=UUID(user_id),
        account_id=UUID(account_id),
        actions=auto_actions,
    )

    # Re-check account is still active
    async with get_session_ctx() as db:
        stmt = select(MailAccount).where(
            MailAccount.id == UUID(account_id),
            MailAccount.is_paused.is_(False),
        )
        result = await db.execute(stmt)
        account_check = result.scalar_one_or_none()

    if account_check is None:
        log.warning(
            "phase4_account_deactivated",
            msg="Skipping IMAP actions — account was deactivated during processing",
        )
        return current_folder, None

    move_outcome = await execute_imap_actions(
        account,
        mail_uid,
        auto_actions,
        source_folder=current_folder,
    )
    if move_outcome.folder:
        return move_outcome.folder, move_outcome.new_uid

    return current_folder, None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _SavepointRollback(Exception):
    """Raised inside the savepoint context to trigger a rollback.

    This is a control-flow exception — it is caught immediately after
    the ``async with db.begin_nested():`` block and never propagates
    to callers.
    """


async def _match_contact(
    db: AsyncSession,
    user_id: str,
    account_id: str,
    mail_uid: str,
    parsed: ParsedEmail,
    event_bus: object,
    log: structlog.stdlib.BoundLogger,
) -> dict[str, Any] | None:
    """Match sender to a contact; return contact dict or None."""
    contact_data: dict[str, Any] | None = None
    try:
        async with db.begin_nested():
            matched_contact = await match_sender_to_contact(db, UUID(user_id), parsed.sender)
            if matched_contact:
                contact_data = {
                    "id": str(matched_contact.id),
                    "display_name": matched_contact.display_name,
                    "first_name": matched_contact.first_name,
                    "last_name": matched_contact.last_name,
                    "organization": matched_contact.organization,
                    "title": matched_contact.title,
                    "emails": matched_contact.emails,
                    "phones": matched_contact.phones,
                }
                await event_bus.emit(  # type: ignore[attr-defined]
                    ContactMatchedEvent(
                        user_id=UUID(user_id),
                        account_id=UUID(account_id),
                        mail_uid=mail_uid,
                        contact_id=matched_contact.id,
                    )
                )
    except Exception:
        log.warning("contact_match_failed", sender=parsed.sender)
    return contact_data


async def _evaluate_rules(
    db: AsyncSession,
    user_id: str,
    account_id: str,
    mail_uid: str,
    context: MailContext,
    event_bus: object,
    log: structlog.stdlib.BoundLogger,
    result: PipelineResult,
) -> None:
    """Evaluate user rules before the AI pipeline."""
    from app.services.rules import evaluate_rules

    rule_result = None
    try:
        async with db.begin_nested():
            rule_result = await evaluate_rules(db, UUID(user_id), UUID(account_id), context)
            log.info(
                "rules_evaluated",
                matched=len(rule_result.matched_rule_ids),
                actions=rule_result.actions_taken,
                imap_actions=rule_result.imap_actions,
            )
    except Exception:
        log.exception("rule_evaluation_failed")

    if rule_result and rule_result.imap_actions:
        result.auto_actions.extend(rule_result.imap_actions)

    await event_bus.emit(  # type: ignore[attr-defined]
        RulesEvaluatedEvent(
            user_id=UUID(user_id),
            account_id=UUID(account_id),
            mail_uid=mail_uid,
            actions_taken=rule_result.actions_taken if rule_result else [],
            mail_id=UUID(context.mail_id) if context.mail_id else None,
        )
    )


def _apply_outcome(result: PipelineResult, outcome: PluginOutcome) -> None:
    """Merge a single plugin outcome into the pipeline result."""
    if outcome.skipped:
        result.plugins_skipped.append(outcome.plugin_name)
        result.plugin_results[outcome.plugin_name] = PluginResultEntry(
            status="skipped",
            display_name=outcome.plugin_display_name,
            summary=f"Skipped: {outcome.skip_reason or 'disabled'}",
        )
        return

    if outcome.executed:
        result.plugins_executed.append(outcome.plugin_name)

    if outcome.completed:
        result.plugins_completed.append(outcome.plugin_name)
        details = outcome.result_details
        if outcome.auto_approved:
            details = {**(details or {}), "auto_approved": True}
        result.plugin_results[outcome.plugin_name] = PluginResultEntry(
            status="completed",
            display_name=outcome.plugin_display_name,
            summary=outcome.result_summary,
            details=details,
        )
    elif outcome.failed:
        result.plugins_failed.append(outcome.plugin_name)
        status = "warning" if outcome.transient_error else "failed"
        result.plugin_results[outcome.plugin_name] = PluginResultEntry(
            status=status,
            display_name=outcome.plugin_display_name,
            summary=outcome.transient_error_reason or "Plugin failed",
        )

    if outcome.approval_created:
        result.approvals_created += 1

    if outcome.actions_taken:
        result.auto_actions.extend(outcome.actions_taken)

    # Determine completion reason for short-circuits
    if outcome.break_pipeline and outcome.completed:
        result.completion_reason = CompletionReason.SPAM_SHORT_CIRCUIT
