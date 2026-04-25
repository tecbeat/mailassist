"""Jinja2 SandboxedEnvironment for prompt and notification templates.

Provides safe template rendering with custom filters and variable injection.
User-provided templates are sandboxed to prevent file access, imports, or
access to private attributes.
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, ChoiceLoader, DictLoader, FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

# Path to default templates shipped with the application
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

# Patterns that may indicate prompt injection attempts
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?above\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"^system\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^assistant\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^user\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"###\s*(SYSTEM|ASSISTANT|USER)\s*###", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"new\s+instructions?\s*:", re.IGNORECASE),
    re.compile(r"forget\s+(everything|all)", re.IGNORECASE),
]


def _sanitize_for_llm(text: str) -> str:
    """Strip sequences that look like prompt injection attempts.

    Custom Jinja2 filter applied to untrusted email content before sending to LLM.
    """
    if not text:
        return text

    result = text
    for pattern in _INJECTION_PATTERNS:
        result = pattern.sub("[FILTERED]", result)

    # Remove markdown code fences that could break prompt structure
    result = result.replace("```", "")

    # Escape delimiter characters used in prompt templates
    result = result.replace("=== ", "--- ")

    return result


def _sanitize_html(html: str) -> str:
    """Sanitize HTML content, stripping scripts, styles, and tracking pixels."""
    import nh3

    return nh3.clean(html)


def _datetimeformat(value: datetime | str, fmt: str = "%Y-%m-%d %H:%M %Z") -> str:
    """Format a datetime using strftime."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return str(value)
    return value.strftime(fmt)


def _truncate(text: str, length: int = 2000, end: str = "...") -> str:
    """Truncate text to a maximum length."""
    if len(text) <= length:
        return text
    return text[: length - len(end)] + end


class TemplateEngine:
    """Manages Jinja2 template rendering with sandboxing and custom filters.

    Templates can come from:
    1. Default files on disk (app/templates/)
    2. User-customized templates stored in the database (loaded via DictLoader)
    """

    def __init__(self) -> None:
        # Start with only the filesystem loader for defaults
        self._user_templates: dict[str, str] = {}
        self._env = self._create_env()

    def _create_env(self) -> SandboxedEnvironment:
        """Create a sandboxed Jinja2 environment with custom filters."""
        loaders: list[BaseLoader] = []
        if self._user_templates:
            loaders.append(DictLoader(self._user_templates))
        if _TEMPLATES_DIR.exists():
            loaders.append(FileSystemLoader(str(_TEMPLATES_DIR)))

        env = SandboxedEnvironment(
            loader=ChoiceLoader(loaders) if loaders else None,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

        # Register custom filters
        env.filters["sanitize_for_llm"] = _sanitize_for_llm
        env.filters["sanitize_html"] = _sanitize_html
        env.filters["datetimeformat"] = _datetimeformat
        env.filters["truncate_text"] = _truncate
        # Note: Jinja2's builtin ``truncate`` is preserved (word-boundary aware)

        return env

    def set_user_template(self, name: str, source: str) -> None:
        """Register or update a user-customized template."""
        self._user_templates[name] = source
        # Recreate environment to pick up new template
        self._env = self._create_env()

    def render(self, template_name: str, context: dict[str, Any]) -> str:
        """Render a named template with the given context variables.

        Looks up user-customized template first, falls back to default.

        Raises:
            jinja2.TemplateNotFound: If neither custom nor default template exists.
            jinja2.TemplateSyntaxError: If the template has syntax errors.
        """
        template = self._env.get_template(template_name)
        return template.render(**context)

    def render_string(self, source: str, context: dict[str, Any]) -> str:
        """Render a template from a raw string (for preview/test).

        Args:
            source: Jinja2 template string.
            context: Template variables.

        Raises:
            jinja2.TemplateSyntaxError: If the template string has syntax errors.
        """
        template = self._env.from_string(source)
        return template.render(**context)

    def validate_template(self, source: str) -> list[str]:
        """Validate a template string and return a list of errors (empty if valid)."""
        errors: list[str] = []
        try:
            self._env.parse(source)
        except Exception as e:
            errors.append(str(e))
        return errors


# Module-level singleton
_template_engine: TemplateEngine | None = None


def init_template_engine() -> TemplateEngine:
    """Initialize and return the global template engine."""
    global _template_engine
    _template_engine = TemplateEngine()
    return _template_engine


def get_template_engine() -> TemplateEngine:
    """Return the global template engine instance."""
    if _template_engine is None:
        raise RuntimeError("Template engine not initialized. Call init_template_engine() first.")
    return _template_engine
