"""Email summary AI plugin.

Generates concise summaries of emails with urgency assessment.
Runs last in the pipeline (execution_order=75) to benefit from
context gathered by prior plugins. Summaries are stored in DB
and optionally forwarded via notification if filter rules match.
"""

from typing import Annotated, Any

from pydantic import BaseModel, Field, StringConstraints

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin


class EmailSummaryResponse(BaseModel):
    """Validated LLM response for email summary."""

    summary: str = Field(max_length=500)
    key_points: list[Annotated[str, StringConstraints(max_length=500)]] = Field(default_factory=list, max_length=10)
    urgency: str = Field(pattern=r"^(low|medium|high|critical)$")
    action_required: bool
    action_description: str | None = Field(default=None, max_length=200)


@register_plugin
class EmailSummaryPlugin(AIFunctionPlugin[EmailSummaryResponse]):
    """Generate concise email summaries with urgency assessment."""

    name = "email_summary"
    display_name = "Email Summary"
    description = "Summarizes emails with key points and urgency level for dashboard and notifications"
    default_prompt_template = "prompts/email_summary.j2"
    execution_order = 75
    icon = "ListChecks"
    approval_key = "summary"
    has_view_page = True
    view_route = "/summaries"
    notification_event_type = "email_summary"
    notification_template = "notifications/email_summary.j2"

    async def execute(self, context: MailContext, ai_response: EmailSummaryResponse) -> ActionResult:
        actions: list[str] = [
            f"store_summary (urgency: {ai_response.urgency})",
        ]

        if ai_response.action_required:
            actions.append(f"action_required: {ai_response.action_description or 'unspecified'}")

        self.logger.info(
            "email_summary_generated",
            urgency=ai_response.urgency,
            action_required=ai_response.action_required,
            mail_uid=context.mail_uid,
        )

        return ActionResult(
            success=True,
            actions_taken=actions,
        )

    def get_approval_summary(self, ai_response: EmailSummaryResponse) -> str:
        summary_preview = ai_response.summary[:100]
        return f"Summary ({ai_response.urgency}): {summary_preview}..."

    @classmethod
    def get_notification_context(cls, result_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": result_data.get("summary", ""),
            "key_points": result_data.get("key_points", []),
            "urgency": result_data.get("urgency", "normal"),
            "action_required": result_data.get("action_required", False),
            "action_description": result_data.get("action_description", ""),
        }

    @classmethod
    async def load_notification_context(
        cls,
        db: Any,
        account_id: Any,
        mail_uid: str,
    ) -> dict[str, Any]:
        """Load email summary data from the database for notification context."""
        from sqlalchemy import select

        from app.models.mail import EmailSummary

        result = await db.execute(
            select(EmailSummary).where(
                EmailSummary.mail_account_id == account_id,
                EmailSummary.mail_uid == mail_uid,
            )
        )
        summary = result.scalar_one_or_none()
        if summary:
            return {
                "summary": summary.summary,
                "key_points": summary.key_points or [],
                "urgency": summary.urgency or "normal",
                "action_required": summary.action_required,
                "action_description": summary.action_description or "",
            }
        return {}

    @classmethod
    def get_notification_variables(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "summary",
                "var_type": "String",
                "description": "Short email summary text",
                "example": "Meeting confirmation for Q2 report discussion.",
            },
            {
                "name": "key_points",
                "var_type": "List",
                "description": "Key points extracted from the email",
                "example": '["Meeting at 2pm", "Bring Q2 report"]',
            },
            {
                "name": "urgency",
                "var_type": "String",
                "description": "Urgency level (low, normal, high, critical)",
                "example": "medium",
            },
            {
                "name": "action_required",
                "var_type": "Boolean",
                "description": "Whether user action is required",
                "example": "true",
            },
            {
                "name": "action_description",
                "var_type": "String",
                "description": "Description of required action",
                "example": "Prepare Q2 report for meeting",
            },
        ]

    @classmethod
    def get_preview_context(cls) -> dict[str, Any]:
        return {
            "summary": "Meeting confirmation for Q2 report discussion.",
            "key_points": ["Meeting at 2pm", "Bring Q2 report"],
            "urgency": "medium",
            "action_required": True,
            "action_description": "Prepare Q2 report for meeting",
        }
