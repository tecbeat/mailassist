"""Deterministic email header analysis for spam detection.

Extracts technical indicators from email headers (SPF, DKIM, DMARC,
header mismatches) without any network calls. Results are injected
into the spam detection prompt as verified facts.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict


class AuthResult(TypedDict, total=False):
    """Single authentication check result."""

    result: str  # pass, fail, softfail, neutral, none, temperror, permerror
    detail: str  # e.g. "smtp.mailfrom=example.com"


class TechnicalIndicators(TypedDict, total=False):
    """Deterministic technical indicators extracted from email headers."""

    spf: AuthResult
    dkim: AuthResult
    dmarc: AuthResult
    reply_to_mismatch: bool
    reply_to_domain: str
    from_domain: str
    display_name_spoofing: bool
    display_name_email: str
    return_path_mismatch: bool
    return_path: str


# Regex for key=value pairs inside Authentication-Results
_AUTH_KV_RE = re.compile(r"(\w[\w.-]*)=([^\s;]+)")

# Known auth method names
_AUTH_METHODS = {"spf", "dkim", "dmarc", "arc"}

# Valid result values per RFC 8601
_VALID_RESULTS = {"pass", "fail", "softfail", "neutral", "none", "temperror", "permerror"}

# Email pattern in display names
_EMAIL_IN_NAME_RE = re.compile(r"[\w.+-]+@[\w.-]+\.\w{2,}")


def _extract_domain(address: str) -> str:
    """Extract lowercase domain from an email address."""
    _, _, domain = address.rpartition("@")
    return domain.lower().strip().rstrip(">")


def parse_authentication_results(headers: dict[str, str]) -> dict[str, AuthResult]:
    """Parse Authentication-Results (and ARC-Authentication-Results) headers.

    Handles multiple headers (joined by newline in the headers dict),
    multiple results per header, and various formatting styles.

    Returns dict with keys 'spf', 'dkim', 'dmarc' where present.
    """
    results: dict[str, AuthResult] = {}

    raw_parts: list[str] = []
    for key in ("Authentication-Results", "ARC-Authentication-Results"):
        val = headers.get(key, "")
        if val:
            raw_parts.extend(val.split("\n"))

    for raw in raw_parts:
        # Strip the authserv-id (everything before the first semicolon)
        _, _, body = raw.partition(";")
        if not body:
            body = raw

        # Split on semicolons to get individual method results
        for segment in body.split(";"):
            segment = segment.strip()
            if not segment:
                continue

            # Format: "method=result (detail)" or "method=result key=value"
            parts = segment.split(None, 1)
            if not parts:
                continue

            token = parts[0].lower()

            # Try "method=result" format
            if "=" in token:
                method, _, result_val = token.partition("=")
                method = method.strip().lower()
            else:
                # Sometimes the method name is separate: "dkim pass ..."
                method = token
                if len(parts) > 1:
                    rest_parts = parts[1].split(None, 1)
                    result_val = rest_parts[0].lower() if rest_parts else ""
                else:
                    continue

            # Normalize method name
            if method not in _AUTH_METHODS:
                continue
            if method == "arc":
                continue  # ARC results are informational, skip

            result_val = result_val.lower().strip()
            if result_val not in _VALID_RESULTS:
                continue

            # Already have a result for this method — first wins
            if method in results:
                continue

            # Extract detail (key=value pairs after the result)
            detail = ""
            if len(parts) > 1:
                kvs = _AUTH_KV_RE.findall(parts[1])
                if kvs:
                    detail = " ".join(f"{k}={v}" for k, v in kvs)

            results[method] = AuthResult(result=result_val, detail=detail)

    return results


def check_reply_to_mismatch(headers: dict[str, str], from_domain: str) -> tuple[bool, str]:
    """Check if Reply-To domain differs from From domain.

    Returns (is_mismatch, reply_to_domain).
    """
    reply_to = headers.get("Reply-To", "")
    if not reply_to:
        return False, ""

    rt_domain = _extract_domain(reply_to)
    if not rt_domain:
        return False, ""

    return rt_domain != from_domain, rt_domain


def check_display_name_spoofing(sender_name: str, sender_email: str) -> tuple[bool, str]:
    """Detect display name containing an email that differs from actual From.

    Classic phishing trick: 'support@paypal.com <attacker@evil.com>'

    Returns (is_spoofed, email_found_in_name).
    """
    if not sender_name:
        return False, ""

    match = _EMAIL_IN_NAME_RE.search(sender_name)
    if not match:
        return False, ""

    name_email = match.group(0).lower()
    if name_email == sender_email.lower():
        return False, ""

    return True, name_email


def check_return_path_mismatch(headers: dict[str, str], from_domain: str) -> tuple[bool, str]:
    """Check if Return-Path domain differs from From domain.

    Returns (is_mismatch, return_path_value).
    """
    return_path = headers.get("Return-Path", "")
    if not return_path:
        return False, ""

    rp_domain = _extract_domain(return_path)
    if not rp_domain:
        return False, ""

    return rp_domain != from_domain, return_path.strip().strip("<>")


def analyze_headers(
    headers: dict[str, str],
    sender_email: str,
    sender_name: str = "",
) -> dict[str, Any]:
    """Top-level function: extract all technical indicators from headers.

    Returns a dict suitable for injection into MailContext and prompt templates.
    """
    from_domain = _extract_domain(sender_email)

    auth_results = parse_authentication_results(headers)

    rt_mismatch, rt_domain = check_reply_to_mismatch(headers, from_domain)
    dn_spoofing, dn_email = check_display_name_spoofing(sender_name, sender_email)
    rp_mismatch, rp_value = check_return_path_mismatch(headers, from_domain)

    indicators: dict[str, Any] = {
        "from_domain": from_domain,
    }

    if "spf" in auth_results:
        indicators["spf"] = auth_results["spf"]
    if "dkim" in auth_results:
        indicators["dkim"] = auth_results["dkim"]
    if "dmarc" in auth_results:
        indicators["dmarc"] = auth_results["dmarc"]

    if rt_mismatch:
        indicators["reply_to_mismatch"] = True
        indicators["reply_to_domain"] = rt_domain
    if dn_spoofing:
        indicators["display_name_spoofing"] = True
        indicators["display_name_email"] = dn_email
    if rp_mismatch:
        indicators["return_path_mismatch"] = True
        indicators["return_path"] = rp_value

    return indicators
