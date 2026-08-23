"""Tool registry for automatic tool discovery and management.

Discovers and registers all BaseTool subclasses at startup.
Provides the global tool pool available to all plugins during inference.
"""

import importlib
import pkgutil
from pathlib import Path
from typing import Any

import structlog

from app.tools.base import BaseTool

logger = structlog.get_logger()

# Decorator-based registration
_registered_tools: dict[str, type[BaseTool]] = {}


def register_tool(cls: type[BaseTool]) -> type[BaseTool]:
    """Decorator to register a tool in the global pool.

    Usage:
        @register_tool
        class MyTool(BaseTool):
            name = "my_tool"
            ...
    """
    if not cls.name:
        raise ValueError(f"Tool {cls.__name__} must define a 'name' attribute")
    if cls.name in _registered_tools:
        raise ValueError(f"Tool name '{cls.name}' already registered by {_registered_tools[cls.name].__name__}")

    _registered_tools[cls.name] = cls
    logger.info("tool_registered", tool=cls.name)
    return cls


class ToolRegistry:
    """Manages the global pool of LLM-callable tools.

    Tools are discovered at startup via module import of tools/*.py.
    All tools are available to all plugins (global pool).
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def discover_tools(self) -> None:
        """Import all modules in the tools package to trigger registration."""
        tools_dir = Path(__file__).parent
        package_name = "app.tools"

        for module_info in pkgutil.iter_modules([str(tools_dir)]):
            if module_info.name in ("base", "registry", "__init__"):
                continue
            try:
                importlib.import_module(f"{package_name}.{module_info.name}")
                logger.debug("tool_module_imported", module=module_info.name)
            except Exception:
                logger.exception("tool_import_failed", module=module_info.name)

        # Instantiate registered tools
        for name, tool_cls in _registered_tools.items():
            self._tools[name] = tool_cls()

        logger.info(
            "tool_discovery_complete",
            total=len(self._tools),
            tools=list(self._tools.keys()),
        )

    def get_tool(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_all_tools(self) -> list[BaseTool]:
        """Get all registered tools."""
        return list(self._tools.values())

    def get_litellm_tools(self) -> list[dict[str, Any]]:
        """Get all tools in litellm/OpenAI format for the tools= parameter."""
        return [tool.to_litellm_tool() for tool in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


# Module-level singleton
_registry: ToolRegistry | None = None


def init_tool_registry() -> ToolRegistry:
    """Initialize the global tool registry and discover tools."""
    global _registry
    _registry = ToolRegistry()
    _registry.discover_tools()
    return _registry


def get_tool_registry() -> ToolRegistry:
    """Return the global tool registry instance."""
    if _registry is None:
        raise RuntimeError("Tool registry not initialized. Call init_tool_registry() first.")
    return _registry
