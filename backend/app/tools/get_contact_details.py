"""Tool: get_contact_details — retrieve full details for a specific contact."""

from __future__ import annotations

import json
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import select

from app.models.contacts import Contact
from app.tools.base import BaseTool, ToolResult
from app.tools.registry import register_tool


@register_tool
class GetContactDetailsTool(BaseTool):
    """Retrieve detailed information for a specific contact."""

    name = "get_contact_details"
    description = (
        "Get full details for a specific contact by ID or email address. "
        "Returns name, all emails, phone numbers, organization, title, "
        "and other available information."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "contact_id": {
                "type": "string",
                "description": "The contact UUID (from search_contacts results).",
            },
            "email": {
                "type": "string",
                "description": "Email address to look up. Used if contact_id is not provided.",
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Get contact details."""
        if self._mail_context is None or self._db is None:
            return ToolResult(content="No context available.", is_error=True)

        contact_id: str | None = kwargs.get("contact_id")
        email: str | None = kwargs.get("email")

        if not contact_id and not email:
            return ToolResult(
                content="Provide either 'contact_id' or 'email' to look up a contact.",
                is_error=True,
            )

        user_id = UUID(self._mail_context.user_id)

        if contact_id:
            try:
                cid = UUID(contact_id)
            except ValueError:
                return ToolResult(content=f"Invalid contact_id format: {contact_id}", is_error=True)
            stmt = select(Contact).where(Contact.user_id == user_id, Contact.id == cid)
        else:
            # Search by email in the JSONB emails array
            pattern = f"%{email}%"
            from sqlalchemy import String
            from sqlalchemy.sql import cast

            stmt = select(Contact).where(
                Contact.user_id == user_id,
                cast(Contact.emails, String).ilike(pattern),
            ).limit(1)

        result = await self._db.execute(stmt)
        contact = result.scalar_one_or_none()

        if contact is None:
            lookup = contact_id or email
            return ToolResult(content=f"No contact found for '{lookup}'.")

        details = {
            "id": str(contact.id),
            "display_name": contact.display_name,
            "first_name": contact.first_name,
            "last_name": contact.last_name,
            "emails": contact.emails,
            "phones": contact.phones,
            "organization": contact.organization,
            "title": contact.title,
        }

        return ToolResult(content=json.dumps(details, default=str))
