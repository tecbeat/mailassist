"""Auto-reply draft AI plugin.

Generates draft replies for emails that warrant a response.
Runs last in the pipeline (execution_order=70) to benefit from
context gathered by prior plugins. Never auto-sends -- always creates
a draft in the IMAP Drafts folder.
"""

from pydantic import BaseModel, Field

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin


class AutoReplyResponse(BaseModel):
    """Validated LLM response for auto-reply draft generation."""

    should_reply: bool
    draft_body: str | None = Field(default=None, max_length=5000)
    tone: str | None = Field(default=None, max_length=50)
    reasoning: str = Field(max_length=300)


@register_plugin
class AutoReplyPlugin(AIFunctionPlugin[AutoReplyResponse]):
    """Generate draft replies for emails that warrant a response."""

    name = "auto_reply"
    display_name = "Auto-Reply Draft"
    description = "Drafts replies for emails that need a response, saved to IMAP Drafts folder"
    default_prompt_template = "prompts/auto_reply.j2"
    execution_order = 70
    icon = "Reply"
    approval_key = "auto_reply"
    has_view_page = True
    view_route = "/auto-reply"

    async def execute(self, context: MailContext, ai_response: AutoReplyResponse) -> ActionResult:
        if not ai_response.should_reply:
            self.logger.debug(
                "auto_reply_skipped",
                reason=ai_response.reasoning,
                mail_uid=context.mail_uid,
            )
            return self._no_action(f"no_reply_needed: {ai_response.reasoning}")

        if not ai_response.draft_body:
            return ActionResult(
                success=True,
                actions_taken=["reply_suggested_but_no_body"],
            )

        actions: list[str] = [
            f"create_draft_reply (tone: {ai_response.tone or 'neutral'})",
            "save_to_drafts",
            "track_ai_draft",
        ]

        self.logger.info(
            "auto_reply_drafted",
            tone=ai_response.tone,
            mail_uid=context.mail_uid,
        )

        # Auto-reply always requires approval by default
        return ActionResult(
            success=True,
            actions_taken=actions,
            requires_approval=True,
            approval_summary=self.get_approval_summary(ai_response),
        )

    def get_approval_summary(self, ai_response: AutoReplyResponse) -> str:
        return f"Draft reply ({ai_response.tone or 'neutral'}): {ai_response.reasoning}"
