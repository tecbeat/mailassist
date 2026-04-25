"""WebDAV/CardDAV/CalDAV auto-discovery (RFC 6764).

Discovers DAV endpoints from a minimal server URL by following:
  1. ``/.well-known/carddav`` or ``/.well-known/caldav`` redirect
  2. ``current-user-principal`` PROPFIND
  3. ``addressbook-home-set`` / ``calendar-home-set`` PROPFIND
  4. Depth-1 PROPFIND to enumerate collections

This allows users to provide just ``https://nextcloud.example.com``
and have the full DAV path, address books, and calendars auto-detected.
"""

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

import httpx
import structlog

logger = structlog.get_logger()

_NS = {
    "d": "DAV:",
    "card": "urn:ietf:params:xml:ns:carddav",
    "cal": "urn:ietf:params:xml:ns:caldav",
}

_PROPFIND_PRINCIPAL = """<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:current-user-principal/></d:prop>
</d:propfind>"""

_PROPFIND_HOMESETS = """<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:"
            xmlns:card="urn:ietf:params:xml:ns:carddav"
            xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <card:addressbook-home-set/>
    <cal:calendar-home-set/>
  </d:prop>
</d:propfind>"""

_PROPFIND_COLLECTIONS = """<?xml version="1.0" encoding="UTF-8"?>
<d:propfind xmlns:d="DAV:"
            xmlns:card="urn:ietf:params:xml:ns:carddav"
            xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:displayname/>
    <d:resourcetype/>
  </d:prop>
</d:propfind>"""


@dataclass
class DavCollection:
    """A discovered DAV collection (address book or calendar)."""

    href: str
    slug: str
    display_name: str
    collection_type: str  # "addressbook" or "calendar"


@dataclass
class DavDiscoveryResult:
    """Result of DAV auto-discovery."""

    success: bool
    message: str
    dav_url: str = ""
    principal_url: str = ""
    addressbook_home: str = ""
    calendar_home: str = ""
    address_books: list[DavCollection] = field(default_factory=list)
    calendars: list[DavCollection] = field(default_factory=list)


def _absolute_url(base: str, href: str) -> str:
    """Resolve a potentially relative href against the base URL.

    Always enforces HTTPS since the original server URL must use HTTPS.
    Handles servers behind reverse proxies that redirect to ``http://``.
    """
    from urllib.parse import urlparse

    if href.startswith("http://") or href.startswith("https://"):
        # Force HTTPS — servers behind reverse proxies may return http://
        parsed = urlparse(href)
        return f"https://{parsed.netloc}{parsed.path}"

    # Relative href — combine with base
    parsed = urlparse(base)
    return f"https://{parsed.netloc}{href}"


async def _propfind(
    client: httpx.AsyncClient,
    url: str,
    body: str,
    depth: str = "0",
) -> httpx.Response | None:
    """Send a PROPFIND request, following one redirect if needed."""
    max_redirects = 2
    current_url = url

    for _ in range(max_redirects + 1):
        try:
            resp = await client.request(
                "PROPFIND",
                current_url,
                headers={"Depth": depth, "Content-Type": "application/xml"},
                content=body,
            )
            if resp.status_code in (200, 207):
                return resp
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                if location:
                    current_url = _absolute_url(url, location)
                    continue
            logger.warning("propfind_failed", url=current_url, status=resp.status_code)
            return None
        except Exception as e:
            logger.warning("propfind_failed", url=current_url, error=str(e))
            return None
    return None


async def _discover_dav_url(
    client: httpx.AsyncClient, server_url: str, service: str,
) -> str:
    """Try well-known discovery, fall back to common Nextcloud paths.

    Args:
        server_url: Base server URL (e.g. ``https://nextcloud.example.com``).
        service: Either ``carddav`` or ``caldav``.

    Returns:
        The DAV base URL to use for further discovery.
    """
    base = server_url.rstrip("/")

    # 1. Try /.well-known/{service}
    well_known = f"{base}/.well-known/{service}"
    try:
        resp = await client.request(
            "PROPFIND", well_known,
            headers={"Depth": "0", "Content-Type": "application/xml"},
            content=_PROPFIND_PRINCIPAL,
        )
        if resp.status_code in (200, 207):
            return well_known
        # Follow redirects manually (httpx doesn't redirect PROPFIND by default)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if location:
                redirect_url = _absolute_url(base, location)
                # Verify the redirect target works
                check = await _propfind(client, redirect_url.rstrip("/"), _PROPFIND_PRINCIPAL)
                if check:
                    return redirect_url.rstrip("/")
    except Exception:
        pass

    # 2. Try common Nextcloud/Sabre paths
    for path in ["/remote.php/dav", "/dav"]:
        url = f"{base}{path}"
        resp = await _propfind(client, url, _PROPFIND_PRINCIPAL)
        if resp:
            return url

    # 3. Fall back to provided URL as-is
    return base


async def _discover_principal(
    client: httpx.AsyncClient, dav_url: str,
) -> str | None:
    """Discover the current-user-principal href."""
    resp = await _propfind(client, dav_url, _PROPFIND_PRINCIPAL)
    if resp is None:
        return None

    try:
        root = ET.fromstring(resp.text)
        href_el = root.find(".//d:current-user-principal/d:href", _NS)
        if href_el is not None and href_el.text:
            return _absolute_url(dav_url, href_el.text.strip())
    except Exception:
        pass
    return None


