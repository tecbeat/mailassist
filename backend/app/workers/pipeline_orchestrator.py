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
    Contact,
    LabelChangeLog,
    MailAccount,
    UserSettings,
)
from app.models.mail import CompletionReason
from app.plugins.base import MailContext, PipelineContext
from app.plugins.registry import get_plugin_registry
from app.services.change_logger import save_new_folders, save_new_labels
from app.services.contacts import match_sender_to_contact
from app.services.email_parser import parse_email
from app.services.imap_actions import execute_imap_actions
from app.services.mail import (
    ParsedEmail,
    fetch_raw_message,
    get_cached_folders,
    imap_connection,
    list_folders,
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
class PipelineResult:
    """Aggregated result of the full pipeline."""

    plugins_executed: list[str] = field(default_factory=list)
    plugins_completed: list[str] = field(default_factory=list)
    plugins_failed: list[str] = field(default_factory=list)
    plugins_skipped: list[str] = field(default_factory=list)
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


# ---------------------------------------------------------------------------
# Pipeline progress tracking (Valkey-backed, ephemeral)
# ---------------------------------------------------------------------------

PROGRESS_KEY_PREFIX = "pipeline:progress:"


def _progress_key(account_id: str, mail_uid: str, current_folder: str = "INBOX") -> str:
    """Build the Valkey key for pipeline progress of a specific mail job."""
    return f"{PROGRESS_KEY_PREFIX}process_mail:{account_id}:{mail_uid}:{current_folder}"


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
) -> None:
    """Write ephemeral pipeline progress to Valkey.

    Called before each plugin and at phase transitions so the dashboard
    can show which step the pipeline is on.  Keys auto-expire after
    ``pipeline_progress_ttl_seconds`` seconds.
    """
    try:
        from app.core.redis import get_task_client

        client = get_task_client()
        value = json.dumps(
            {
                "phase": phase,
                "current_plugin": current_plugin,
                "current_plugin_display": current_plugin_display,
                "plugin_index": plugin_index,
                "plugins_total": plugins_total,
            }
        )
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


class EmailParseError(Exception):
    """Raised when the raw email bytes cannot be parsed.

    This is a permanent error — retrying will not help.
    """


