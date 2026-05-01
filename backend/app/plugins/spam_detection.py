"""Spam detection AI plugin.

Evaluates incoming emails for spam, phishing, and scam characteristics.
Runs first in the pipeline (execution_order=10). If spam is detected with
sufficient confidence, remaining plugins are skipped.
"""

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin


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
