"""Rules engine pseudo-plugin.

Registered so the rules engine appears in the plugin list (sidebar, settings)
alongside the AI plugins.  It does NOT participate in the AI processing
pipeline -- rule evaluation is handled separately in the mail processor.
"""

from pydantic import BaseModel

from app.plugins.base import AIFunctionPlugin, ActionResult, MailContext
from app.plugins.registry import register_plugin


class _NoOpResponse(BaseModel):
    """Placeholder response model -- never used at runtime."""

    pass


@register_plugin
class RulesPlugin(AIFunctionPlugin[_NoOpResponse]):
    """Pseudo-plugin for the rules engine."""

    name = "rules"
    display_name = "Rules Engine"
    description = "User-defined rules that filter, label, move, or flag emails based on conditions"
    default_prompt_template = ""
    execution_order = 5
    supports_approval = True
    runs_in_pipeline = False
    icon = "GitBranch"
    approval_key = "rules"
    has_view_page = True
    view_route = "/rules"

    async def execute(self, context: MailContext, ai_response: _NoOpResponse) -> ActionResult:
        """Not called -- rules are evaluated separately."""
        raise NotImplementedError("RulesPlugin does not participate in the AI pipeline")

    def get_approval_summary(self, ai_response: _NoOpResponse) -> str:
        """Not called -- rules are evaluated separately."""
        raise NotImplementedError("RulesPlugin does not participate in the AI pipeline")
