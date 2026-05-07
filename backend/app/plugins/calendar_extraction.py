"""Calendar extraction AI plugin.

Detects meetings, appointments, and date/time mentions in emails.
Creates CalDAV events when configured. Always requires approval
regardless of user settings (high-impact external action).
Runs sixth in the pipeline (execution_order=60).
"""

from datetime import UTC, datetime
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

        # Check if event is in the past — skip unless user opted in
        if ai_response.start and not context.calendar_include_past_events:
            try:
                event_start = datetime.fromisoformat(ai_response.start)
                # Make offset-naive datetimes UTC-aware for comparison
                if event_start.tzinfo is None:
                    from zoneinfo import ZoneInfo

                    event_start = event_start.replace(tzinfo=ZoneInfo("Europe/Berlin"))
                if event_start < datetime.now(UTC):
                    self.logger.info(
                        "calendar_event_past_skipped",
                        title=ai_response.title,
                        start=ai_response.start,
                        mail_uid=context.mail_uid,
                    )
                    return self._no_action("calendar_event_in_past")
            except (ValueError, TypeError):
                pass  # If we can't parse, proceed normally

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
        """Load calendar event data from the database for notification context.

        Returns both a flat set of variables and the legacy ``calendar_event`` dict
        so existing custom templates continue to work.
        """
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
            start_str = cal.start.isoformat() if cal.start else ""
            end_str = cal.end.isoformat() if cal.end else ""
            return {
                # flat vars
                "event_title": cal.title,
                "event_start": start_str,
                "event_end": end_str,
                "event_location": cal.location or "",
                "event_description": cal.description or "",
                "event_is_all_day": cal.is_all_day,
                # legacy dict for backwards-compat with existing custom templates
                "calendar_event": {
                    "title": cal.title,
                    "start": start_str,
                    "end": end_str,
                    "location": cal.location,
                    "description": cal.description,
                },
            }
        return {}

    @classmethod
    def get_notification_variables(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "event_title",
                "var_type": "String",
                "description": "Title of the calendar event",
                "example": "Team Meeting",
            },
            {
                "name": "event_start",
                "var_type": "String",
                "description": "Start date/time in ISO 8601 format",
                "example": "2026-03-31T14:00:00+00:00",
            },
            {
                "name": "event_end",
                "var_type": "String",
                "description": "End date/time in ISO 8601 format (empty if not set)",
                "example": "2026-03-31T15:00:00+00:00",
            },
            {
                "name": "event_location",
                "var_type": "String",
                "description": "Location of the event (empty string if not set)",
                "example": "Room 5",
            },
            {
                "name": "event_description",
                "var_type": "String",
                "description": "Description / notes for the event",
                "example": "Quarterly review",
            },
            {
                "name": "event_is_all_day",
                "var_type": "Boolean",
                "description": "True if this is an all-day event",
                "example": "false",
            },
        ]

    @classmethod
    def get_preview_context(cls) -> dict[str, Any]:
        return {
            "event_title": "Team Meeting",
            "event_start": "2026-03-31T14:00:00+00:00",
            "event_end": "2026-03-31T15:00:00+00:00",
            "event_location": "Room 5",
            "event_description": "Quarterly review",
            "event_is_all_day": False,
            "calendar_event": {
                "title": "Team Meeting",
                "start": "2026-03-31T14:00:00+00:00",
                "end": "2026-03-31T15:00:00+00:00",
                "location": "Room 5",
                "description": "Quarterly review",
            },
        }
