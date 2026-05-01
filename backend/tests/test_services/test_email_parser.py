"""Tests for email parsing robustness with empty or minimal bodies.

Verifies that the email parser and IMAP fetch logic handle edge cases
gracefully — no crashes, no account pausing for content-level issues.
"""

from __future__ import annotations

import pytest

from app.services.email_parser import parse_email

# ---------------------------------------------------------------------------
# Helpers — minimal RFC822 messages
# ---------------------------------------------------------------------------

HEADERS_ONLY = (
    b"From: sender@example.com\r\n"
    b"To: user@example.com\r\n"
    b"Subject: No body at all\r\n"
    b"Date: Mon, 14 Apr 2026 12:00:00 +0000\r\n"
    b"Message-ID: <empty-body-1@example.com>\r\n"
    b"\r\n"
)

EMPTY_BODY = (
    b"From: sender@example.com\r\n"
    b"To: user@example.com\r\n"
    b"Subject: Empty body\r\n"
    b"Message-ID: <empty-body-2@example.com>\r\n"
    b"\r\n"
    b""
)

SHORT_BODY = (
    b"From: sender@example.com\r\nTo: user@example.com\r\nSubject: Short\r\nMessage-ID: <short-1@example.com>\r\n\r\nHi"
)

WHITESPACE_BODY = (
    b"From: sender@example.com\r\n"
    b"To: user@example.com\r\n"
    b"Subject: Whitespace\r\n"
    b"Message-ID: <ws-1@example.com>\r\n"
    b"\r\n"
    b"   \r\n  \r\n"
)

ATTACHMENT_ONLY = (
    b"From: sender@example.com\r\n"
    b"To: user@example.com\r\n"
    b"Subject: Attachment only\r\n"
    b"Message-ID: <attach-1@example.com>\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/mixed; boundary="BOUNDARY"\r\n'
    b"\r\n"
    b"--BOUNDARY\r\n"
    b"Content-Type: application/pdf\r\n"
    b'Content-Disposition: attachment; filename="report.pdf"\r\n'
    b"Content-Transfer-Encoding: base64\r\n"
    b"\r\n"
    b"JVBERi0xLjQKMSAwIG9iago=\r\n"
    b"--BOUNDARY--\r\n"
)

HTML_ONLY = (
    b"From: sender@example.com\r\n"
    b"To: user@example.com\r\n"
    b"Subject: HTML only\r\n"
    b"Message-ID: <html-1@example.com>\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"\r\n"
    b"<p>Hello</p>"
)

MULTIPART_EMPTY_PARTS = (
    b"From: sender@example.com\r\n"
    b"To: user@example.com\r\n"
    b"Subject: Empty multipart\r\n"
    b"Message-ID: <empty-multi-1@example.com>\r\n"
    b"MIME-Version: 1.0\r\n"
    b'Content-Type: multipart/alternative; boundary="BOUNDARY"\r\n'
    b"\r\n"
    b"--BOUNDARY\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"\r\n"
    b"--BOUNDARY\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"\r\n"
    b"\r\n"
    b"--BOUNDARY--\r\n"
)


# ---------------------------------------------------------------------------
# parse_email — empty / minimal body
# ---------------------------------------------------------------------------


class TestParseEmailEmptyBody:
    """parse_email must not raise on emails with no body content."""

    def test_headers_only(self):
        result = parse_email(HEADERS_ONLY, "100")
        assert result.subject == "No body at all"
        assert result.sender == "sender@example.com"
        assert result.body_plain == ""
        assert result.body_html == ""

    def test_empty_body(self):
        result = parse_email(EMPTY_BODY, "101")
        assert result.subject == "Empty body"
        assert result.body_plain == ""
        assert result.body_html == ""

    def test_short_body(self):
        result = parse_email(SHORT_BODY, "102")
        assert result.subject == "Short"
        assert result.body_plain == "Hi"

    def test_whitespace_body(self):
        result = parse_email(WHITESPACE_BODY, "103")
        assert result.subject == "Whitespace"
        # Body is whitespace — should be preserved, not crash
        assert isinstance(result.body_plain, str)

    def test_attachment_only_no_text(self):
        result = parse_email(ATTACHMENT_ONLY, "104")
        assert result.subject == "Attachment only"
        assert result.body_plain == ""
        assert result.body_html == ""
        assert result.has_attachments is True
        assert "report.pdf" in result.attachment_names

    def test_html_only_no_plain(self):
        result = parse_email(HTML_ONLY, "105")
        assert result.subject == "HTML only"
        assert result.body_plain == ""
        assert result.body_html != ""  # HTML body is present

    def test_multipart_with_empty_parts(self):
        result = parse_email(MULTIPART_EMPTY_PARTS, "106")
        assert result.subject == "Empty multipart"
        # Empty text parts — should not crash


class TestParseEmailMetadata:
    """Metadata extraction works even when body is empty."""

    def test_sender_extracted_without_body(self):
        result = parse_email(HEADERS_ONLY, "200")
        assert result.sender == "sender@example.com"
        assert result.sender_name == "sender@example.com"

    def test_message_id_extracted_without_body(self):
        result = parse_email(HEADERS_ONLY, "201")
        assert result.message_id == "empty-body-1@example.com"

    def test_date_extracted_without_body(self):
        result = parse_email(HEADERS_ONLY, "202")
        assert result.date is not None

    def test_size_reflects_raw_bytes(self):
        result = parse_email(HEADERS_ONLY, "203")
        assert result.size == len(HEADERS_ONLY)

    def test_uid_preserved(self):
        result = parse_email(HEADERS_ONLY, "204")
        assert result.uid == "204"


