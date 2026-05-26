"""Base class for LLM-callable tools.

Tools provide additional context-gathering capabilities to the LLM during
plugin execution. Each tool defines its name, description, parameters (as
JSON Schema), and an async execute method.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

import structlog

logger = structlog.get_logger()


@dataclass
class ToolResult:
    """Result returned by a tool execution.

    The LLM receives ``content`` as the tool call result.
    If ``is_error`` is True, the content describes the error.
    """

    content: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """Abstract base class for all LLM-callable tools.

    Subclasses must define:
        - name: Unique tool identifier (snake_case)
        - description: Human-readable description for the LLM
        - parameters: JSON Schema dict describing the tool's input parameters

    And implement:
        - execute(**kwargs) -> ToolResult
    """

    #: Unique identifier for this tool (snake_case, e.g. "get_plugin_results")
    name: str = ""

    #: Description shown to the LLM explaining when/how to use this tool
    description: str = ""

    #: JSON Schema for the tool's parameters.
    #: Must be a valid JSON Schema object with "type": "object" and "properties".
    #: Example:
    #:   {
    #:       "type": "object",
    #:       "properties": {
    #:           "query": {"type": "string", "description": "Search query"}
    #:       },
    #:       "required": ["query"]
    #:   }
    parameters: ClassVar[dict[str, Any]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate required class attributes on subclass definition."""
        super().__init_subclass__(**kwargs)
        if cls.name == "" and not getattr(cls, "__abstractmethods__", None):
            raise TypeError(f"Tool {cls.__name__} must define a 'name' class attribute")
        if cls.description == "" and not getattr(cls, "__abstractmethods__", None):
            raise TypeError(f"Tool {cls.__name__} must define a 'description' class attribute")

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with the given parameters.

        Implementations must NOT raise exceptions. Instead, return a ToolResult
        with is_error=True and a descriptive error message.

        Args:
            **kwargs: Parameters as defined in the tool's JSON Schema.

        Returns:
            ToolResult with the content to return to the LLM.
        """
        ...

    def to_litellm_tool(self) -> dict[str, Any]:
        """Convert this tool to the litellm/OpenAI tool format.

        Returns a dict compatible with the ``tools`` parameter of
        ``litellm.acompletion()``.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }

    async def safe_execute(self, **kwargs: Any) -> ToolResult:
        """Execute with error boundary — never raises."""
        try:
            return await self.execute(**kwargs)
        except Exception as e:
            logger.exception("tool_execution_error", tool=self.name, error=str(e))
            return ToolResult(
                content=f"Tool execution failed: {type(e).__name__}: {e}",
                is_error=True,
            )

    def __repr__(self) -> str:
        return f"<{type(self).__name__}(name={self.name!r})>"
