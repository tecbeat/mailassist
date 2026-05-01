"""Newsletter detection AI plugin.

Identifies newsletters, marketing emails, and bulk mailings.
Runs second in the pipeline (execution_order=20).

Detection-only: this plugin classifies the email and persists the
result in the ``detected_newsletters`` table (handled by the processor).
Folder organisation and labelling are left to the smart folder and
labeling plugins that run later in the pipeline.
"""

from pydantic import BaseModel, Field, field_validator

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin


class NewsletterDetectionResponse(BaseModel):
    """Validated LLM response for newsletter detection."""

    is_newsletter: bool
    newsletter_name: str | None = Field(default=None, max_length=200)
    has_unsubscribe: bool
    unsubscribe_url: str | None = None

    @field_validator("unsubscribe_url", mode="before")
    @classmethod
    def validate_unsubscribe_url(cls, v: str | None) -> str | None:
        """Ensure unsubscribe URL is a valid HTTP(S) URL, discard otherwise."""
        if v is None:
            return None
        v = v.strip()
        if v.startswith(("http://", "https://")):
            return v
        # Discard invalid URLs (javascript:, relative paths, garbage)
        return None


@register_plugin
class NewsletterDetectionPlugin(AIFunctionPlugin[NewsletterDetectionResponse]):
    """Detect newsletters, marketing emails, and bulk mailings."""

    name = "newsletter_detection"
    display_name = "Newsletter Detection"
    description = "Identifies newsletters and marketing emails for tracking and unsubscribe management"
    default_prompt_template = "prompts/newsletter_detection.j2"
    execution_order = 20
    icon = "Newspaper"
    approval_key = "newsletter"
    has_view_page = True
    view_route = "/newsletters"

    async def execute(self, context: MailContext, ai_response: NewsletterDetectionResponse) -> ActionResult:
        if not ai_response.is_newsletter:
            return self._no_action("newsletter_check_passed")

        actions: list[str] = []

        # Store unsubscribe URL if detected and valid
        if ai_response.has_unsubscribe and ai_response.unsubscribe_url:
            actions.append(f"store_unsubscribe_url:{ai_response.unsubscribe_url}")

        name = ai_response.newsletter_name or "Unknown"
        self.logger.info(
            "newsletter_detected",
            newsletter_name=name,
            mail_uid=context.mail_uid,
        )

        return ActionResult(
            success=True,
            actions_taken=actions,
        )

    def get_approval_summary(self, ai_response: NewsletterDetectionResponse) -> str:
        return f"Newsletter detected: {ai_response.newsletter_name or 'Unknown'}"
