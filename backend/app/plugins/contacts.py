"""Contacts AI pipeline plugin.

Analyzes incoming emails and assigns them to existing contacts using
AI-powered matching that goes beyond simple email-address matching.
Uses sender info, content context, name variations, signatures, and
company information to find the best contact match — or suggest
creating a new contact.

Runs late in the pipeline (execution_order=80) so that other plugins
have already enriched the context.
"""

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin


class ContactAssignmentResponse(BaseModel):
    """Validated LLM response for contact assignment."""

    contact_id: str | None = Field(
        default=None,
        description="UUID of the matched existing contact, or null if suggesting a new contact",
    )
    contact_name: str = Field(
        max_length=255,
        description="Display name of the matched or suggested contact",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=500)
    is_new_contact_suggestion: bool = Field(
        default=False,
        description="True if the AI suggests creating a new contact instead of matching an existing one",
    )


@register_plugin
class ContactsPlugin(AIFunctionPlugin[ContactAssignmentResponse]):
    """AI-powered contact assignment for incoming emails."""

    name = "contacts"
    display_name = "Contacts"
    description = "AI-powered contact matching and assignment for incoming emails"
    default_prompt_template = "prompts/contacts.j2"
    execution_order = 80
    supports_approval = True
    runs_in_pipeline = True
    icon = "Contact"
    approval_key = "contacts"
    has_view_page = True
    view_route = "/contacts"
    notification_event_type = "contact_assigned"
    notification_template = "notifications/contact_assigned.j2"
    default_config: ClassVar[dict[str, Any]] = {"confidence_threshold": 0.85}

    async def execute(self, context: MailContext, ai_response: ContactAssignmentResponse) -> ActionResult:
        # No match — AI explicitly said there's no matching contact
        if not ai_response.contact_id and not ai_response.is_new_contact_suggestion:
            return self._no_action("no_contact_match")

        # If no contacts exist and AI didn't suggest a new one, skip
        if not ai_response.contact_name:
            return self._no_action("no_contact_assignment")

        # If the deterministic pre-pipeline match already found the same
        # contact, just persist quietly (no approval needed)
        if context.contact and ai_response.contact_id and context.contact.get("id") == ai_response.contact_id:
            return ActionResult(
                success=True,
                actions_taken=[f"confirm_contact:{ai_response.contact_id}"],
            )

        # Below confidence threshold or new contact suggestion: require approval
        threshold: float = self.get_config("confidence_threshold")
        if ai_response.is_new_contact_suggestion or not self._meets_threshold(ai_response.confidence, threshold):
            return ActionResult(
                success=True,
                actions_taken=[],
                requires_approval=True,
                approval_summary=self.get_approval_summary(ai_response),
            )

        # High-confidence match to an existing contact
        action = f"assign_contact:{ai_response.contact_id}" if ai_response.contact_id else "suggest_new_contact"
        return ActionResult(
            success=True,
            actions_taken=[action],
        )

    def get_approval_summary(self, ai_response: ContactAssignmentResponse) -> str:
        if ai_response.is_new_contact_suggestion:
            return (
                f"Suggest new contact '{ai_response.contact_name}' "
                f"(confidence: {ai_response.confidence:.0%}): {ai_response.reasoning}"
            )
        return (
            f"Assign to '{ai_response.contact_name}' "
            f"(confidence: {ai_response.confidence:.0%}): {ai_response.reasoning}"
        )

    @classmethod
    def get_notification_context(cls, result_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "contact_name": result_data.get("contact_name", ""),
            "confidence": result_data.get("confidence", 0.0),
            "is_new_contact_suggestion": result_data.get("is_new_contact_suggestion", False),
            "reasoning": result_data.get("reasoning", ""),
        }

    @classmethod
    async def load_notification_context(
        cls,
        db: Any,
        account_id: Any,
        mail_uid: str,
        *,
        mail_id: Any = None,
    ) -> dict[str, Any]:
        """Load contact assignment data from the database for notification context."""
        from sqlalchemy import select

        from app.models.mail import ContactAssignment

        if mail_id is not None:
            stmt = select(ContactAssignment).where(ContactAssignment.mail_id == mail_id)
        else:
            stmt = select(ContactAssignment).where(
                ContactAssignment.mail_account_id == account_id,
                ContactAssignment.mail_uid == mail_uid,
            )
        result = await db.execute(stmt)
        assignment = result.scalar_one_or_none()
        if assignment:
            return {
                "contact_name": assignment.contact_name,
                "confidence": assignment.confidence,
                "is_new_contact_suggestion": assignment.is_new_contact_suggestion,
                "reasoning": assignment.reasoning,
            }
        return {}

    @classmethod
    def get_notification_variables(cls) -> list[dict[str, Any]]:
        return [
            {
                "name": "contact_name",
                "var_type": "String",
                "description": "Name of the assigned contact",
                "example": "Max Müller",
            },
            {
                "name": "confidence",
                "var_type": "Float",
                "description": "Confidence score of the contact assignment",
                "example": "0.92",
            },
            {
                "name": "is_new_contact_suggestion",
                "var_type": "Boolean",
                "description": "Whether this is a new contact suggestion",
                "example": "true",
            },
            {
                "name": "reasoning",
                "var_type": "String",
                "description": "AI reasoning for the contact assignment",
                "example": "Email address matches known contact",
            },
        ]

    @classmethod
    def get_preview_context(cls) -> dict[str, Any]:
        return {
            "contact_name": "Max Müller",
            "confidence": 0.92,
            "is_new_contact_suggestion": False,
            "reasoning": "Email address matches known contact",
        }
