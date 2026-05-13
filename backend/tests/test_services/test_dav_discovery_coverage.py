"""Coverage tests for app.services.dav_discovery.

Covers: _absolute_url, _propfind, _discover_dav_url, _discover_principal,
_discover_homesets, _discover_collections, discover_dav.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.dav_discovery import (
    DavDiscoveryResult,
    _absolute_url,
    _discover_collections,
    _discover_dav_url,
    _discover_homesets,
    _discover_principal,
    _propfind,
    discover_dav,
)


# ---------------------------------------------------------------------------
# _absolute_url
# ---------------------------------------------------------------------------


class TestAbsoluteUrl:
    def test_relative_href(self):
        result = _absolute_url("https://nc.example.com/dav", "/remote.php/dav/principals/users/admin")
        assert result == "https://nc.example.com/remote.php/dav/principals/users/admin"

    def test_absolute_https(self):
        result = _absolute_url("https://nc.example.com", "https://nc.example.com/dav")
        assert result == "https://nc.example.com/dav"

    def test_absolute_http_forced_to_https(self):
        result = _absolute_url("https://nc.example.com", "http://nc.example.com/dav")
        assert result == "https://nc.example.com/dav"


# ---------------------------------------------------------------------------
# _propfind
# ---------------------------------------------------------------------------


class TestPropfind:
    @pytest.mark.asyncio
    async def test_propfind_success_207(self):
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 207
        mock_client.request = AsyncMock(return_value=resp)

        result = await _propfind(mock_client, "https://nc.example.com/dav", "<body/>")
        assert result is resp

    @pytest.mark.asyncio
    async def test_propfind_redirect_followed(self):
        mock_client = AsyncMock()
        redirect_resp = MagicMock()
        redirect_resp.status_code = 301
        redirect_resp.headers = {"location": "/remote.php/dav"}

        ok_resp = MagicMock()
        ok_resp.status_code = 207

        mock_client.request = AsyncMock(side_effect=[redirect_resp, ok_resp])

        result = await _propfind(mock_client, "https://nc.example.com/.well-known/carddav", "<body/>")
        assert result is ok_resp

    @pytest.mark.asyncio
    async def test_propfind_redirect_no_location(self):
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 302
        resp.headers = {}
        mock_client.request = AsyncMock(return_value=resp)

        result = await _propfind(mock_client, "https://nc.example.com/dav", "<body/>")
        # No location header → falls through to warning, returns None
        assert result is None

    @pytest.mark.asyncio
    async def test_propfind_error_status(self):
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 403
        mock_client.request = AsyncMock(return_value=resp)

        result = await _propfind(mock_client, "https://nc.example.com/dav", "<body/>")
        assert result is None

    @pytest.mark.asyncio
    async def test_propfind_exception(self):
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=RuntimeError("network"))

        result = await _propfind(mock_client, "https://nc.example.com/dav", "<body/>")
        assert result is None

    @pytest.mark.asyncio
    async def test_propfind_max_redirects_exhausted(self):
        mock_client = AsyncMock()
        redirect_resp = MagicMock()
        redirect_resp.status_code = 301
        redirect_resp.headers = {"location": "/loop"}
        mock_client.request = AsyncMock(return_value=redirect_resp)

        result = await _propfind(mock_client, "https://nc.example.com/dav", "<body/>")
        assert result is None


# ---------------------------------------------------------------------------
# _discover_dav_url
# ---------------------------------------------------------------------------


class TestDiscoverDavUrl:
    @pytest.mark.asyncio
    async def test_well_known_direct_success(self):
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 207
        mock_client.request = AsyncMock(return_value=resp)

        result = await _discover_dav_url(mock_client, "https://nc.example.com", "carddav")
        assert result == "https://nc.example.com/.well-known/carddav"

    @pytest.mark.asyncio
    async def test_well_known_redirect_then_verify(self):
        mock_client = AsyncMock()
        redirect_resp = MagicMock()
        redirect_resp.status_code = 301
        redirect_resp.headers = {"location": "/remote.php/dav"}

        verify_resp = MagicMock()
        verify_resp.status_code = 207

        mock_client.request = AsyncMock(side_effect=[redirect_resp, verify_resp])

        result = await _discover_dav_url(mock_client, "https://nc.example.com", "carddav")
        assert result == "https://nc.example.com/remote.php/dav"

    @pytest.mark.asyncio
    async def test_well_known_fails_fallback_common_path(self):
        mock_client = AsyncMock()
        # well-known returns 404
        wk_resp = MagicMock()
        wk_resp.status_code = 404
        # /remote.php/dav propfind returns 207
        dav_resp = MagicMock()
        dav_resp.status_code = 207

        mock_client.request = AsyncMock(side_effect=[wk_resp, dav_resp])

        result = await _discover_dav_url(mock_client, "https://nc.example.com", "carddav")
        assert result == "https://nc.example.com/remote.php/dav"

    @pytest.mark.asyncio
    async def test_all_fail_returns_base(self):
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=RuntimeError("down"))

        result = await _discover_dav_url(mock_client, "https://nc.example.com", "carddav")
        assert result == "https://nc.example.com"

    @pytest.mark.asyncio
    async def test_well_known_exception_fallback_paths(self):
        mock_client = AsyncMock()
        # well-known raises, both fallback paths fail
        fail_resp = MagicMock()
        fail_resp.status_code = 403

        mock_client.request = AsyncMock(side_effect=[RuntimeError("wk"), fail_resp, fail_resp])

        result = await _discover_dav_url(mock_client, "https://nc.example.com", "carddav")
        assert result == "https://nc.example.com"


# ---------------------------------------------------------------------------
# _discover_principal
# ---------------------------------------------------------------------------


class TestDiscoverPrincipal:
    @pytest.mark.asyncio
    async def test_principal_found(self):
        xml = """<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:">
          <d:response>
            <d:propstat>
              <d:prop>
                <d:current-user-principal>
                  <d:href>/remote.php/dav/principals/users/admin/</d:href>
                </d:current-user-principal>
              </d:prop>
            </d:propstat>
          </d:response>
        </d:multistatus>"""
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 207
        resp.text = xml
        mock_client.request = AsyncMock(return_value=resp)

        result = await _discover_principal(mock_client, "https://nc.example.com/remote.php/dav")
        assert result == "https://nc.example.com/remote.php/dav/principals/users/admin/"

    @pytest.mark.asyncio
    async def test_principal_not_found(self):
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=RuntimeError("fail"))

        result = await _discover_principal(mock_client, "https://nc.example.com/dav")
        assert result is None

    @pytest.mark.asyncio
    async def test_principal_bad_xml(self):
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 207
        resp.text = "not xml at all"
        mock_client.request = AsyncMock(return_value=resp)

        result = await _discover_principal(mock_client, "https://nc.example.com/dav")
        assert result is None


# ---------------------------------------------------------------------------
# _discover_homesets
# ---------------------------------------------------------------------------


class TestDiscoverHomesets:
    @pytest.mark.asyncio
    async def test_homesets_found(self):
        xml = """<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:"
                        xmlns:card="urn:ietf:params:xml:ns:carddav"
                        xmlns:cal="urn:ietf:params:xml:ns:caldav">
          <d:response>
            <d:propstat>
              <d:prop>
                <card:addressbook-home-set>
                  <d:href>/remote.php/dav/addressbooks/users/admin/</d:href>
                </card:addressbook-home-set>
                <cal:calendar-home-set>
                  <d:href>/remote.php/dav/calendars/users/admin/</d:href>
                </cal:calendar-home-set>
              </d:prop>
            </d:propstat>
          </d:response>
        </d:multistatus>"""
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 207
        resp.text = xml
        mock_client.request = AsyncMock(return_value=resp)

        ab, cal = await _discover_homesets(mock_client, "https://nc.example.com/dav/principals/users/admin/")
        assert ab is not None
        assert "addressbooks" in ab
        assert cal is not None
        assert "calendars" in cal

    @pytest.mark.asyncio
    async def test_homesets_propfind_fails(self):
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=RuntimeError("fail"))

        ab, cal = await _discover_homesets(mock_client, "https://nc.example.com/dav/principals/users/admin/")
        assert ab is None
        assert cal is None

    @pytest.mark.asyncio
    async def test_homesets_bad_xml(self):
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 207
        resp.text = "not xml"
        mock_client.request = AsyncMock(return_value=resp)

        ab, cal = await _discover_homesets(mock_client, "https://nc.example.com/dav")
        assert ab is None
        assert cal is None


# ---------------------------------------------------------------------------
# _discover_collections
# ---------------------------------------------------------------------------


class TestDiscoverCollections:
    @pytest.mark.asyncio
    async def test_collections_found(self):
        xml = """<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:"
                        xmlns:card="urn:ietf:params:xml:ns:carddav"
                        xmlns:cal="urn:ietf:params:xml:ns:caldav">
          <d:response>
            <d:href>/remote.php/dav/addressbooks/users/admin/</d:href>
            <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop></d:propstat>
          </d:response>
          <d:response>
            <d:href>/remote.php/dav/addressbooks/users/admin/contacts/</d:href>
            <d:propstat>
              <d:prop>
                <d:displayname>Contacts</d:displayname>
                <d:resourcetype><d:collection/><card:addressbook/></d:resourcetype>
              </d:prop>
            </d:propstat>
          </d:response>
          <d:response>
            <d:href>/remote.php/dav/addressbooks/users/admin/work/</d:href>
            <d:propstat>
              <d:prop>
                <d:displayname></d:displayname>
                <d:resourcetype><d:collection/><card:addressbook/></d:resourcetype>
              </d:prop>
            </d:propstat>
          </d:response>
        </d:multistatus>"""
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 207
        resp.text = xml
        mock_client.request = AsyncMock(return_value=resp)

        result = await _discover_collections(mock_client, "https://nc.example.com/remote.php/dav/addressbooks/users/admin/")
        assert len(result) == 2
        assert result[0].collection_type == "addressbook"
        assert result[0].display_name == "Contacts"
        # Second has empty display name, should fallback to slug
        assert result[1].display_name == "work"

    @pytest.mark.asyncio
    async def test_collections_propfind_fails(self):
        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=RuntimeError("fail"))

        result = await _discover_collections(mock_client, "https://nc.example.com/dav/ab/")
        assert result == []

    @pytest.mark.asyncio
    async def test_collections_calendar_type(self):
        xml = """<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
          <d:response>
            <d:href>/dav/calendars/admin/personal/</d:href>
            <d:propstat>
              <d:prop>
                <d:displayname>Personal</d:displayname>
                <d:resourcetype><d:collection/><cal:calendar/></d:resourcetype>
              </d:prop>
            </d:propstat>
          </d:response>
        </d:multistatus>"""
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 207
        resp.text = xml
        mock_client.request = AsyncMock(return_value=resp)

        result = await _discover_collections(mock_client, "https://nc.example.com/dav/calendars/admin/")
        assert len(result) == 1
        assert result[0].collection_type == "calendar"

    @pytest.mark.asyncio
    async def test_collections_no_resourcetype_skipped(self):
        xml = """<?xml version="1.0"?>
        <d:multistatus xmlns:d="DAV:">
          <d:response>
            <d:href>/dav/ab/contacts/</d:href>
            <d:propstat>
              <d:prop><d:displayname>Contacts</d:displayname></d:prop>
            </d:propstat>
          </d:response>
        </d:multistatus>"""
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 207
        resp.text = xml
        mock_client.request = AsyncMock(return_value=resp)

        result = await _discover_collections(mock_client, "https://nc.example.com/dav/ab/")
        assert result == []


# ---------------------------------------------------------------------------
# discover_dav (top-level)
# ---------------------------------------------------------------------------


class TestDiscoverDav:
    @pytest.mark.asyncio
    async def test_non_https_returns_failure(self):
        result = await discover_dav("http://nc.example.com", "user", "pass")
        assert result.success is False
        assert "HTTPS" in result.message

    @pytest.mark.asyncio
    async def test_full_success(self):
        with (
            patch("app.services.dav_discovery._discover_dav_url", new_callable=AsyncMock, return_value="https://nc.example.com/remote.php/dav"),
            patch("app.services.dav_discovery._discover_principal", new_callable=AsyncMock, return_value="https://nc.example.com/dav/principals/admin/"),
            patch("app.services.dav_discovery._discover_homesets", new_callable=AsyncMock, return_value=("https://nc.example.com/dav/ab/", "https://nc.example.com/dav/cal/")),
            patch("app.services.dav_discovery._discover_collections", new_callable=AsyncMock, return_value=[]),
            patch("app.services.dav_discovery.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_dav("https://nc.example.com", "user", "pass")

        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_principal_returns_failure(self):
        with (
            patch("app.services.dav_discovery._discover_dav_url", new_callable=AsyncMock, return_value="https://nc.example.com/dav"),
            patch("app.services.dav_discovery._discover_principal", new_callable=AsyncMock, return_value=None),
            patch("app.services.dav_discovery.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_dav("https://nc.example.com", "user", "pass")

        assert result.success is False
        assert "Authentication" in result.message

    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self):
        with patch("app.services.dav_discovery.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_dav("https://nc.example.com", "user", "pass")

        assert result.success is False
        assert "timed out" in result.message

    @pytest.mark.asyncio
    async def test_generic_exception_returns_failure(self):
        with patch("app.services.dav_discovery.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(side_effect=RuntimeError("unexpected"))
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_dav("https://nc.example.com", "user", "pass")

        assert result.success is False
        assert "unexpected" in result.message

    @pytest.mark.asyncio
    async def test_no_collections_message(self):
        with (
            patch("app.services.dav_discovery._discover_dav_url", new_callable=AsyncMock, return_value="https://nc.example.com/dav"),
            patch("app.services.dav_discovery._discover_principal", new_callable=AsyncMock, return_value="https://nc.example.com/dav/p/"),
            patch("app.services.dav_discovery._discover_homesets", new_callable=AsyncMock, return_value=(None, None)),
            patch("app.services.dav_discovery.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_dav("https://nc.example.com", "user", "pass")

        assert result.success is True
        assert "no collections" in result.message.lower()
