"""Spam detection AI plugin.

Evaluates incoming emails for spam, phishing, and scam characteristics.
Runs first in the pipeline (execution_order=10). If spam is detected with
sufficient confidence, remaining plugins are skipped.
"""

from typing import Any, ClassVar

import structlog
from pydantic import BaseModel, Field

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin

logger = structlog.get_logger()


class SpamDetectionResponse(BaseModel):
    """Validated LLM response for spam detection."""

    is_spam: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(max_length=500)


@register_plugin
class SpamDetectionPlugin(AIFunctionPlugin[SpamDetectionResponse]):
    """Detect spam, phishing, and scam emails."""

    name = "spam_detection"
    display_name = "Spam Detection"
    description = "Evaluates emails for spam, phishing, and scam characteristics"
    default_prompt_template = "prompts/spam_detection.j2"
    execution_order = 10
    icon = "ShieldAlert"
    approval_key = "spam"
    has_view_page = True
    view_route = "/spam"
    default_config: ClassVar[dict[str, Any]] = {"confidence_threshold": 0.8}
    notification_event_type = "spam_detected"
    notification_template = "notifications/spam_detected.j2"

    async def execute(self, context: MailContext, ai_response: SpamDetectionResponse) -> ActionResult:
        if not ai_response.is_spam:
            return self._no_action("spam_check_passed")

        threshold: float = self.get_config("confidence_threshold")
        if self._meets_threshold(ai_response.confidence, threshold):
            # High confidence: move to spam and skip remaining plugins
            return ActionResult(
                success=True,
                actions_taken=[
                    f"move_to_spam (confidence: {ai_response.confidence:.0%})",
                    "mark_as_read",
                ],
                skip_remaining_plugins=True,
            )

        # Below threshold: flag for review, continue pipeline
        return ActionResult(
            success=True,
            actions_taken=[f"flagged_for_review (confidence: {ai_response.confidence:.0%})"],
            requires_approval=True,
            approval_summary=self.get_approval_summary(ai_response),
        )

    def get_approval_summary(self, ai_response: SpamDetectionResponse) -> str:
        return f"Spam detected (confidence: {ai_response.confidence:.0%}): {ai_response.reason}"

    @classmethod
    async def load_notification_context(
        cls,
        db: Any,
        account_id: Any,
        mail_uid: str,
        *,
        mail_id: Any = None,
    ) -> dict[str, Any]:
        """Load spam detection data from the database for notification context."""
        from sqlalchemy import select

        from app.models.mail import SpamDetectionResult

        if mail_id is None:
            logger.warning(
                "load_notification_context called without mail_id",
                plugin="spam_detection",
                account_id=str(account_id),
                mail_uid=mail_uid,
            )
            return {}
        stmt = select(SpamDetectionResult).where(SpamDetectionResult.mail_id == mail_id)
        result = await db.execute(stmt)
        spam = result.scalar_one_or_none()
        if spam:
            return {
                "is_spam": spam.is_spam,
                "spam_confidence": spam.confidence,
                "spam_reason": spam.reason or "",
                "spam_source": spam.source,
            }
        return {}

    @classmethod
    def get_notification_variables(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "is_spam",
                "var_type": "Boolean",
                "description": "Whether the email was classified as spam",
                "example": "true",
            },
            {
                "name": "spam_confidence",
                "var_type": "Float",
                "description": "Confidence score between 0 and 1",
                "example": "0.92",
            },
            {
                "name": "spam_reason",
                "var_type": "String",
                "description": "Reason the email was flagged as spam",
                "example": "Contains phishing link and urgency language",
            },
            {
                "name": "spam_source",
                "var_type": "String",
                "description": "Detection source (ai or blocklist)",
                "example": "ai",
            },
        ]

    @classmethod
    def get_preview_context(cls) -> dict[str, Any]:
        return {
            "is_spam": True,
            "spam_confidence": 0.92,
            "spam_reason": "Contains phishing link and urgency language",
            "spam_source": "ai",
        }
