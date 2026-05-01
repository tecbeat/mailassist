"""Email parsing service.

Handles MIME multipart parsing, character encoding, HTML sanitization,
and extraction of email metadata. Robust against malformed emails.
"""

import email
import email.policy
import re
from datetime import datetime
from email.header import decode_header as decode_email_header
from email.utils import parseaddr, parsedate_to_datetime

import structlog

from app.services.mail import ParsedEmail

logger = structlog.get_logger()

# Maximum body size before truncation (configurable via settings)
DEFAULT_MAX_BODY_SIZE = 51200  # 50KB


def _decode_header(header_value: str | None) -> str:
    """Decode an email header value, handling various encodings."""
    if header_value is None:
        return ""

    decoded_parts = []
    for part, charset in decode_email_header(header_value):
        if isinstance(part, bytes):
            charset = charset or "utf-8"
            try:
                decoded_parts.append(part.decode(charset, errors="replace"))
            except (LookupError, UnicodeDecodeError):
                decoded_parts.append(part.decode("utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return " ".join(decoded_parts)


def _extract_body(msg: email.message.Message, max_size: int = DEFAULT_MAX_BODY_SIZE) -> tuple[str, str]:
    """Extract plain text and HTML body from a MIME message.

    Returns (body_plain, body_html). Prefers text/plain for AI processing.
    Truncates to max_size bytes.
    """
    body_plain = ""
    body_html = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue

                charset = part.get_content_charset() or "utf-8"
                try:
                    text = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = payload.decode("utf-8", errors="replace")

                if content_type == "text/plain" and not body_plain:
                    body_plain = text[:max_size]
                elif content_type == "text/html" and not body_html:
                    body_html = text[:max_size]

            except Exception:
                # Expected with malformed MIME parts; skip and try next.
                logger.debug("body_extraction_failed", content_type=content_type)
                continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                try:
                    text = payload.decode(charset, errors="replace")
                except (LookupError, UnicodeDecodeError):
                    text = payload.decode("utf-8", errors="replace")

                if msg.get_content_type() == "text/html":
                    body_html = text[:max_size]
                else:
                    body_plain = text[:max_size]
        except Exception:
            # Expected with malformed single-part messages.
            logger.debug("body_extraction_failed_single_part")

    if not body_plain and not body_html:
        logger.debug("email_body_empty", msg="no text/plain or text/html parts found")

    return body_plain, body_html


def _sanitize_html(html: str) -> str:
    """Sanitize HTML: strip scripts, styles, tracking pixels."""
    if not html:
        return html
    try:
        import nh3
        return nh3.clean(html)
    except ImportError:
        # Basic fallback: strip all tags
        return re.sub(r"<[^>]+>", "", html)


def _extract_attachments(msg: email.message.Message) -> tuple[bool, list[str]]:
    """Extract attachment filenames and determine if message has attachments."""
    attachment_names: list[str] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:
                    attachment_names.append(_decode_header(filename))

    has_attachments = len(attachment_names) > 0
    return has_attachments, attachment_names


def parse_email(raw_bytes: bytes, uid: str, max_body_size: int = DEFAULT_MAX_BODY_SIZE) -> ParsedEmail:
    """Parse a raw email message into a structured ParsedEmail object.

    Uses lenient parsing policy for malformed emails.
    """
    # Use default policy for lenient parsing of malformed emails
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)

    # Parse sender
    sender_name_raw, sender_email = parseaddr(str(msg.get("From", "")))
    sender_name = _decode_header(sender_name_raw) or sender_email
    sender = sender_email.lower() if sender_email else ""

    # Parse recipient
    _, recipient = parseaddr(str(msg.get("To", "")))
    cc = _decode_header(str(msg.get("Cc", "")))

    # Subject
    subject = _decode_header(str(msg.get("Subject", "")))

    # Date
    date_str = msg.get("Date", "")
    email_date: datetime | None = None
    if date_str:
        try:
            email_date = parsedate_to_datetime(str(date_str))
        except Exception:
            # Common with non-standard date headers; falls back to None.
            logger.debug("date_parse_failed", date_str=date_str)

    # Message-ID
    message_id = str(msg.get("Message-ID", "")).strip("<>")

    # Thread detection
    in_reply_to = str(msg.get("In-Reply-To", "")).strip("<>") or None
    references_raw = str(msg.get("References", ""))
    references = [r.strip("<>") for r in references_raw.split() if r.strip("<>")]

    is_reply = bool(in_reply_to or subject.lower().startswith("re:"))
    is_forwarded = subject.lower().startswith(("fwd:", "fw:"))

    # Extract body
    body_plain, body_html = _extract_body(msg, max_body_size)

    # Sanitize HTML body
    body_html_sanitized = _sanitize_html(body_html)

    # Determine combined body (prefer plain text)
    body = body_plain if body_plain else body_html_sanitized

    # Extract attachments
    has_attachments, attachment_names = _extract_attachments(msg)

    # Extract all headers, preserving duplicate header names (valid per RFC 2822,
    # e.g. multiple Received headers) by joining repeated values with a newline.
    headers: dict[str, str] = {}
    for k, v in msg.items():
        decoded = _decode_header(str(v))
        if k in headers:
            headers[k] = f"{headers[k]}\n{decoded}"
        else:
            headers[k] = decoded

    # Calculate size
    size = len(raw_bytes)

    return ParsedEmail(
        uid=uid,
        message_id=message_id,
        sender=sender,
        sender_name=sender_name,
        recipient=recipient,
        cc=cc,
        subject=subject,
        date=email_date,
        body_plain=body_plain,
        body_html=body_html_sanitized,
        headers=headers,
        has_attachments=has_attachments,
        attachment_names=attachment_names,
        size=size,
        is_reply=is_reply,
        is_forwarded=is_forwarded,
        in_reply_to=in_reply_to,
        references=references,
    )