async def fetch_raw_mail(
    account: MailAccount,
    mail_uid: str,
    current_folder: str,
    log: structlog.stdlib.BoundLogger,
) -> tuple[bytes, list[str], str]:
    """Connect to IMAP, download the raw message, list folders.

    Returns:
        Tuple of (raw_bytes, imap_folders, folder_separator).

    Raises:
        IMAPFetchError: Non-OK IMAP response or missing message body.
        Exception: IMAP connection failures (transient).
    """
    async with imap_connection(account) as conn:
        try:
            raw_bytes = await fetch_raw_message(conn, mail_uid, folder=current_folder)
        except ValueError as e:
            if "imap_fetch_failed" in str(e):
                raise IMAPFetchError(str(e)) from e
            raise IMAPFetchError("no_message_body_in_response") from e
        except Exception as e:
            # folder.set() failures indicate missing/deleted folder
            err_msg = str(e).lower()
            if "select" in err_msg or "folder" in err_msg or "mailbox" in err_msg:
                raise IMAPFolderError(
                    f"imap_select_failed: folder '{current_folder}' may have been deleted ({e})"
                ) from e
            raise

        try:
            imap_folders = await get_cached_folders(account.id)
            if imap_folders is None:
                imap_folders = await list_folders(conn)
                await set_cached_folders(account.id, imap_folders)
        except Exception:
            log.warning("folder_list_failed_fallback_empty")
            imap_folders = []

        folder_sep = conn.separator or "/"

    return raw_bytes, imap_folders, folder_sep


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
    # Instead of sending ALL contacts (which can overflow the LLM context
    # window), pre-filter to the most relevant candidates based on email
    # domain and name similarity to the sender.
    user_contacts_data: list[dict[str, Any]] = []
    try:
        sender_email = (parsed.sender or "").lower()
        sender_domain = sender_email.split("@")[-1] if "@" in sender_email else ""
        sender_name = (parsed.sender_name or "").lower().strip()

        # Pre-filter contacts in SQL by email/domain match to avoid loading all contacts
        from sqlalchemy import String as SAString
        from sqlalchemy import cast, or_

        contacts_stmt = select(Contact).where(Contact.user_id == UUID(user_id))
        # Add SQL-level pre-filter: match on sender email or domain in the JSON emails array
        sql_filters = []
        if sender_email:
            sql_filters.append(cast(Contact.emails, SAString).ilike(f"%{sender_email}%"))
        if sender_domain:
            sql_filters.append(cast(Contact.emails, SAString).ilike(f"%{sender_domain}%"))
        if sender_name and len(sender_name) >= 3:
            # Also match on display name for name-based scoring
            sql_filters.append(Contact.display_name.ilike(f"%{sender_name}%"))
        if sql_filters:
            contacts_stmt = contacts_stmt.where(or_(*sql_filters))
        contacts_stmt = contacts_stmt.limit(200)

        contacts_result = await db.execute(contacts_stmt)
        all_contacts = contacts_result.scalars().all()
        # Filter out stopwords and short tokens for name matching
        _NAME_STOPWORDS = {
            "dr",
            "mr",
            "mrs",
            "ms",
            "prof",
            "ing",
            "mag",
            "von",
            "van",
            "de",
            "del",
            "der",
            "die",
            "das",
            "the",
            "and",
            "und",
            "jr",
            "sr",
            "ii",
            "iii",
            "msc",
            "bsc",
            "phd",
            "mba",
        }
        sender_name_parts = (
            {t for t in sender_name.split() if len(t) >= 3 and t not in _NAME_STOPWORDS} if sender_name else set()
        )

        scored: list[tuple[float, Contact]] = []
        for c in all_contacts:
            score = 0.0
            c_emails = [e.lower() for e in (c.emails or [])]
            # Exact email match → highest score
            if sender_email and sender_email in c_emails:
                score += 100.0
            # Same domain → exact domain comparison (not substring)
            elif sender_domain:
                c_domains = {e.split("@")[-1] for e in c_emails if "@" in e}
                if sender_domain in c_domains:
                    score += 10.0
            # Name overlap → score per overlapping token (filtered)
            c_name_parts = {
                t for t in (c.display_name or "").lower().split() if len(t) >= 3 and t not in _NAME_STOPWORDS
            }
            if c.first_name and len(c.first_name) >= 3:
                c_name_parts.add(c.first_name.lower())
            if c.last_name and len(c.last_name) >= 3:
                c_name_parts.add(c.last_name.lower())
            overlap = sender_name_parts & c_name_parts
            score += len(overlap) * 5.0
            # Organization match → exact domain comparison
            if c.organization and sender_domain:
                org_domain = c.organization.lower().replace(" ", "")
                if org_domain == sender_domain.split(".")[0]:
                    score += 8.0
            scored.append((score, c))

        # Sort by score descending, take top 30 but only those with score > 0
        scored.sort(key=lambda x: x[0], reverse=True)
        max_contacts = 30
        for _score, c in scored[:max_contacts]:
            if _score <= 0.0:
                break
            user_contacts_data.append(
                {
                    "id": str(c.id),
                    "display_name": c.display_name,
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "organization": c.organization,
                    "title": c.title,
                    "emails": c.emails,
                }
            )
        if len(all_contacts) > max_contacts:
            log.info(
                "contacts_filtered_for_prompt",
                total=len(all_contacts),
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

    # --- Build mail context ---
    excluded = {f.lower() for f in (account.excluded_folders or [])}
    filtered_folders = [f for f in fetched.imap_folders if f.lower() not in excluded]

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
    )

    # --- Rule evaluation ---
    await _evaluate_rules(db, user_id, account_id, mail_uid, context, event_bus, log)

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

    all_plugins = registry.get_all_plugins()
    if user_settings and user_settings.plugin_order:
        order_map = {name: idx for idx, name in enumerate(user_settings.plugin_order)}
        fallback = len(order_map)
        all_plugins = sorted(all_plugins, key=lambda p: order_map.get(p.name, fallback))

    # Pre-compute pipeline plugins for progress tracking (exclude
    # non-pipeline and explicitly skipped plugins).
    pipeline_plugins = [p for p in all_plugins if p.runs_in_pipeline and not (skip_plugins and p.name in skip_plugins)]
    plugins_total = len(pipeline_plugins)

    try:
        async with db.begin_nested():  # Savepoint
            plugin_index = 0
            for plugin in all_plugins:
                if not plugin.runs_in_pipeline:
                    continue

                if skip_plugins and plugin.name in skip_plugins:
                    log.debug("plugin_skipped_explicitly", plugin=plugin.name)
                    result.plugins_skipped.append(plugin.name)
                    continue

                plugin_index += 1
                await _set_pipeline_progress(
                    account_id,
                    mail_uid,
                    current_folder=current_folder,
                    phase="ai_pipeline",
                    current_plugin=plugin.name,
                    current_plugin_display=plugin.display_name,
                    plugin_index=plugin_index,
                    plugins_total=plugins_total,
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
            )
    except Exception:
        log.exception("rule_evaluation_failed")

    await event_bus.emit(  # type: ignore[attr-defined]
        RulesEvaluatedEvent(
            user_id=UUID(user_id),
            account_id=UUID(account_id),
            mail_uid=mail_uid,
            actions_taken=rule_result.actions_taken if rule_result else [],
        )
    )


def _apply_outcome(result: PipelineResult, outcome: PluginOutcome) -> None:
    """Merge a single plugin outcome into the pipeline result."""
    if outcome.skipped:
        result.plugins_skipped.append(outcome.plugin_name)
        return

    if outcome.executed:
        result.plugins_executed.append(outcome.plugin_name)

    if outcome.completed:
        result.plugins_completed.append(outcome.plugin_name)
    elif outcome.failed:
        result.plugins_failed.append(outcome.plugin_name)

    if outcome.approval_created:
        result.approvals_created += 1

    if outcome.actions_taken:
        result.auto_actions.extend(outcome.actions_taken)

    # Determine completion reason for short-circuits
    if outcome.break_pipeline and outcome.completed:
        result.completion_reason = CompletionReason.SPAM_SHORT_CIRCUIT
