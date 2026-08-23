"""Tool: get_user_data — query user-specific data (labels, folders, contacts, rules)."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from app.tools.base import BaseTool, ToolResult
from app.tools.registry import register_tool


@register_tool
class GetUserDataTool(BaseTool):
    """Provides access to user-specific application data for context-aware decisions."""

    name = "get_user_data"
    description = (
        "Query user-specific data: available IMAP folders and labels, "
        "contact list (names and emails), and account configuration. "
        "Use this when you need to know what folders exist, who the user's "
        "contacts are, or what the account setup looks like."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["folders", "contacts", "account", "all"],
                "description": (
                    "Which data to retrieve. "
                    "'folders' = available IMAP folders and labels, "
                    "'contacts' = user's contact list, "
                    "'account' = mail account configuration, "
                    "'all' = everything."
                ),
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Return user-specific data."""
        if self._mail_context is None:
            return ToolResult(content="No mail context available.", is_error=True)

        section: str = kwargs.get("section", "all")
        ctx = self._mail_context
        result: dict[str, Any] = {}

        if section in ("folders", "all"):
            result["folders"] = {
                "available": ctx.existing_folders,
                "excluded": ctx.excluded_folders,
                "labels": ctx.existing_labels,
                "separator": ctx.folder_separator,
            }

        if section in ("contacts", "all"):
            contacts: list[dict[str, str]] = []
            if ctx.user_contacts:
                for c in ctx.user_contacts:
                    contacts.append(
                        {
                            "name": c.get("name", ""),
                            "email": c.get("email", ""),
                        }
                    )
            result["contacts"] = {
                "count": len(contacts),
                "list": contacts,
            }

        if section in ("account", "all"):
            result["account"] = {
                "name": ctx.account_name,
                "email": ctx.account_email,
            }

        if not result:
            return ToolResult(
                content=f"Unknown section '{section}'. Use 'folders', 'contacts', 'account', or 'all'.",
                is_error=True,
            )

        return ToolResult(content=json.dumps(result, default=str))
