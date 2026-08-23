"""Tool: search_calendar — search CalDAV events within a date range."""

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
class SearchCalendarTool(BaseTool):
    """Search calendar events within a date range, optionally filtering by text."""

    name = "search_calendar"
    description = (
        "Search the user's CalDAV calendar for events within a date range. "
        "Optionally filter by a text query. Returns up to 20 events with "
        "title, start, end, location, and description. Use this to check "
        "what events exist in a time window."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "Start of date range in ISO 8601 format (e.g. '2025-01-15T00:00:00').",
            },
            "end_date": {
                "type": "string",
                "description": "End of date range in ISO 8601 format (e.g. '2025-01-20T23:59:59').",
            },
            "query": {
                "type": "string",
                "description": "Optional text to filter events by title or description.",
            },
        },
        "required": ["start_date", "end_date"],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Search calendar events."""
        if self._mail_context is None or self._db is None:
            return ToolResult(content="No context available.", is_error=True)

        try:
            start = datetime.fromisoformat(kwargs["start_date"])
            end = datetime.fromisoformat(kwargs["end_date"])
        except (KeyError, ValueError) as e:
            return ToolResult(content=f"Invalid date format: {e}", is_error=True)

        # Load CalDAV config
        user_id = UUID(self._mail_context.user_id)
        result = await self._db.execute(
            select(CalDAVConfig).where(
                CalDAVConfig.user_id == user_id,
                CalDAVConfig.is_active.is_(True),
            )
        )
        config = result.scalar_one_or_none()

        if config is None:
            return ToolResult(content="Calendar (CalDAV) is not configured for this user. Cannot search events.")

        username, password = get_caldav_credentials(config.encrypted_credentials)

        try:
            events = await search_calendar_events(
                caldav_url=config.caldav_url,
                username=username,
                password=password,
                calendar_name=config.default_calendar,
                start=start,
                end=end,
                query=kwargs.get("query"),
            )
        except Exception as e:
            return ToolResult(content=f"Calendar search failed: {e}", is_error=True)

        if not events:
            return ToolResult(content="No events found in the specified date range.")

        return ToolResult(
            content=json.dumps(
                {"count": len(events), "events": [asdict(ev) for ev in events]},
                default=str,
            )
        )
