"""Contacts API endpoints.

Provides CardDAV configuration, contact browsing, search, manual sync,
and email assignment to contacts.
"""

import json
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.api.deps import CurrentUserId, DbSession, build_paginated_response, get_or_404, paginate, sanitize_like
from app.core.redis import get_cache_client
from app.core.security import get_encryption
from app.models import CardDAVConfig, Contact, ContactAssignment, EmailSummary, UserSettings
from app.schemas.contacts import (
    AssignEmailRequest,
    AssignEmailResponse,
    CardDAVConfigCreate,
    CardDAVConfigResponse,
    CardDAVTestRequest,
    CardDAVTestResult,
    ContactCreateRequest,
    ContactExtractedData,
    ContactExtractRequest,
    ContactListResponse,
    ContactMailsResponse,
    ContactResponse,
    RemoveEmailRequest,
    RemoveEmailResponse,
    SenderResponse,
    SyncResult,
)
from app.schemas.contacts import (
    ContactAssignmentResponse as ContactAssignmentSchema,
)
from app.services.contacts import (
    remove_email_from_contact,
    sync_contacts,
    test_carddav_connection,
    write_back_email_to_contact,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


# --- CardDAV Config ---


@router.get("/config")
async def get_config(
    db: DbSession,
    user_id: CurrentUserId,
) -> CardDAVConfigResponse | None:
    """Get the current user's CardDAV configuration (credentials excluded).

    Returns ``None`` (HTTP 200 with ``null`` body) when no config exists.
    This is intentional: ``null`` tells the frontend "not configured yet"
    and renders the setup form, whereas a 404 would trigger an error state.
    """
    stmt = select(CardDAVConfig).where(CardDAVConfig.user_id == UUID(user_id))
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if config is None:
        return None
    return CardDAVConfigResponse.model_validate(config)


@router.put("/config")
async def upsert_config(
    data: CardDAVConfigCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> CardDAVConfigResponse:
    """Create or update CardDAV configuration with encrypted credentials."""
    encryption = get_encryption()
    uid = UUID(user_id)

    stmt = select(CardDAVConfig).where(CardDAVConfig.user_id == uid)
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    # Only re-encrypt credentials if both username and password are provided.
    # When editing, empty credentials mean "keep existing".
    has_new_credentials = bool(data.username and data.password)

    if config is None:
        # Creating new config: credentials are required
        if not has_new_credentials:
            raise HTTPException(status_code=422, detail="Username and password are required for initial setup")
        credentials_json = json.dumps({"username": data.username, "password": data.password})
        encrypted = encryption.encrypt(credentials_json)
        config = CardDAVConfig(
            user_id=uid,
            carddav_url=data.carddav_url,
            encrypted_credentials=encrypted,
            address_book=data.address_book,
            sync_interval=data.sync_interval,
        )
        db.add(config)
    else:
        config.carddav_url = data.carddav_url
        config.address_book = data.address_book
        config.sync_interval = data.sync_interval
        if has_new_credentials:
            credentials_json = json.dumps({"username": data.username, "password": data.password})
            config.encrypted_credentials = encryption.encrypt(credentials_json)
        # else: preserve existing encrypted_credentials

    await db.flush()
    logger.info("carddav_config_saved", user_id=user_id)

    # Trigger an immediate sync after saving config
    try:
        stats = await sync_contacts(db, config)
        logger.info("carddav_auto_sync_after_save", user_id=user_id, stats=stats)
    except Exception:
        logger.warning("carddav_auto_sync_after_save_failed", user_id=user_id, exc_info=True)

    return CardDAVConfigResponse.model_validate(config)


@router.post("/config/test")
async def test_config(
    data: CardDAVTestRequest,
    user_id: CurrentUserId,
) -> CardDAVTestResult:
    """Test a CardDAV connection before saving configuration."""
    try:
        result = await test_carddav_connection(
            data.carddav_url,
            data.username,
            data.password,
            data.address_book,
        )
    except Exception as e:
        logger.error("carddav_test_failed", error=str(e))
        raise HTTPException(status_code=502, detail="CardDAV connection test failed") from None
    return CardDAVTestResult(success=result.success, message=result.message, details=result.details)


# --- Contact Sync ---


@router.post("/sync")
async def trigger_sync(
    db: DbSession,
    user_id: CurrentUserId,
) -> SyncResult:
    """Trigger a manual contact sync from CardDAV.

    Uses the stored CardDAV configuration. Performs full re-sync
    if no sync-token exists, otherwise incremental.
    """
    uid = UUID(user_id)
    stmt = select(CardDAVConfig).where(CardDAVConfig.user_id == uid, CardDAVConfig.is_active.is_(True))
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if config is None:
        raise HTTPException(status_code=404, detail="No active CardDAV configuration found")

    try:
        stats = await sync_contacts(db, config)
    except Exception as e:
        logger.error("contact_sync_failed", user_id=user_id, error=str(e))
        raise HTTPException(status_code=502, detail="Contact sync failed") from None
    return SyncResult(**stats)


# --- Contacts ---


@router.get("")
async def list_contacts(
    db: DbSession,
    user_id: CurrentUserId,
    search: str | None = Query(default=None, max_length=200, description="Search by name, email, or organization"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
) -> ContactListResponse:
    """List cached contacts with optional search and pagination."""
    uid = UUID(user_id)
    base_stmt = select(Contact).where(Contact.user_id == uid)

    if search:
        pattern = f"%{sanitize_like(search)}%"
        base_stmt = base_stmt.where(
            or_(
                Contact.display_name.ilike(pattern),
                Contact.first_name.ilike(pattern),
                Contact.last_name.ilike(pattern),
                Contact.organization.ilike(pattern),
            )
        )

    base_stmt = base_stmt.order_by(Contact.display_name)
    result = await paginate(db, base_stmt, page, per_page)

    return build_paginated_response(result, ContactResponse, ContactListResponse)


# --- All Senders ---


@router.get("/senders")
async def list_all_senders(
    db: DbSession,
    user_id: CurrentUserId,
    search: str = Query(default="", max_length=200),
    matched: bool | None = Query(
        default=None, description="Filter by match status: true=matched, false=unmatched, omit=all"
    ),
) -> list[SenderResponse]:
    """List unique email addresses: senders from emails AND contact emails.

    Returns every unique ``mail_from`` from ``email_summaries`` for this
    user, together with the mail count and the contact ID if the sender
    is already assigned to a contact.  Additionally includes all email
    addresses stored in contacts that have never appeared as a sender
    (with ``mail_count=0``), so the matching UI always shows the full
    picture.

    Use ``matched=false`` to get only unmatched senders,
    ``matched=true`` for only matched ones, or omit for all.
    """
    uid = UUID(user_id)
    search_term = search.strip().lower()

    # All unique senders with mail count
    stmt = (
        select(
            func.lower(EmailSummary.mail_from).label("email_address"),
            func.count().label("mail_count"),
        )
        .where(
            EmailSummary.user_id == uid,
            EmailSummary.mail_from.isnot(None),
            EmailSummary.mail_from != "",
        )
        .group_by(func.lower(EmailSummary.mail_from))
        .order_by(func.count().desc())
    )

    if search_term:
        stmt = stmt.where(func.lower(EmailSummary.mail_from).contains(search_term))

    result = await db.execute(stmt)
    rows = result.all()

    # Build a lookup: lowered email -> contact ID from all contacts
    contacts_stmt = select(Contact).where(Contact.user_id == uid)
    contacts_result = await db.execute(contacts_stmt)
    contacts = contacts_result.scalars().all()

    email_to_contact: dict[str, UUID] = {}
    for contact in contacts:
        for email in contact.emails or []:
            if not email or not email.strip():
                continue
            email_to_contact[email.lower()] = contact.id

    # Start with sender rows from email_summaries
    seen_emails: set[str] = set()
    senders: list[SenderResponse] = []
    for row in rows:
        contact_id = email_to_contact.get(row.email_address)
        if matched is True and contact_id is None:
            seen_emails.add(row.email_address)
            continue
        if matched is False and contact_id is not None:
            seen_emails.add(row.email_address)
            continue
        seen_emails.add(row.email_address)
        senders.append(
            SenderResponse(
                email_address=row.email_address,
                mail_count=row.mail_count,
                matched_contact_id=contact_id,
            )
        )

    # Append contact emails that never appeared as a sender (skip if matched=false)
    if matched is not False:
        for email_lower, contact_id in email_to_contact.items():
            if email_lower in seen_emails:
                continue
            if search_term and search_term not in email_lower:
                continue
            senders.append(
                SenderResponse(
                    email_address=email_lower,
                    mail_count=0,
                    matched_contact_id=contact_id,
                )
            )

    return senders


# --- AI Contact Extraction ---


class _AIExtractedContact(BaseModel):
    """LLM response schema for contact extraction."""

    display_name: str = Field(description="Full name of the contact")
    first_name: str | None = Field(default=None, description="First name")
    last_name: str | None = Field(default=None, description="Last name")
    emails: list[str] = Field(default_factory=list, description="Email addresses")
    phones: list[str] | None = Field(default=None, description="Phone numbers")
    organization: str | None = Field(default=None, description="Company/organization")
    title: str | None = Field(default=None, description="Job title")


@router.post("/extract-from-sender")
async def extract_contact_from_sender(
    data: ContactExtractRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ContactExtractedData:
    """Use AI to extract contact information from all emails by a sender.

    Collects all email summaries for the given sender address and asks the
    AI to extract structured contact data (name, phone, organization, title).
    """
    uid = UUID(user_id)
    sender_lower = data.sender_email.strip().lower()

    # Fetch up to 10 most recent summaries from this sender
    stmt = (
        select(EmailSummary)
        .where(
            EmailSummary.user_id == uid,
            func.lower(EmailSummary.mail_from) == sender_lower,
        )
        .order_by(EmailSummary.created_at.desc())
        .limit(10)
    )
    result = await db.execute(stmt)
    summaries = result.scalars().all()

    if not summaries:
        # No emails from this sender -- return basic info from the email address
        local_part = sender_lower.split("@")[0] if "@" in sender_lower else sender_lower
        display = local_part.replace(".", " ").replace("_", " ").replace("-", " ").title()
        return ContactExtractedData(
            display_name=display,
            emails=[sender_lower],
        )

    # Resolve AI provider
    from app.services.provider_resolver import get_default_provider

    provider = await get_default_provider(db, uid)
    if provider is None:
        raise HTTPException(status_code=422, detail="No active AI provider configured")

    # Render prompt
    from app.core.templating import get_template_engine

    engine = get_template_engine()
    mails_data = [
        {
            "mail_from": s.mail_from,
            "mail_subject": s.mail_subject,
            "mail_date": s.mail_date,
            "summary": s.summary or "",
            "key_points": s.key_points or [],
        }
        for s in summaries
    ]
    user_prompt = engine.render(
        "prompts/contact_extraction.j2",
        {
            "mails": mails_data,
            "language": "en",
        },
    )

    # Call LLM
    from app.services.ai import call_llm

    encryption = get_encryption()
    api_key = encryption.decrypt(provider.api_key) if provider.api_key else None
    user_settings = (await db.execute(select(UserSettings).where(UserSettings.user_id == uid))).scalar_one_or_none()

    try:
        ai_response, _tokens = await call_llm(
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            model_name=provider.model_name,
            api_key=api_key,
            system_prompt="You are a contact information extraction assistant. Extract structured contact data from emails.",
            user_prompt=user_prompt,
            response_schema=_AIExtractedContact,
            max_tokens=provider.max_tokens,
            temperature=0.1,
            timeout=provider.timeout_seconds or (user_settings.ai_timeout_seconds if user_settings else None),
        )
    except Exception as e:
        logger.error("contact_extraction_failed", sender=sender_lower, error=str(e))
        raise HTTPException(status_code=502, detail="AI extraction failed") from None

    extracted = cast("_AIExtractedContact", ai_response)

    # Ensure the sender email is always in the list
    emails = [e.lower() for e in (extracted.emails or [])]
    if sender_lower not in emails:
        emails.insert(0, sender_lower)

    return ContactExtractedData(
        display_name=extracted.display_name or sender_lower,
        first_name=extracted.first_name,
        last_name=extracted.last_name,
        emails=emails,
        phones=extracted.phones,
        organization=extracted.organization,
        title=extracted.title,
    )


@router.post("", status_code=201)
async def create_contact(
    data: ContactCreateRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> ContactResponse:
    """Create a new local contact (not from CardDAV sync).

    Generates a synthetic CardDAV UID for local-only contacts and
    auto-assigns the email addresses to the new contact.
    If CardDAV is configured, a write-back is attempted.
    """
    uid = UUID(user_id)

    # Generate a synthetic vCard for the local contact
    contact_uuid = uuid4()
    carddav_uid = f"local-{contact_uuid}"
    now = datetime.now(UTC)

    vcard_lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"UID:{carddav_uid}",
        f"FN:{data.display_name}",
    ]
    if data.first_name or data.last_name:
        vcard_lines.append(f"N:{data.last_name or ''};{data.first_name or ''};;;")
    for email in data.emails or []:
        vcard_lines.append(f"EMAIL:{email}")
    for phone in data.phones or []:
        vcard_lines.append(f"TEL:{phone}")
    if data.organization:
        vcard_lines.append(f"ORG:{data.organization}")
    if data.title:
        vcard_lines.append(f"TITLE:{data.title}")
    vcard_lines.append("END:VCARD")
    raw_vcard = "\n".join(vcard_lines)

    contact = Contact(
        id=contact_uuid,
        user_id=uid,
        carddav_uid=carddav_uid,
        display_name=data.display_name,
        first_name=data.first_name,
        last_name=data.last_name,
        emails=[e.lower() for e in (data.emails or [])],
        phones=data.phones,
        organization=data.organization,
        title=data.title,
        raw_vcard=raw_vcard,
        etag=f"local-{contact_uuid}",
        synced_at=now,
    )
    db.add(contact)
    await db.flush()

    # Update Valkey cache for each email
    cache = get_cache_client()
    from app.core.config import get_settings

    settings = get_settings()
    for email in contact.emails or []:
        cache_key = f"contact_match:{uid}:{email.lower()}"
        await cache.setex(cache_key, settings.contact_cache_ttl_seconds, str(contact.id))

    logger.info(
        "contact_created_manually",
        contact_id=str(contact.id),
        display_name=data.display_name,
        user_id=user_id,
    )

    return ContactResponse.model_validate(contact)


# --- Single Contact (by ID) ---
# NOTE: Path-parameter routes must come AFTER literal routes like /unmatched-senders
# to avoid FastAPI matching the literal segment as a {contact_id} UUID.


@router.get("/assignment/{account_id}/{mail_uid}")
async def get_mail_contact(
    account_id: UUID,
    mail_uid: str,
    db: DbSession,
    user_id: CurrentUserId,
) -> ContactAssignmentSchema | None:
    """Get the AI-assigned contact for a specific mail.

    Returns ``None`` (HTTP 200 with ``null`` body) when no assignment exists.
    """
    stmt = (
        select(ContactAssignment)
        .where(
            ContactAssignment.user_id == UUID(user_id),
            ContactAssignment.mail_account_id == account_id,
            ContactAssignment.mail_uid == mail_uid,
        )
        .order_by(ContactAssignment.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    assignment = result.scalar_one_or_none()
    if assignment is None:
        return None
    return ContactAssignmentSchema.model_validate(assignment)


@router.get("/{contact_id}")
async def get_contact(
    contact_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> ContactResponse:
    """Get a single cached contact by ID."""
    contact = await get_or_404(db, Contact, contact_id, user_id, "Contact not found")
    return ContactResponse.model_validate(contact)


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(
    contact_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a cached contact."""
    contact = await get_or_404(db, Contact, contact_id, user_id, "Contact not found")
    await db.delete(contact)
    await db.flush()
    logger.info("contact_deleted", contact_id=str(contact_id), user_id=user_id)


@router.get("/{contact_id}/mails")
async def list_contact_mails(
    contact_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> ContactMailsResponse:
    """List mails associated with a contact via AI assignment (paginated)."""
    await get_or_404(db, Contact, contact_id, user_id, "Contact not found")
    base_stmt = (
        select(ContactAssignment)
        .where(
            ContactAssignment.user_id == UUID(user_id),
            ContactAssignment.contact_id == contact_id,
        )
        .order_by(ContactAssignment.created_at.desc())
    )
    result = await paginate(db, base_stmt, page, per_page)
    return build_paginated_response(result, ContactAssignmentSchema, ContactMailsResponse)


@router.delete("/{contact_id}/mails/{assignment_id}", status_code=204)
async def unlink_contact_mail(
    contact_id: UUID,
    assignment_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Remove an AI-assigned mail from a contact (delete the ContactAssignment row)."""
    assignment = await get_or_404(db, ContactAssignment, assignment_id, user_id, detail="Assignment not found")
    if assignment.contact_id != contact_id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    await db.delete(assignment)
    await db.flush()
    logger.info(
        "contact_mail_unlinked",
        assignment_id=str(assignment_id),
        contact_id=str(contact_id),
        user_id=user_id,
    )


@router.post("/{contact_id}/emails", status_code=201)
async def assign_email_to_contact(
    contact_id: UUID,
    data: AssignEmailRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> AssignEmailResponse:
    """Assign an email address to a contact.

    Adds the email to the contact's ``emails`` JSON array (if not already
    present) and triggers a CardDAV write-back to persist the change
    in the upstream address book.  Also updates the Valkey cache so
    subsequent matching resolves immediately.
    """
    uid = UUID(user_id)
    email_lower = data.email_address.strip().lower()

    contact = await get_or_404(db, Contact, contact_id, user_id, "Contact not found")

    writeback_triggered = False

    # Add email to contact's local emails array if not already present
    existing_emails_lower = [e.lower() for e in (contact.emails or [])]
    if email_lower not in existing_emails_lower:
        contact.emails = [*(contact.emails or []), email_lower]
        await db.flush()

        # Trigger CardDAV write-back
        config_stmt = select(CardDAVConfig).where(CardDAVConfig.user_id == uid, CardDAVConfig.is_active.is_(True))
        config_result = await db.execute(config_stmt)
        carddav_config = config_result.scalar_one_or_none()
        if carddav_config:
            try:
                await write_back_email_to_contact(db, carddav_config, contact, email_lower)
                writeback_triggered = True
            except Exception:
                logger.exception(
                    "email_writeback_failed",
                    contact_id=str(contact_id),
                    email=email_lower,
                )

    # Update Valkey cache so matching resolves immediately
    cache = get_cache_client()
    cache_key = f"contact_match:{uid}:{email_lower}"
    from app.core.config import get_settings

    await cache.setex(cache_key, get_settings().contact_cache_ttl_seconds, str(contact.id))

    logger.info(
        "email_assigned_to_contact",
        email=email_lower,
        contact_id=str(contact_id),
        user_id=user_id,
        writeback=writeback_triggered,
    )

    return AssignEmailResponse(
        contact_id=contact.id,
        email_address=email_lower,
        writeback_triggered=writeback_triggered,
    )


@router.delete("/{contact_id}/emails", status_code=200)
async def remove_email_from_contact_endpoint(
    contact_id: UUID,
    data: RemoveEmailRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> RemoveEmailResponse:
    """Remove an email address from a contact.

    Removes the email from the contact's ``emails`` JSON array and
    triggers a CardDAV write-back to persist the change in the upstream
    address book.  Also invalidates the Valkey cache entry.
    """
    uid = UUID(user_id)
    email_lower = data.email_address.strip().lower()

    contact = await get_or_404(db, Contact, contact_id, user_id, "Contact not found")

    writeback_triggered = False

    # Remove email from contact's local emails array
    existing_emails_lower = [e.lower() for e in (contact.emails or [])]
    if email_lower in existing_emails_lower:
        contact.emails = [e for e in (contact.emails or []) if e.lower() != email_lower]
        await db.flush()

        # Trigger CardDAV write-back to remove from vCard
        config_stmt = select(CardDAVConfig).where(CardDAVConfig.user_id == uid, CardDAVConfig.is_active.is_(True))
        config_result = await db.execute(config_stmt)
        carddav_config = config_result.scalar_one_or_none()
        if carddav_config:
            try:
                await remove_email_from_contact(db, carddav_config, contact, email_lower)
                writeback_triggered = True
            except Exception:
                logger.exception(
                    "email_remove_writeback_failed",
                    contact_id=str(contact_id),
                    email=email_lower,
                )

    # Invalidate Valkey cache
    cache = get_cache_client()
    cache_key = f"contact_match:{uid}:{email_lower}"
    await cache.delete(cache_key)

    logger.info(
        "email_removed_from_contact",
        email=email_lower,
        contact_id=str(contact_id),
        user_id=user_id,
        writeback=writeback_triggered,
    )

    return RemoveEmailResponse(
        contact_id=contact.id,
        email_address=email_lower,
        writeback_triggered=writeback_triggered,
    )
