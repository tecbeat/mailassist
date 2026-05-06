"""Newsletter detection AI plugin.

Identifies newsletters, marketing emails, and bulk mailings.
Runs second in the pipeline (execution_order=20).

Detection-only: this plugin classifies the email and persists the
result in the ``detected_newsletters`` table (handled by the processor).
Folder organisation and labelling are left to the smart folder and
labeling plugins that run later in the pipeline.
"""

from typing import Any

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
    notification_event_type = "newsletter_detected"
    notification_template = "notifications/newsletter_detected.j2"

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

    @classmethod
    async def load_notification_context(
        cls,
        db: Any,
        account_id: Any,
        mail_uid: str,
    ) -> dict[str, Any]:
        """Load newsletter detection data from the database for notification context."""
        from sqlalchemy import select

        from app.models.mail import DetectedNewsletter

        result = await db.execute(
            select(DetectedNewsletter).where(
                DetectedNewsletter.mail_account_id == account_id,
                DetectedNewsletter.mail_uid == mail_uid,
            )
        )
        newsletter = result.scalar_one_or_none()
        if newsletter:
            return {
                "newsletter_name": newsletter.newsletter_name,
                "newsletter_sender": newsletter.sender_address,
                "has_unsubscribe": newsletter.has_unsubscribe,
                "unsubscribe_url": newsletter.unsubscribe_url or "",
            }
        return {}

    @classmethod
    def get_notification_variables(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "newsletter_name",
                "var_type": "String",
                "description": "Name of the detected newsletter",
                "example": "The Weekly Digest",
            },
            {
                "name": "newsletter_sender",
                "var_type": "String",
                "description": "Sender email address of the newsletter",
                "example": "news@example.com",
            },
            {
                "name": "has_unsubscribe",
                "var_type": "Boolean",
                "description": "Whether an unsubscribe link was found",
                "example": "true",
            },
            {
                "name": "unsubscribe_url",
                "var_type": "String",
                "description": "Unsubscribe URL (empty string if not found)",
                "example": "https://example.com/unsubscribe?token=abc",
            },
        ]

    @classmethod
    def get_preview_context(cls) -> dict[str, Any]:
        return {
            "newsletter_name": "The Weekly Digest",
            "newsletter_sender": "news@example.com",
            "has_unsubscribe": True,
            "unsubscribe_url": "https://example.com/unsubscribe?token=abc",
        }
