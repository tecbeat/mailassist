"""Tests for plugin registry (test area 6).

Covers: decorator registration, discovery, ordering, duplicate names,
missing name attribute, get_plugin, get_all_plugins sorted by order,
plugin info serialization, and __contains__/__len__.
"""

from unittest.mock import patch, MagicMock

import pytest
from pydantic import BaseModel

from app.plugins.base import AIFunctionPlugin, ActionResult, MailContext
from app.plugins.registry import (
    PluginRegistry,
    register_plugin,
    _registered_plugins,
)


class DummyResponse(BaseModel):
    result: str


class _BaseDummyPlugin(AIFunctionPlugin):
    """Concrete plugin for testing (not registered by default)."""

    name = "_base_dummy"
    display_name = "Dummy"
    description = "Test plugin"
    default_prompt_template = "prompts/dummy.j2"
    execution_order = 50

    def get_response_schema(self) -> type[BaseModel]:
        return DummyResponse

    async def execute(self, context: MailContext, ai_response: BaseModel) -> ActionResult:
        return ActionResult(success=True, actions_taken=["dummy_action"])

    def get_approval_summary(self, ai_response: BaseModel) -> str:
        return "Dummy approval"


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset the module-level _registered_plugins between tests."""
    saved = dict(_registered_plugins)
    _registered_plugins.clear()
    yield
    _registered_plugins.clear()
    _registered_plugins.update(saved)


class TestRegisterDecorator:
    """Test the @register_plugin decorator."""

    def test_register_adds_to_dict(self):
        """Decorator adds the plugin class to _registered_plugins."""

        @register_plugin
        class PluginA(_BaseDummyPlugin):
            name = "test_plugin_a"

        assert "test_plugin_a" in _registered_plugins
        assert _registered_plugins["test_plugin_a"] is PluginA

    def test_register_duplicate_name_raises(self):
        """Registering two plugins with the same name raises ValueError."""

        @register_plugin
        class PluginB(_BaseDummyPlugin):
            name = "dup_name"

        with pytest.raises(ValueError, match="already registered"):

            @register_plugin
            class PluginC(_BaseDummyPlugin):
                name = "dup_name"

    def test_register_missing_name_raises(self):
        """Plugin without a name attribute raises ValueError."""
        with pytest.raises(ValueError, match="must define a 'name'"):

            @register_plugin
            class NoNamePlugin(_BaseDummyPlugin):
                name = ""

    def test_register_returns_class_unchanged(self):
        """Decorator returns the original class (no wrapping)."""

        @register_plugin
        class PluginD(_BaseDummyPlugin):
            name = "test_plugin_d"

        assert PluginD.name == "test_plugin_d"
        assert issubclass(PluginD, AIFunctionPlugin)


class TestPluginRegistry:
    """Test the PluginRegistry class methods."""

    def _make_registry(self, *plugins: type[AIFunctionPlugin]) -> PluginRegistry:
        """Register plugins and build a PluginRegistry from them."""
        for p in plugins:
            _registered_plugins[p.name] = p

        registry = PluginRegistry()
        # Manually instantiate without filesystem discovery
        for name, cls in _registered_plugins.items():
            registry._plugins[name] = cls()
        return registry

    def test_get_plugin_existing(self):
        class PluginE(_BaseDummyPlugin):
            name = "plugin_e"

        reg = self._make_registry(PluginE)
        assert reg.get_plugin("plugin_e") is not None
        assert reg.get_plugin("plugin_e").name == "plugin_e"

    def test_get_plugin_missing_returns_none(self):
        reg = PluginRegistry()
        assert reg.get_plugin("nonexistent") is None

    def test_get_all_plugins_sorted_by_order(self):
        """Plugins are returned sorted by execution_order."""

        class PluginLow(_BaseDummyPlugin):
            name = "low"
            execution_order = 10

        class PluginHigh(_BaseDummyPlugin):
            name = "high"
            execution_order = 70

        class PluginMid(_BaseDummyPlugin):
            name = "mid"
            execution_order = 40

        reg = self._make_registry(PluginHigh, PluginLow, PluginMid)
        ordered = reg.get_all_plugins()
        names = [p.name for p in ordered]
        assert names == ["low", "mid", "high"]

    def test_len_and_contains(self):
        class PluginF(_BaseDummyPlugin):
            name = "plugin_f"

        reg = self._make_registry(PluginF)
        assert len(reg) == 1
        assert "plugin_f" in reg
        assert "nonexistent" not in reg

    def test_get_plugin_info(self):
        """Plugin info returns list of dicts with expected keys."""

        class PluginG(_BaseDummyPlugin):
            name = "plugin_g"
            display_name = "Plugin G"
            execution_order = 25

        reg = self._make_registry(PluginG)
        info = reg.get_plugin_info()
        assert len(info) == 1
        assert info[0]["name"] == "plugin_g"
        assert info[0]["display_name"] == "Plugin G"
        assert info[0]["execution_order"] == 25
        assert "default_prompt_template" in info[0]

    def test_discover_plugins_imports_modules(self):
        """discover_plugins() imports plugin modules from the package directory."""
        reg = PluginRegistry()
        # Patch iter_modules to return nothing (avoid importing real plugins)
        with patch("app.plugins.registry.pkgutil.iter_modules", return_value=[]):
            reg.discover_plugins()

        # No modules to import, so no plugins discovered
        assert len(reg) == 0

    def test_discover_skips_base_and_registry(self):
        """discover_plugins() skips base.py, registry.py, and __init__.py."""
        module_infos = [
            MagicMock(name="base"),
            MagicMock(name="registry"),
            MagicMock(name="__init__"),
        ]
        # pkgutil.iter_modules returns ModuleInfo objects with .name attribute
        for mi in module_infos:
            mi.name = mi._mock_name

        reg = PluginRegistry()
        with patch("app.plugins.registry.pkgutil.iter_modules", return_value=module_infos):
            with patch("app.plugins.registry.importlib.import_module") as mock_import:
                reg.discover_plugins()

        # None of the skipped modules should be imported
        mock_import.assert_not_called()