# ---------------------------------------------------------------------------
# fetch_raw_mail — imaplib-style responses via imap-tools
# ---------------------------------------------------------------------------


class TestFetchRawMailResponse:
    """fetch_raw_mail delegates to fetch_raw_message (which uses imaplib's
    client.uid('FETCH', uid, '(RFC822)')) and list_folders.

    imaplib response format:
      status = "OK"
      data = [(b'UID 123 FETCH (RFC822 {size})', b'raw message bytes'), b')']
    """

    @pytest.mark.asyncio
    async def test_small_mail_accepted(self):
        """A valid small message is fetched and returned correctly."""
        from unittest.mock import AsyncMock, MagicMock, patch

        small_msg = b"Subject: Hi\r\n\r\nOk"

        mock_conn = MagicMock()
        mock_conn.separator = "/"

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_imap_connection(account):
            yield mock_conn

        mock_account = MagicMock()

        with (
            patch(
                "app.workers.pipeline_orchestrator.imap_connection",
                fake_imap_connection,
            ),
            patch(
                "app.workers.pipeline_orchestrator.fetch_raw_message",
                AsyncMock(return_value=small_msg),
            ),
            patch(
                "app.workers.pipeline_orchestrator.list_folders",
                AsyncMock(return_value=["INBOX"]),
            ),
            patch(
                # ``fetch_raw_mail`` now consults the Valkey folder cache before
                # listing folders.  Without these patches the test runs against
                # an uninitialised Valkey client, the ``except`` branch fires and
                # ``folders`` returns ``[]``.
                "app.workers.pipeline_orchestrator.get_cached_folders",
                AsyncMock(return_value=None),
            ),
            patch(
                "app.workers.pipeline_orchestrator.set_cached_folders",
                AsyncMock(),
            ),
        ):
            import structlog

            from app.workers.pipeline_orchestrator import fetch_raw_mail

            log = structlog.get_logger()
            raw, folders, sep = await fetch_raw_mail(
                mock_account,
                "123",
                "INBOX",
                log,
            )

        assert raw == small_msg
        assert folders == ["INBOX"]
        assert sep == "/"

    @pytest.mark.asyncio
    async def test_normal_email_returned(self):
        """fetch_raw_mail returns the raw bytes from fetch_raw_message."""
        from unittest.mock import AsyncMock, MagicMock, patch

        email_body = b"From: sender@example.com\r\nSubject: Test\r\n\r\nHello world"

        mock_conn = MagicMock()
        mock_conn.separator = "/"

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_imap_connection(account):
            yield mock_conn

        mock_account = MagicMock()

        with (
            patch(
                "app.workers.pipeline_orchestrator.imap_connection",
                fake_imap_connection,
            ),
            patch(
                "app.workers.pipeline_orchestrator.fetch_raw_message",
                AsyncMock(return_value=email_body),
            ),
            patch(
                "app.workers.pipeline_orchestrator.list_folders",
                AsyncMock(return_value=["INBOX"]),
            ),
        ):
            import structlog

            from app.workers.pipeline_orchestrator import fetch_raw_mail

            log = structlog.get_logger()
            raw, _folders, _sep = await fetch_raw_mail(
                mock_account,
                "123",
                "INBOX",
                log,
            )

        assert raw == email_body

    @pytest.mark.asyncio
    async def test_deleted_uid_raises(self):
        """If UID doesn't exist, fetch_raw_message raises ValueError
        which is converted to IMAPFetchError."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_conn = MagicMock()
        mock_conn.separator = "/"

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_imap_connection(account):
            yield mock_conn

        mock_account = MagicMock()

        with (
            patch(
                "app.workers.pipeline_orchestrator.imap_connection",
                fake_imap_connection,
            ),
            patch(
                "app.workers.pipeline_orchestrator.fetch_raw_message",
                AsyncMock(side_effect=ValueError("no_message_body_in_response")),
            ),
        ):
            import structlog

            from app.workers.pipeline_orchestrator import (
                IMAPFetchError,
                fetch_raw_mail,
            )

            log = structlog.get_logger()
            with pytest.raises(IMAPFetchError, match="no_message_body_in_response"):
                await fetch_raw_mail(mock_account, "999", "INBOX", log)

    @pytest.mark.asyncio
    async def test_fetch_failed_raises(self):
        """If IMAP FETCH returns non-OK, fetch_raw_message raises ValueError
        with 'imap_fetch_failed' which is converted to IMAPFetchError."""
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_conn = MagicMock()
        mock_conn.separator = "/"

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_imap_connection(account):
            yield mock_conn

        mock_account = MagicMock()

        with (
            patch(
                "app.workers.pipeline_orchestrator.imap_connection",
                fake_imap_connection,
            ),
            patch(
                "app.workers.pipeline_orchestrator.fetch_raw_message",
                AsyncMock(side_effect=ValueError("imap_fetch_failed: NO")),
            ),
        ):
            import structlog

            from app.workers.pipeline_orchestrator import (
                IMAPFetchError,
                fetch_raw_mail,
            )

            log = structlog.get_logger()
            with pytest.raises(IMAPFetchError):
                await fetch_raw_mail(mock_account, "123", "INBOX", log)
