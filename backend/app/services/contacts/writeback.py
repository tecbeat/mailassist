"""CardDAV write-back service.

Adds or removes email addresses on Nextcloud contacts via CardDAV PUT
with optimistic locking (ETag-based).
"""

import httpx
import structlog
import vobject
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_cache_client
from app.core.security import decrypt_credentials
from app.models import CardDAVConfig, Contact

logger = structlog.get_logger()


def _get_carddav_credentials(config: CardDAVConfig) -> dict[str, str]:
    """Decrypt CardDAV credentials. Held only briefly."""
    return decrypt_credentials(config.encrypted_credentials)


async def write_back_email_to_contact(
    db: AsyncSession,
    config: CardDAVConfig,
    contact: Contact,
    new_email: str,
) -> bool:
    """Write back a new email address to a Nextcloud contact via CardDAV.

    Only adds email addresses; never removes existing ones.
    Uses optimistic locking via ETag.
    """
    credentials = _get_carddav_credentials(config)
    email_lower = new_email.lower()

    # Skip if email already exists on the contact
    if email_lower in [e.lower() for e in (contact.emails or [])]:
        return True

    # Resolve the actual addressbook-home URL via DAV discovery.
    # The stored carddav_url may be a bare server URL.
    from app.services.dav_discovery import discover_dav

    try:
        discovery = await discover_dav(
            config.carddav_url,
            credentials["username"],
            credentials["password"],
        )
    except Exception:
        logger.exception("writeback_discovery_failed")
        return False

    if not discovery.success or not discovery.addressbook_home:
        logger.error("writeback_discovery_failed", message=discovery.message)
        return False

    base_url = discovery.addressbook_home.rstrip("/")
    address_book = config.address_book.strip("/")

    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(
                auth=(credentials["username"], credentials["password"]),
                timeout=15,
            ) as client:
                # Fetch current vCard with ETag
                contact_url = f"{base_url}/{address_book}/{contact.carddav_uid}.vcf"
                get_response = await client.get(contact_url)
                if get_response.status_code != 200:
                    logger.error("writeback_fetch_failed", status=get_response.status_code)
                    return False

                current_etag = get_response.headers.get("ETag", "").strip('"')
                current_vcard_text = get_response.text

                # Parse and modify vCard using vobject
                card = vobject.readOne(current_vcard_text)
                new_email_prop = card.add("email")
                new_email_prop.value = email_lower
                new_email_prop.type_param = "INTERNET"

                updated_vcard = card.serialize()

                # PUT with If-Match for optimistic locking
                put_response = await client.put(
                    contact_url,
                    content=updated_vcard,
                    headers={
                        "Content-Type": "text/vcard; charset=utf-8",
                        "If-Match": f'"{current_etag}"',
                    },
                )

                if put_response.status_code in (200, 201, 204):
                    # Update local cache
                    contact.emails = (contact.emails or []) + [email_lower]
                    contact.etag = put_response.headers.get("ETag", "").strip('"') or current_etag
                    contact.raw_vcard = updated_vcard
                    await db.commit()

                    # Invalidate Valkey cache for this email
                    cache = get_cache_client()
                    await cache.delete(f"contact_match:{contact.user_id}:{email_lower}")

                    logger.info(
                        "writeback_success",
                        contact_id=str(contact.id),
                        email=email_lower,
                    )
                    return True

                elif put_response.status_code == 412:
                    # Precondition failed: concurrent edit, retry
                    logger.warning("writeback_conflict", attempt=attempt)
                    continue
                else:
                    logger.error("writeback_put_failed", status=put_response.status_code)
                    return False

        except Exception:
            logger.exception("writeback_failed", attempt=attempt)
            if attempt >= max_retries:
                return False

    return False


