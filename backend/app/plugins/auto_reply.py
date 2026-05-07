"""Auto-reply draft AI plugin.

Generates draft replies for emails that warrant a response.
Runs last in the pipeline (execution_order=70) to benefit from
context gathered by prior plugins. Never auto-sends -- always creates
a draft in the IMAP Drafts folder.
"""

from typing import Any

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
    notification_event_type = "reply_needed"
    notification_template = "notifications/reply_needed.j2"

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

    @classmethod
    def get_notification_context(cls, result_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "draft_body": result_data.get("draft_body", ""),
            "tone": result_data.get("tone", ""),
            "reply_reasoning": result_data.get("reasoning", ""),
            "action_taken": f"Draft reply created (tone: {result_data.get('tone', 'default')})",
        }

    @classmethod
    async def load_notification_context(
        cls,
        db: Any,
        account_id: Any,
        mail_uid: str,
    ) -> dict[str, Any]:
        """Load auto-reply data from the database for notification context."""
        from sqlalchemy import select

        from app.models.mail import AutoReplyRecord

        result = await db.execute(
            select(AutoReplyRecord).where(
                AutoReplyRecord.mail_account_id == account_id,
                AutoReplyRecord.mail_uid == mail_uid,
            )
        )
        reply = result.scalar_one_or_none()
        if reply:
            return {
                "draft_body": reply.draft_body,
                "tone": reply.tone or "",
                "reply_reasoning": reply.reasoning or "",
                "action_taken": f"Draft reply created (tone: {reply.tone or 'default'})",
            }
        return {}

    @classmethod
    def get_notification_variables(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "draft_body",
                "var_type": "String",
                "description": "The generated reply draft text",
                "example": "Thank you for your email...",
            },
            {
                "name": "tone",
                "var_type": "String",
                "description": "Tone of the generated reply",
                "example": "professional",
            },
            {
                "name": "reply_reasoning",
                "var_type": "String",
                "description": "AI reasoning for why a reply was drafted",
                "example": "Sender asked a direct question requiring a response",
            },
            {
                "name": "action_taken",
                "var_type": "String",
                "description": "Summary of the action performed",
                "example": "Draft reply created (tone: professional)",
            },
        ]

    @classmethod
    def get_preview_context(cls) -> dict[str, Any]:
        return {
            "draft_body": "Thank you for your email. I will review the documents and get back to you by Friday.",
            "tone": "professional",
            "reply_reasoning": "Sender asked a direct question requiring a response",
            "action_taken": "Draft reply created (tone: professional)",
        }
