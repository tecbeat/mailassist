"""Calendar extraction AI plugin.

Detects meetings, appointments, and date/time mentions in emails.
Creates CalDAV events when configured. Always requires approval
regardless of user settings (high-impact external action).
Runs sixth in the pipeline (execution_order=60).
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.plugins.base import AIFunctionPlugin, ActionResult, MailContext
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
