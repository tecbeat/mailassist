"""Tool: check_conflicts — check for calendar scheduling conflicts."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import select

from app.models.contacts import CalDAVConfig
from app.services.calendar import get_caldav_credentials, search_calendar_events
from app.tools.base import BaseTool, ToolResult
from app.tools.registry import register_tool


@register_tool
class CheckConflictsTool(BaseTool):
    """Check for scheduling conflicts in a proposed time window."""

    name = "check_conflicts"
    description = (
        "Check if there are any existing calendar events that conflict with "
        "a proposed time window. Returns conflicting events if any exist. "
        "Use this before proposing or creating calendar events to avoid "
        "double-booking."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "proposed_start": {
                "type": "string",
                "description": "Proposed event start in ISO 8601 format.",
            },
            "proposed_end": {
                "type": "string",
                "description": "Proposed event end in ISO 8601 format.",
            },
        },
        "required": ["proposed_start", "proposed_end"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Check for conflicts in the proposed time window."""
        if self._mail_context is None or self._db is None:
            return ToolResult(content="No context available.", is_error=True)

        try:
            start = datetime.fromisoformat(kwargs["proposed_start"])
            end = datetime.fromisoformat(kwargs["proposed_end"])
        except (KeyError, ValueError) as e:
            return ToolResult(content=f"Invalid date format: {e}", is_error=True)

        user_id = UUID(self._mail_context.user_id)
        result = await self._db.execute(
            select(CalDAVConfig).where(
                CalDAVConfig.user_id == user_id,
                CalDAVConfig.is_active.is_(True),
            )
        )
        config = result.scalar_one_or_none()

        if config is None:
            return ToolResult(
                content="Calendar (CalDAV) is not configured. Cannot check conflicts."
            )

        username, password = get_caldav_credentials(config.encrypted_credentials)

        try:
            events = await search_calendar_events(
                caldav_url=config.caldav_url,
                username=username,
                password=password,
                calendar_name=config.default_calendar,
                start=start,
                end=end,
            )
        except Exception as e:
            return ToolResult(content=f"Calendar query failed: {e}", is_error=True)

        if not events:
            return ToolResult(
                content=json.dumps(
                    {"has_conflicts": False, "message": "No conflicts found. Time slot is free."},
                    default=str,
                )
            )

        return ToolResult(
            content=json.dumps(
                {
                    "has_conflicts": True,
                    "conflict_count": len(events),
                    "conflicts": [asdict(ev) for ev in events],
                },
                default=str,
            )
        )
