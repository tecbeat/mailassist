"""Tool: fetch_url — fetch and extract text content from a URL."""

from __future__ import annotations

import ipaddress
import re
from typing import Any, ClassVar
from urllib.parse import urlparse

import httpx
import structlog

from app.core.config import get_settings
from app.tools.base import BaseTool, ToolResult
from app.tools.registry import register_tool

logger = structlog.get_logger()

# Private/internal IP ranges to block (SSRF protection)
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

# Simple HTML tag stripper
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private/internal IP."""
    try:
        addr = ipaddress.ip_address(hostname)
        return any(addr in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        # Not a raw IP — allow DNS names (resolved by httpx)
        return False


def _strip_html(html: str) -> str:
    """Crude HTML-to-text conversion."""
    # Remove script/style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


@register_tool
class FetchUrlTool(BaseTool):
    """Fetch content from a URL and return extracted text."""

    name = "fetch_url"
    description = (
        "Fetch a web page or API endpoint and return its text content. "
        "Use this to check links in emails, verify information, or read "
        "referenced web pages. Returns truncated plain text (max ~8000 chars). "
        "Only HTTP/HTTPS URLs are allowed."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch (must be http:// or https://).",
            },
        },
        "required": ["url"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Fetch URL content."""
        url: str = kwargs.get("url", "").strip()
        if not url:
            return ToolResult(content="URL parameter is required.", is_error=True)

        # Validate URL scheme
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return ToolResult(
                content=f"Invalid URL scheme '{parsed.scheme}'. Only http/https allowed.",
                is_error=True,
            )

        # SSRF: block private IPs
        hostname = parsed.hostname or ""
        if _is_private_ip(hostname):
            return ToolResult(
                content="Cannot fetch internal/private IP addresses.",
                is_error=True,
            )

        settings = get_settings()
        timeout = settings.tool_fetch_timeout
        max_length = settings.tool_fetch_max_content_length

        logger.info("tool_fetch_url", url=url)

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "mailassist-tool/1.0"},
                )
                resp.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(content=f"Request timed out after {timeout}s.", is_error=True)
        except httpx.HTTPStatusError as e:
            return ToolResult(content=f"HTTP error {e.response.status_code}: {e.response.reason_phrase}", is_error=True)
        except httpx.RequestError as e:
            return ToolResult(content=f"Request failed: {type(e).__name__}: {e}", is_error=True)

        content_type = resp.headers.get("content-type", "")
        body = resp.text

        # Extract text from HTML
        if "html" in content_type:
            body = _strip_html(body)

        # Truncate
        if len(body) > max_length:
            body = body[:max_length] + "\n\n[Content truncated]"

        return ToolResult(content=body)
