"""Labeling AI plugin.

Assigns IMAP labels/keywords to emails based on AI analysis.
Prefers existing labels, creates new ones only when necessary.
Tracks new labels in LabelChangeLog for re-processing.
"""

import re

from pydantic import BaseModel, Field

from app.plugins.base import AIFunctionPlugin, ActionResult, MailContext
from app.plugins.registry import register_plugin


class LabelingResponse(BaseModel):
    """Validated LLM response for labeling."""

    labels: list[str] = Field(min_length=1, max_length=10)


@register_plugin
class LabelingPlugin(AIFunctionPlugin[LabelingResponse]):
    """Auto-label emails using AI analysis."""

    name = "labeling"
    display_name = "Auto-Labeling"
    description = "Assigns IMAP labels/keywords based on email content, preferring existing labels"
    default_prompt_template = "prompts/labeling.j2"
    execution_order = 30
    icon = "Tags"
    approval_key = "labeling"
    has_view_page = True
    view_route = "/labeling"

    async def execute(self, context: MailContext, ai_response: LabelingResponse) -> ActionResult:
        existing_set = {label.lower() for label in context.existing_labels}
        new_labels = []
        reused_labels = []

        for raw_label in ai_response.labels:
            # Normalize: lowercase, spaces/underscores → hyphens, strip non-alnum
            label = raw_label.strip().lower()
            label = re.sub(r"[\s_]+", "-", label)
            label = re.sub(r"[^a-z0-9\-]", "", label)
            label = label.strip("-")
            if not label:
                continue

            if label.lower() in existing_set:
                reused_labels.append(label)
            else:
                new_labels.append(label)

        actions: list[str] = []

        if not reused_labels and not new_labels:
            return self._no_action("all_labels_empty_after_normalization")

        for label in reused_labels:
            actions.append(f"apply_label:{label}")

        for label in new_labels:
            actions.append(f"create_and_apply_label:{label}")

        if new_labels:
            # New labels are tracked for re-processing triggers
            actions.append(f"log_new_labels:{','.join(new_labels)}")
            self.logger.info(
                "new_labels_created",
                labels=new_labels,
                mail_uid=context.mail_uid,
            )

        return ActionResult(
            success=True,
            actions_taken=actions,
        )

    def get_approval_summary(self, ai_response: LabelingResponse) -> str:
        return f"Apply labels: {', '.join(ai_response.labels)}"