async def _discover_homesets(
    client: httpx.AsyncClient, principal_url: str,
) -> tuple[str | None, str | None]:
    """Discover addressbook-home-set and calendar-home-set from the principal."""
    resp = await _propfind(client, principal_url, _PROPFIND_HOMESETS)
    if resp is None:
        return None, None

    ab_home = None
    cal_home = None
    try:
        root = ET.fromstring(resp.text)
        ab_href = root.find(".//card:addressbook-home-set/d:href", _NS)
        if ab_href is not None and ab_href.text:
            ab_home = _absolute_url(principal_url, ab_href.text.strip())
        cal_href = root.find(".//cal:calendar-home-set/d:href", _NS)
        if cal_href is not None and cal_href.text:
            cal_home = _absolute_url(principal_url, cal_href.text.strip())
    except Exception:
        pass
    return ab_home, cal_home


async def _discover_collections(
    client: httpx.AsyncClient, home_url: str,
) -> list[DavCollection]:
    """List collections (address books or calendars) under a home-set URL."""
    resp = await _propfind(client, home_url, _PROPFIND_COLLECTIONS, depth="1")
    if resp is None:
        return []

    collections: list[DavCollection] = []
    try:
        root = ET.fromstring(resp.text)
        for response in root.findall(".//d:response", _NS):
            href = response.findtext("d:href", "", _NS)
            # Skip the home-set resource itself
            if href.rstrip("/") == home_url.rstrip("/").split("//", 1)[-1].split("/", 1)[-1].rstrip("/"):
                continue

            restype = response.find(".//d:resourcetype", _NS)
            if restype is None:
                continue

            display_name = response.findtext(".//d:displayname", "", _NS).strip()
            slug = href.rstrip("/").rsplit("/", 1)[-1]

            if not display_name:
                display_name = slug

            # Skip the parent collection itself (compare full paths)
            from urllib.parse import urlparse
            home_path = urlparse(home_url).path.rstrip("/")
            if href.rstrip("/") == home_path:
                continue

            if restype.find("card:addressbook", _NS) is not None:
                collections.append(DavCollection(
                    href=href,
                    slug=slug,
                    display_name=display_name,
                    collection_type="addressbook",
                ))
            elif restype.find("cal:calendar", _NS) is not None:
                collections.append(DavCollection(
                    href=href,
                    slug=slug,
                    display_name=display_name,
                    collection_type="calendar",
                ))
    except Exception:
        logger.warning("collection_parse_failed", home_url=home_url)

    return collections


async def discover_dav(
    server_url: str,
    username: str,
    password: str,
) -> DavDiscoveryResult:
    """Full DAV auto-discovery from a server URL.

    Given just ``https://nextcloud.example.com`` plus credentials, discovers:
    - The DAV endpoint URL
    - The user's principal URL
    - Address book home-set and available address books
    - Calendar home-set and available calendars

    Args:
        server_url: The server base URL (e.g. ``https://nextcloud.example.com``).
        username: DAV username.
        password: DAV password (or app token).

    Returns:
        A ``DavDiscoveryResult`` with all discovered information.
    """
    if not server_url.startswith("https://"):
        return DavDiscoveryResult(
            success=False, message="Server URL must use HTTPS",
        )

    try:
        async with httpx.AsyncClient(
            auth=(username, password),
            timeout=15,
            follow_redirects=False,
        ) as client:
            # Step 1: Find the DAV URL
            dav_url = await _discover_dav_url(client, server_url, "carddav")

            # Step 2: Find current-user-principal
            principal_url = await _discover_principal(client, dav_url)
            if principal_url is None:
                return DavDiscoveryResult(
                    success=False,
                    message="Authentication failed or no DAV endpoint found at this URL.",
                    dav_url=dav_url,
                )

            # Step 3: Find home-sets
            ab_home, cal_home = await _discover_homesets(client, principal_url)

            # Step 4: Enumerate collections
            address_books: list[DavCollection] = []
            calendars: list[DavCollection] = []

            if ab_home:
                address_books = await _discover_collections(client, ab_home)
            if cal_home:
                calendars = await _discover_collections(client, cal_home)

            # Build summary
            parts = []
            if address_books:
                ab_names = [ab.display_name for ab in address_books]
                parts.append(f"{len(address_books)} address book(s): {', '.join(ab_names)}")
            if calendars:
                cal_names = [c.display_name for c in calendars]
                parts.append(f"{len(calendars)} calendar(s): {', '.join(cal_names)}")

            summary = ". ".join(parts) if parts else "Connected but no collections found."

            return DavDiscoveryResult(
                success=True,
                message=f"Auto-discovery successful. {summary}",
                dav_url=dav_url,
                principal_url=principal_url,
                addressbook_home=ab_home or "",
                calendar_home=cal_home or "",
                address_books=address_books,
                calendars=calendars,
            )

    except httpx.TimeoutException:
        return DavDiscoveryResult(
            success=False, message="Connection timed out.",
        )
    except Exception as e:
        return DavDiscoveryResult(
            success=False, message=f"Discovery failed: {e}",
        )