async def remove_email_from_contact(
    db: AsyncSession,
    config: CardDAVConfig,
    contact: Contact,
    email: str,
) -> bool:
    """Remove an email address from a Nextcloud contact via CardDAV.

    Deletes the EMAIL property from the vCard and PUTs the updated
    card back with optimistic locking via ETag.
    """
    credentials = _get_carddav_credentials(config)
    email_lower = email.lower()

    # Resolve addressbook-home URL via DAV discovery.
    from app.services.dav_discovery import discover_dav

    try:
        discovery = await discover_dav(
            config.carddav_url,
            credentials["username"],
            credentials["password"],
        )
    except Exception:
        logger.exception("writeback_remove_discovery_failed")
        return False

    if not discovery.success or not discovery.addressbook_home:
        logger.error("writeback_remove_discovery_failed", message=discovery.message)
        return False

    base_url = discovery.addressbook_home.rstrip("/")
    address_book = config.address_book.strip("/")

    max_retries = 2

    for attempt in range(max_retries + 1):
        try:
            async with httpx.AsyncClient(
                auth=(credentials["username"], credentials["password"]),
                timeout=15,
            ) as client:
                contact_url = f"{base_url}/{address_book}/{contact.carddav_uid}.vcf"
                get_response = await client.get(contact_url)
                if get_response.status_code != 200:
                    logger.error("writeback_remove_fetch_failed", status=get_response.status_code)
                    return False

                current_etag = get_response.headers.get("ETag", "").strip('"')
                current_vcard_text = get_response.text

                # Parse vCard and remove matching EMAIL properties
                card = vobject.readOne(current_vcard_text)
                email_children = [
                    c for c in card.contents.get("email", [])
                    if c.value.lower() == email_lower
                ]
                if not email_children:
                    # Email not on vCard — nothing to remove
                    return True

                for child in email_children:
                    card.contents["email"].remove(child)
                # Clean up empty list
                if not card.contents.get("email"):
                    del card.contents["email"]

                updated_vcard = card.serialize()

                put_response = await client.put(
                    contact_url,
                    content=updated_vcard,
                    headers={
                        "Content-Type": "text/vcard; charset=utf-8",
                        "If-Match": f'"{current_etag}"',
                    },
                )

                if put_response.status_code in (200, 201, 204):
                    # Update local model
                    contact.emails = [
                        e for e in (contact.emails or [])
                        if e.lower() != email_lower
                    ]
                    contact.etag = put_response.headers.get("ETag", "").strip('"') or current_etag
                    contact.raw_vcard = updated_vcard
                    await db.commit()

                    # Invalidate Valkey cache
                    cache = get_cache_client()
                    await cache.delete(f"contact_match:{contact.user_id}:{email_lower}")

                    logger.info(
                        "writeback_remove_success",
                        contact_id=str(contact.id),
                        email=email_lower,
                    )
                    return True

                elif put_response.status_code == 412:
                    logger.warning("writeback_remove_conflict", attempt=attempt)
                    continue
                else:
                    logger.error("writeback_remove_put_failed", status=put_response.status_code)
                    return False

        except Exception:
            logger.exception("writeback_remove_failed", attempt=attempt)
            if attempt >= max_retries:
                return False

    return False


from uuid import UUID


async def auto_add_sender_email(
    user_id: UUID,
    contact_id: UUID,
    sender_email: str,
) -> bool:
    """Add a sender's email to an assigned contact (DB + CardDAV + cache).

    Called automatically after contact assignment (direct or post-approval).
    Best-effort: failures are logged but never propagate.
    """
    from app.core.config import get_settings
    from app.core.database import get_session_ctx

    email_lower = sender_email.strip().lower()
    if not email_lower:
        return False

    try:
        async with get_session_ctx() as db:
            contact = await db.get(Contact, contact_id)
            if contact is None or contact.user_id != user_id:
                logger.debug("auto_add_email_contact_not_found", contact_id=str(contact_id))
                return False

            # Skip if already present
            if email_lower in [e.lower() for e in (contact.emails or [])]:
                return True

            # Update local DB
            contact.emails = [*(contact.emails or []), email_lower]
            await db.flush()

            # CardDAV write-back (if configured)
            from sqlalchemy import select as sa_select
            config_result = await db.execute(
                sa_select(CardDAVConfig).where(
                    CardDAVConfig.user_id == user_id,
                    CardDAVConfig.is_active.is_(True),
                )
            )
            carddav_config = config_result.scalar_one_or_none()
            if carddav_config:
                try:
                    await write_back_email_to_contact(db, carddav_config, contact, email_lower)
                except Exception:
                    logger.exception("auto_add_email_writeback_failed", contact_id=str(contact_id))

            # Update Valkey cache
            cache = get_cache_client()
            await cache.setex(
                f"contact_match:{user_id}:{email_lower}",
                get_settings().contact_cache_ttl_seconds,
                str(contact.id),
            )

            await db.commit()
            logger.info(
                "auto_add_email_success",
                contact_id=str(contact_id),
                email=email_lower,
            )
            return True
    except Exception:
        logger.exception("auto_add_email_failed", contact_id=str(contact_id), email=email_lower)
        return False
