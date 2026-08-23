"""Tool: search_contacts — search user's contacts by name or email."""

from __future__ import annotations

import json
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import String, cast, or_, select

from app.models.contacts import Contact
from app.tools.base import BaseTool, ToolResult
from app.tools.registry import register_tool


@register_tool
class SearchContactsTool(BaseTool):
    """Search the user's contact list by name or email."""

    name = "search_contacts"
    description = (
        "Search the user's synced contacts by name or email address. "
        "Returns up to 10 matching contacts with name, email, organization, "
        "and title. Use this to find contact information or verify identities."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — matches against display name, first/last name, and emails.",
            },
        },
        "required": ["query"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Search contacts."""
        if self._mail_context is None or self._db is None:
            return ToolResult(content="No context available.", is_error=True)

        query: str = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(content="Query parameter is required.", is_error=True)

        user_id = UUID(self._mail_context.user_id)
        pattern = f"%{query}%"

        stmt = (
            select(Contact)
            .where(
                Contact.user_id == user_id,
                or_(
                    Contact.display_name.ilike(pattern),
                    Contact.first_name.ilike(pattern),
                    Contact.last_name.ilike(pattern),
                    Contact.organization.ilike(pattern),
                    # JSONB array text search
                    cast(Contact.emails, String).ilike(pattern),
                ),
            )
            .limit(10)
        )

        result = await self._db.execute(stmt)
        contacts = result.scalars().all()

        if not contacts:
            return ToolResult(content=f"No contacts found matching '{query}'.")

        contact_list = []
        for c in contacts:
            contact_list.append(
                {
                    "id": str(c.id),
                    "display_name": c.display_name,
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "emails": c.emails,
                    "organization": c.organization,
                    "title": c.title,
                }
            )

        return ToolResult(
            content=json.dumps(
                {"count": len(contact_list), "contacts": contact_list},
                default=str,
            )
        )
