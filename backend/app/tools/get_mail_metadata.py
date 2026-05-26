"""Tool: get_mail_metadata — access extended mail metadata beyond the prompt."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from app.tools.base import BaseTool, ToolResult
from app.tools.registry import register_tool


@register_tool
class GetMailMetadataTool(BaseTool):
    """Exposes extended mail headers, attachment details, and thread context."""

    name = "get_mail_metadata"
    description = (
        "Access extended email metadata not included in the main prompt. "
        "Returns headers (Reply-To, List-Unsubscribe, DKIM, X-headers), "
        "attachment details (filenames, MIME types, sizes), and thread info "
        "(In-Reply-To, References). Use when you need technical email details "
        "to make a decision."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["headers", "attachments", "thread", "all"],
                "description": (
                    "Which metadata section to retrieve. "
                    "'headers' = extended headers, "
                    "'attachments' = attachment details, "
                    "'thread' = conversation threading info, "
                    "'all' = everything."
                ),
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Return extended mail metadata."""
        if self._mail_context is None:
            return ToolResult(content="No mail context available.", is_error=True)

        section: str = kwargs.get("section", "all")
        ctx = self._mail_context
        result: dict[str, Any] = {}

        if section in ("headers", "all"):
            # Expose interesting headers beyond basic From/To/Subject
            interesting_headers = [
                "reply-to", "list-unsubscribe", "list-id", "list-post",
                "x-mailer", "x-spam-status", "x-spam-score",
                "authentication-results", "dkim-signature", "arc-authentication-results",
                "precedence", "auto-submitted", "x-auto-response-suppress",
                "content-type", "mime-version",
            ]
            headers: dict[str, str] = {}
            for key, value in ctx.headers.items():
                if key.lower() in interesting_headers or key.lower().startswith("x-"):
                    headers[key] = value
            result["headers"] = headers

        if section in ("attachments", "all"):
            result["attachments"] = {
                "has_attachments": ctx.has_attachments,
                "filenames": ctx.attachment_names,
                "count": len(ctx.attachment_names),
            }

        if section in ("thread", "all"):
            result["thread"] = {
                "is_reply": ctx.is_reply,
                "is_forwarded": ctx.is_forwarded,
                "thread_length": ctx.thread_length,
                "in_reply_to": ctx.headers.get("in-reply-to", ctx.headers.get("In-Reply-To", "")),
                "references": ctx.headers.get("references", ctx.headers.get("References", "")),
            }

        if section in ("technical", "all"):
            result["technical"] = {
                "mail_size": ctx.mail_size,
                "technical_indicators": ctx.technical_indicators,
            }

        if not result:
            return ToolResult(
                content=f"Unknown section '{section}'. Use 'headers', 'attachments', 'thread', or 'all'.",
                is_error=True,
            )

        return ToolResult(content=json.dumps(result, default=str))
