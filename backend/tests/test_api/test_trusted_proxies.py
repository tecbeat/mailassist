"""Tests for trusted proxy IP extraction in get_client_ip."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.core.middleware import get_client_ip


def _make_request(client_host: str, forwarded_for: str | None = None) -> MagicMock:
    """Create a fake Starlette Request with configurable client and headers."""
    request = MagicMock()
    request.client = MagicMock()
    request.client.host = client_host
    headers: dict[str, str] = {}
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for
    request.headers = headers
    return request


def test_no_trusted_proxies_ignores_forwarded_for():
    """Without trusted proxies configured, X-Forwarded-For is ignored."""
    request = _make_request("10.0.0.1", forwarded_for="1.2.3.4")
    with patch("app.core.middleware.get_settings") as mock_settings:
        mock_settings.return_value.trusted_proxies = []
        result = get_client_ip(request)
    assert result == "10.0.0.1"


def test_trusted_proxy_uses_forwarded_for():
    """When direct client is a trusted proxy, use X-Forwarded-For."""
    request = _make_request("10.0.0.1", forwarded_for="203.0.113.50, 10.0.0.1")
    with patch("app.core.middleware.get_settings") as mock_settings:
        mock_settings.return_value.trusted_proxies = ["10.0.0.0/8"]
        result = get_client_ip(request)
    assert result == "203.0.113.50"


def test_untrusted_proxy_ignores_forwarded_for():
    """When direct client is NOT a trusted proxy, ignore X-Forwarded-For."""
    request = _make_request("192.168.1.50", forwarded_for="1.2.3.4")
    with patch("app.core.middleware.get_settings") as mock_settings:
        mock_settings.return_value.trusted_proxies = ["10.0.0.0/8"]
        result = get_client_ip(request)
    assert result == "192.168.1.50"


def test_trusted_proxy_exact_ip():
    """Trusted proxy can be a single IP (not CIDR)."""
    request = _make_request("172.17.0.2", forwarded_for="8.8.8.8")
    with patch("app.core.middleware.get_settings") as mock_settings:
        mock_settings.return_value.trusted_proxies = ["172.17.0.2"]
        result = get_client_ip(request)
    assert result == "8.8.8.8"


def test_trusted_proxy_no_forwarded_for_falls_back():
    """Trusted proxy without X-Forwarded-For returns direct IP."""
    request = _make_request("10.0.0.1")
    with patch("app.core.middleware.get_settings") as mock_settings:
        mock_settings.return_value.trusted_proxies = ["10.0.0.0/8"]
        result = get_client_ip(request)
    assert result == "10.0.0.1"


def test_no_client_returns_unknown():
    """Missing request.client returns 'unknown'."""
    request = MagicMock()
    request.client = None
    request.headers = {}
    with patch("app.core.middleware.get_settings") as mock_settings:
        mock_settings.return_value.trusted_proxies = []
        result = get_client_ip(request)
    assert result == "unknown"
