"""Calendar extraction AI plugin.

Detects meetings, appointments, and date/time mentions in emails.
Creates CalDAV events when configured. Always requires approval
regardless of user settings (high-impact external action).
Runs sixth in the pipeline (execution_order=60).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin


class CalendarEventResponse(BaseModel):
    """Validated LLM response for calendar extraction."""

    has_event: bool
    title: str | None = Field(default=None, max_length=300)
    start: str | None = None
    end: str | None = None
    location: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)
    is_all_day: bool = False

    @field_validator("start", "end", mode="before")
    @classmethod
    def validate_iso_datetime(cls, v: str | None) -> str | None:
        """Ensure start/end are valid ISO 8601 datetimes, discard otherwise."""
        if v is None:
            return None
        v = v.strip()
        try:
            datetime.fromisoformat(v)
            return v
        except (ValueError, TypeError):
            # LLM returned non-ISO string (e.g. "next Tuesday") — discard
            return None


@register_plugin
class CalendarExtractionPlugin(AIFunctionPlugin[CalendarEventResponse]):
    """Detect and extract calendar events from emails."""

    name = "calendar_extraction"
    display_name = "Calendar Extraction"
    description = "Detects meetings and appointments, creates CalDAV events (always requires approval)"
    default_prompt_template = "prompts/calendar_extraction.j2"
    execution_order = 60
    icon = "CalendarDays"
    approval_key = "calendar"
    has_view_page = True
    view_route = "/calendar"
    notification_event_type = "calendar_event_created"
    notification_template = "notifications/calendar_created.j2"

    async def execute(self, context: MailContext, ai_response: CalendarEventResponse) -> ActionResult:
        if not ai_response.has_event:
            return self._no_action("no_calendar_event_found")

        if not ai_response.title or not ai_response.start:
            return ActionResult(
                success=True,
                actions_taken=["event_detected_but_incomplete"],
            )

        actions: list[str] = [
            "apply_label:calendar",
            f"create_calendar_event:{ai_response.title}",
        ]

        if ai_response.location:
            actions.append(f"event_location:{ai_response.location}")

        self.logger.info(
            "calendar_event_detected",
            title=ai_response.title,
            start=ai_response.start,
            mail_uid=context.mail_uid,
        )

        # Calendar extraction always requires approval
        return ActionResult(
            success=True,
            actions_taken=actions,
            requires_approval=True,
            approval_summary=self.get_approval_summary(ai_response),
        )

    def get_approval_summary(self, ai_response: CalendarEventResponse) -> str:
        return f"Calendar event: '{ai_response.title}' on {ai_response.start}"

    @classmethod
    def get_notification_context(cls, result_data: dict[str, Any]) -> dict[str, Any]:
        return {"calendar_event": result_data.get("calendar_event", {})}

    @classmethod
    async def load_notification_context(
        cls,
        db: Any,
        account_id: Any,
        mail_uid: str,
    ) -> dict[str, Any]:
        """Load calendar event data from the database for notification context."""
        from sqlalchemy import select

        from app.models.mail import CalendarEvent

        result = await db.execute(
            select(CalendarEvent).where(
                CalendarEvent.mail_account_id == account_id,
                CalendarEvent.mail_uid == mail_uid,
            )
        )
        cal = result.scalar_one_or_none()
        if cal:
            return {
                "calendar_event": {
                    "title": cal.title,
                    "start": cal.start,
                    "end": cal.end,
                    "location": cal.location,
                    "description": cal.description,
                },
            }
        return {}

    @classmethod
    def get_notification_variables(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "calendar_event",
                "var_type": "Dict",
                "description": "Extracted calendar event (title, start, end, location, description)",
                "example": '{"title": "Team Meeting", "start": "2026-03-31T14:00:00Z", "location": "Room 5"}',
            },
        ]

    @classmethod
    def get_preview_context(cls) -> dict[str, Any]:
        return {
            "calendar_event": {
                "title": "Team Meeting",
                "start": "2026-03-31T14:00:00Z",
                "end": "2026-03-31T15:00:00Z",
                "location": "Room 5",
                "description": "Quarterly review",
            },
        }
