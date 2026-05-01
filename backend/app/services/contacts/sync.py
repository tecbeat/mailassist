"""CardDAV contact sync service.

Handles full and incremental sync via sync-token, contact upsert/delete,
and email cache rebuilding after sync.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_cache_client
from app.core.security import decrypt_credentials
from app.core.types import ConnectionTestResult
from app.models import CardDAVConfig, Contact
from app.services.contacts.vcard import parse_vcard

logger = structlog.get_logger()


def _get_contact_cache_ttl() -> int:
    """Return contact cache TTL from settings."""
    return get_settings().contact_cache_ttl_seconds


def _get_carddav_credentials(config: CardDAVConfig) -> dict[str, str]:
    """Decrypt CardDAV credentials. Held only briefly."""
    return decrypt_credentials(config.encrypted_credentials)


async def test_carddav_connection(
    carddav_url: str,
    username: str,
    password: str,
    address_book: str = "",
) -> ConnectionTestResult:
    """Test CardDAV connection with auto-discovery.

    Uses RFC 6764 auto-discovery to find address books from the server URL.
    If ``address_book`` is provided, validates that it exists.
    Returns discovered address books and the resolved ``carddav_url``
    so the frontend can auto-fill the configuration.
    """
    from app.services.dav_discovery import discover_dav

    discovery = await discover_dav(carddav_url, username, password)

    if not discovery.success:
        return ConnectionTestResult(
            success=False,
            message=discovery.message,
        )

    ab_names = [ab.display_name for ab in discovery.address_books]
    ab_slugs = [ab.slug for ab in discovery.address_books]

    # If address_book provided, validate it exists
    if address_book:
        match = address_book.strip("/")
        if match not in ab_slugs and match not in ab_names:
            hint = f" Available: {', '.join(ab_names)}" if ab_names else ""
            return ConnectionTestResult(
                success=False,
                message=f"Address book '{address_book}' not found.{hint}",
                details={
                    "address_books": ab_slugs,
                    "address_book_names": ab_names,
                    "carddav_url": discovery.addressbook_home,
                },
            )
        return ConnectionTestResult(
            success=True,
            message=f"Connected. Address book '{address_book}' is valid.",
            details={
                "address_books": ab_slugs,
                "address_book_names": ab_names,
                "carddav_url": discovery.addressbook_home,
            },
        )

    # No address_book — return discovery results
    return ConnectionTestResult(
        success=True,
        message=discovery.message,
        details={
            "address_books": ab_slugs,
            "address_book_names": ab_names,
            "carddav_url": discovery.addressbook_home,
            "calendars": [c.slug for c in discovery.calendars],
            "calendar_names": [c.display_name for c in discovery.calendars],
            "caldav_url": discovery.calendar_home,
        },
    )


async def sync_contacts(
    db: AsyncSession,
    config: CardDAVConfig,
) -> dict[str, Any]:
    """Sync contacts from CardDAV using incremental sync.

    Uses sync-token for efficient change detection.
    Returns stats about the sync operation.
    """
    credentials = _get_carddav_credentials(config)
    user_id = config.user_id
    stats = {"added": 0, "updated": 0, "deleted": 0, "errors": 0}

    try:
        # Resolve the actual addressbook-home URL via DAV discovery.
        # The stored carddav_url may be a bare server URL (e.g.
        # https://nextcloud.example.com) rather than the full DAV path.
        from app.services.dav_discovery import discover_dav

        discovery = await discover_dav(
            config.carddav_url,
            credentials["username"],
            credentials["password"],
        )
        if not discovery.success or not discovery.addressbook_home:
            raise ConnectionError(f"DAV discovery failed for {config.carddav_url}: {discovery.message}")

        base_url = discovery.addressbook_home.rstrip("/")
        address_book = config.address_book.strip("/")
        sync_url = f"{base_url}/{address_book}/"

        async with httpx.AsyncClient(
            auth=(credentials["username"], credentials["password"]),
            timeout=30,
        ) as client:
            # Build sync request
            if config.sync_token:
                # Incremental sync using sync-token
                body = f"""<?xml version="1.0" encoding="UTF-8"?>
<d:sync-collection xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
    <d:sync-token>{config.sync_token}</d:sync-token>
    <d:sync-level>1</d:sync-level>
    <d:prop>
        <d:getetag/>
        <card:address-data/>
    </d:prop>
</d:sync-collection>"""
                response = await client.request(
                    "REPORT",
                    sync_url,
                    headers={"Content-Type": "application/xml"},
                    content=body,
                )
            else:
                # Full sync: fetch all contacts
                body = """<?xml version="1.0" encoding="UTF-8"?>
