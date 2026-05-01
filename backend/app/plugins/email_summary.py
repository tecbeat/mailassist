"""Email summary AI plugin.

Generates concise summaries of emails with urgency assessment.
Runs last in the pipeline (execution_order=75) to benefit from
context gathered by prior plugins. Summaries are stored in DB
and optionally forwarded via notification if filter rules match.
"""

from typing import Annotated

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
