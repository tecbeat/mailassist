"""Plugin registry for automatic AI function plugin discovery.

Discovers and registers all AIFunctionPlugin subclasses at startup.
Plugins are imported from the plugins/ directory and sorted by execution_order.
"""

import importlib
import pkgutil
from pathlib import Path
from typing import Any

import structlog

from app.plugins.base import AIFunctionPlugin

logger = structlog.get_logger()

# Decorator-based registration
_registered_plugins: dict[str, type[AIFunctionPlugin]] = {}


def register_plugin(cls: type[AIFunctionPlugin]) -> type[AIFunctionPlugin]:
    """Decorator to register an AI function plugin.

    Usage:
        @register_plugin
        class MyPlugin(AIFunctionPlugin):
            name = "my_plugin"
            ...
    """
    if not hasattr(cls, "name") or not cls.name:
        raise ValueError(f"Plugin {cls.__name__} must define a 'name' attribute")
    if cls.name in _registered_plugins:
        raise ValueError(f"Plugin name '{cls.name}' already registered by {_registered_plugins[cls.name].__name__}")

    _registered_plugins[cls.name] = cls
    logger.info("plugin_registered", plugin=cls.name, order=cls.execution_order)
    return cls


class PluginRegistry:
    """Auto-discovers and manages all AIFunctionPlugin subclasses.

    Plugins are discovered at startup via module import of plugins/*.py.
    Provides iteration in execution_order for the processing pipeline.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, AIFunctionPlugin] = {}

    def discover_plugins(self) -> None:
        """Import all modules in the plugins package to trigger registration."""
        plugins_dir = Path(__file__).parent
        package_name = "app.plugins"

        for module_info in pkgutil.iter_modules([str(plugins_dir)]):
            if module_info.name in ("base", "registry", "__init__"):
                continue
            try:
                importlib.import_module(f"{package_name}.{module_info.name}")
                logger.debug("plugin_module_imported", module=module_info.name)
            except Exception:
                logger.exception("plugin_import_failed", module=module_info.name)

        # Instantiate registered plugins
        for name, plugin_cls in _registered_plugins.items():
            self._plugins[name] = plugin_cls()

        logger.info(
            "plugin_discovery_complete",
            total=len(self._plugins),
            plugins=list(self._plugins.keys()),
        )

    def get_plugin(self, name: str) -> AIFunctionPlugin | None:
        """Get a plugin by name."""
        return self._plugins.get(name)

    def get_all_plugins(self) -> list[AIFunctionPlugin]:
        """Get all plugins sorted by execution_order."""
        return sorted(self._plugins.values(), key=lambda p: p.execution_order)

    def get_plugin_info(self) -> list[dict[str, Any]]:
        """Get plugin metadata for API/UI display."""
        return [
            {
                "name": p.name,
                "display_name": p.display_name,
                "description": p.description,
                "execution_order": p.execution_order,
                "default_prompt_template": p.default_prompt_template,
                "icon": p.icon,
                "has_view_page": p.has_view_page,
                "view_route": p.view_route,
                "has_config_page": p.has_config_page,
                "config_route": p.config_route,
                "approval_key": p.approval_key,
                "supports_approval": p.supports_approval,
                "runs_in_pipeline": p.runs_in_pipeline,
            }
            for p in self.get_all_plugins()
        ]

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: str) -> bool:
        return name in self._plugins


# Module-level singleton
_registry: PluginRegistry | None = None


def init_plugin_registry() -> PluginRegistry:
    """Initialize the global plugin registry and discover plugins."""
    global _registry
    _registry = PluginRegistry()
    _registry.discover_plugins()
    return _registry


def get_plugin_registry() -> PluginRegistry:
    """Return the global plugin registry instance."""
    if _registry is None:
        raise RuntimeError("Plugin registry not initialized. Call init_plugin_registry() first.")
    return _registry