<card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
    <d:prop>
        <d:getetag/>
        <card:address-data/>
    </d:prop>
</card:addressbook-query>"""
                response = await client.request(
                    "REPORT",
                    sync_url,
                    headers={"Content-Type": "application/xml", "Depth": "1"},
                    content=body,
                )

            if response.status_code not in (200, 207):
                raise ConnectionError(f"CardDAV sync failed: HTTP {response.status_code}")

            # Parse multistatus XML response
            from xml.etree import ElementTree as ET

            root = ET.fromstring(response.text)

            ns = {
                "d": "DAV:",
                "card": "urn:ietf:params:xml:ns:carddav",
            }

            # Extract new sync token
            sync_token_elem = root.find(".//d:sync-token", ns)
            new_sync_token = sync_token_elem.text if sync_token_elem is not None else None

            # Process each response element
            for resp_elem in root.findall(".//d:response", ns):
                href = resp_elem.findtext("d:href", "", ns)
                status = resp_elem.findtext(".//d:status", "", ns)

                # Check for deleted contacts (404 status in sync-collection)
                if "404" in status:
                    # Extract UID from href and delete
                    carddav_uid = href.rstrip("/").rsplit("/", 1)[-1].replace(".vcf", "")
                    stmt = delete(Contact).where(
                        Contact.user_id == user_id,
                        Contact.carddav_uid == carddav_uid,
                    )
                    await db.execute(stmt)
                    stats["deleted"] += 1
                    continue

                etag = resp_elem.findtext(".//d:getetag", "", ns).strip('"')
                vcard_data = resp_elem.findtext(".//card:address-data", "", ns)

                if not vcard_data:
                    continue

                carddav_uid = href.rstrip("/").rsplit("/", 1)[-1].replace(".vcf", "")

                try:
                    parsed = parse_vcard(vcard_data)
                    if not parsed or not parsed.get("display_name"):
                        continue

                    # Check if contact already exists
                    existing = await db.execute(
                        select(Contact).where(
                            Contact.user_id == user_id,
                            Contact.carddav_uid == carddav_uid,
                        )
                    )
                    contact = existing.scalar_one_or_none()

                    now = datetime.now(UTC)

                    if contact is None:
                        contact = Contact(
                            user_id=user_id,
                            carddav_uid=carddav_uid,
                            display_name=parsed["display_name"],
                            first_name=parsed.get("first_name"),
                            last_name=parsed.get("last_name"),
                            emails=parsed.get("emails", []),
                            phones=parsed.get("phones"),
                            organization=parsed.get("organization"),
                            title=parsed.get("title"),
                            photo_url=parsed.get("photo_url"),
                            raw_vcard=vcard_data,
                            etag=etag,
                            synced_at=now,
                        )
                        db.add(contact)
                        stats["added"] += 1
                    elif contact.etag != etag:
                        contact.display_name = parsed["display_name"]
                        contact.first_name = parsed.get("first_name")
                        contact.last_name = parsed.get("last_name")
                        contact.emails = parsed.get("emails", [])
                        contact.phones = parsed.get("phones")
                        contact.organization = parsed.get("organization")
                        contact.title = parsed.get("title")
                        contact.photo_url = parsed.get("photo_url")
                        contact.raw_vcard = vcard_data
                        contact.etag = etag
                        contact.synced_at = now
                        stats["updated"] += 1

                except Exception:
                    logger.exception("contact_parse_failed", carddav_uid=carddav_uid)
                    stats["errors"] += 1

            # Update sync token and last_sync_at
            if new_sync_token:
                config.sync_token = new_sync_token
            config.last_sync_at = datetime.now(UTC)
            await db.commit()

            # Rebuild email cache after sync
            await _rebuild_email_cache(db, user_id)

            logger.info("contact_sync_complete", user_id=str(user_id), **stats)

    except Exception as e:
        logger.error("contact_sync_failed", user_id=str(user_id), error=str(e))
        raise

    return stats


async def _rebuild_email_cache(db: AsyncSession, user_id: UUID) -> None:
    """Rebuild Valkey cache for contact email lookups after sync.

    Iterates all contacts for the user and caches each email address
    from their ``emails`` JSON array, mapping it to the contact ID.
    """
    cache = get_cache_client()
    ttl = _get_contact_cache_ttl()

    stmt = select(Contact).where(Contact.user_id == user_id)
    result = await db.execute(stmt)
    contacts = result.scalars().all()

    for contact in contacts:
        for email in contact.emails or []:
            email_lower = email.lower()
            cache_key = f"contact_match:{user_id}:{email_lower}"
            await cache.setex(cache_key, ttl, str(contact.id))
