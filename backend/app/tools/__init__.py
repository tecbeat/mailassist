"""Tool system for LLM tool calling in the plugin pipeline.

Provides a global tool pool that plugins can leverage during inference
to gather additional context before making decisions.
"""

from app.tools.base import BaseTool, ToolResult
from app.tools.registry import get_tool_registry, init_tool_registry

__all__ = [
    "BaseTool",
    "ToolResult",
    "get_tool_registry",
    "init_tool_registry",
]
