"""Notifications pseudo-plugin.

Registered so the notifications feature appears in the plugin list (sidebar,
settings) alongside the AI plugins.  It does NOT participate in the AI
processing pipeline -- notifications are triggered by other subsystems.
"""

from pydantic import BaseModel

from app.plugins.base import ActionResult, AIFunctionPlugin, MailContext
from app.plugins.registry import register_plugin


class _NoOpResponse(BaseModel):
    """Placeholder response model -- never used at runtime."""

    pass


@register_plugin
class NotificationsPlugin(AIFunctionPlugin[_NoOpResponse]):
    """Pseudo-plugin for the notifications feature."""

    name = "notifications"
    display_name = "Notifications"
    description = "Push notification settings and delivery preferences"
    default_prompt_template = ""
    execution_order = 90
    supports_approval = False
    runs_in_pipeline = False
    icon = "Bell"
    approval_key = "notifications"
    has_view_page = True
    view_route = "/notifications"

    async def execute(self, context: MailContext, ai_response: _NoOpResponse) -> ActionResult:
        """Not called -- notifications are triggered by other subsystems."""
        raise NotImplementedError("NotificationsPlugin does not participate in the AI pipeline")

    def get_approval_summary(self, ai_response: _NoOpResponse) -> str:
        """Not called -- notifications are triggered by other subsystems."""
        raise NotImplementedError("NotificationsPlugin does not participate in the AI pipeline")
