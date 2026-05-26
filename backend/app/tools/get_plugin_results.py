"""Tool: get_plugin_results — retrieve results from previously executed plugins."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from app.tools.base import BaseTool, ToolResult
from app.tools.registry import register_tool


@register_tool
class GetPluginResultsTool(BaseTool):
    """Returns results from plugins that already ran in the current pipeline."""

    name = "get_plugin_results"
    description = (
        "Retrieve results from plugins that already executed in the current mail "
        "processing pipeline. Returns structured data from prior plugin analyses. "
        "Use this to make context-aware decisions based on what other plugins determined."
    )
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "plugin_name": {
                "type": "string",
                "description": (
                    "Optional: filter to a specific plugin's result "
                    "(e.g. 'spam_detection', 'newsletter_detection', 'labeling'). "
                    "Omit to get all available results."
                ),
            },
        },
        "required": [],
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        """Return pipeline results from previously executed plugins."""
        if self._pipeline is None:
            return ToolResult(content="No pipeline context available.", is_error=True)

        plugin_name: str | None = kwargs.get("plugin_name")

        if plugin_name:
            result = self._pipeline.get_result(plugin_name)
            if result is None:
                available = self._pipeline.executed
                return ToolResult(
                    content=json.dumps({
                        "error": f"No result from plugin '{plugin_name}'.",
                        "executed_plugins": available,
                    }),
                )
            return ToolResult(content=json.dumps({plugin_name: result}))

        # Return all results
        if not self._pipeline.results:
            return ToolResult(
                content=json.dumps({
                    "message": "No plugins have produced results yet.",
                    "executed_plugins": self._pipeline.executed,
                }),
            )

        return ToolResult(content=json.dumps(self._pipeline.results, default=str))
