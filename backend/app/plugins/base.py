"""AI function plugin base class and registry.

Defines the abstract base class that all AI plugins must implement,
and the registry for automatic plugin discovery.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import get_original_bases
from typing import Any, Generic, TypeVar, get_args

import structlog
from pydantic import BaseModel

logger = structlog.get_logger()


# Type variable bound to BaseModel for plugin response types
ResponseT = TypeVar("ResponseT", bound=BaseModel)


@dataclass
class MailContext:
    """Context object passed to AI plugins during execution.

    Contains all information about the mail being processed,
    the matched contact, and the mail account configuration.
    """

    user_id: str
    account_id: str
    mail_uid: str
    sender: str
    sender_name: str
    recipient: str
    subject: str
    body: str
    body_plain: str
    body_html: str
    headers: dict[str, str]
    date: str
    has_attachments: bool
    attachment_names: list[str]
    account_name: str
    account_email: str
    existing_labels: list[str]
    existing_folders: list[str]
    excluded_folders: list[str]
    folder_separator: str
    mail_size: int
    thread_length: int
    is_reply: bool
    is_forwarded: bool
    contact: dict[str, Any] | None = None
    user_contacts: list[dict[str, Any]] | None = None


@dataclass
class ActionResult:
    """Result of executing a plugin action."""

    success: bool
    actions_taken: list[str]
    error: str | None = None
    requires_approval: bool = False
    approval_summary: str | None = None
    skip_remaining_plugins: bool = False


@dataclass
class PipelineContext:
    """Mutable context shared across all plugins during a single mail processing run.

    Later plugins (e.g. email_summary at order 75) can inspect results
    produced by earlier plugins (e.g. spam_detection at order 10).

    **First-Write-Wins** for exclusive actions (``move_to``, ``mark_as_spam``):
    only the first plugin to claim an exclusive key wins; later plugins
    that attempt to set the same key are silently ignored.

    **Additive actions** (``labels``, ``flags``) can be appended by any plugin.

    Usage in a plugin's ``execute()``::

        # Read earlier results
        spam_result = pipeline.get_result("spam_detection")
        if spam_result and spam_result.get("is_spam"):
            ...

        # Store own result for later plugins
        pipeline.set_result("smart_folder", {"folder": "Work", "confidence": 0.95})

        # First-Write-Wins: claim exclusive action
        pipeline.set_exclusive("move_to", "Spam", "spam_detection")

        # Additive: append labels
        pipeline.add_additive("labels", "important")
    """

    #: Results keyed by plugin name.  Each plugin can call ``set_result``
    #: to store a dict of arbitrary data for downstream plugins.
    results: dict[str, dict[str, Any]] = field(default_factory=dict)

    #: Plugins that have been executed so far (list of plugin names).
    executed: list[str] = field(default_factory=list)

    #: Exclusive actions (First-Write-Wins).  Maps action key (e.g.
    #: ``"move_to"``, ``"mark_as_spam"``) to ``(value, plugin_name)``
    #: so we know who locked it.
    _exclusive_actions: dict[str, tuple[Any, str]] = field(default_factory=dict)

    #: Additive actions (append-only).  Maps action key (e.g. ``"labels"``,
    #: ``"flags"``) to a list of values contributed by any plugin.
    _additive_actions: dict[str, list[Any]] = field(default_factory=dict)

    # -- plugin result helpers ------------------------------------------------

    def set_result(self, plugin_name: str, data: dict[str, Any]) -> None:
        """Store a plugin's result data for downstream plugins."""
        self.results[plugin_name] = data

    def get_result(self, plugin_name: str) -> dict[str, Any] | None:
        """Retrieve a previously stored plugin result, or None."""
        return self.results.get(plugin_name)

    def has_run(self, plugin_name: str) -> bool:
        """Check whether a plugin has already executed in this pipeline run."""
        return plugin_name in self.executed

    # -- First-Write-Wins (exclusive actions) ---------------------------------

    def set_exclusive(self, key: str, value: Any, plugin_name: str) -> bool:
        """Claim an exclusive action slot.

        Returns ``True`` if the value was set (first writer), ``False`` if
        the key was already locked by another plugin.
        """
        if key in self._exclusive_actions:
            logger.debug(
                "exclusive_action_already_locked",
                key=key,
                locked_by=self._exclusive_actions[key][1],
                attempted_by=plugin_name,
            )
            return False
        self._exclusive_actions[key] = (value, plugin_name)
        return True

    def get_exclusive(self, key: str) -> Any | None:
        """Return the current value of an exclusive action, or ``None``."""
        entry = self._exclusive_actions.get(key)
        return entry[0] if entry else None

    def is_locked(self, key: str) -> bool:
        """Check whether an exclusive action key has already been claimed."""
        return key in self._exclusive_actions

    # -- Additive actions -----------------------------------------------------

    def add_additive(self, key: str, value: Any) -> None:
        """Append a value to an additive action list (e.g. labels, flags)."""
        self._additive_actions.setdefault(key, []).append(value)

    def get_additive(self, key: str) -> list[Any]:
        """Return the accumulated list for an additive action key."""
        return list(self._additive_actions.get(key, []))


class AIFunctionPlugin(ABC, Generic[ResponseT]):
    """Base class for all AI function plugins.

    Parameterised with the plugin's Pydantic response model so that
    ``execute()`` and ``get_approval_summary()`` receive the concrete
    type instead of a bare ``BaseModel``, eliminating ``type: ignore``
    casts in every plugin.

    New AI functions are added by:
    1. Create a new file in plugins/
    2. Subclass ``AIFunctionPlugin[MyResponseModel]``
    3. Implement the required methods
    4. Register via ``@register_plugin`` decorator

    No changes to existing code needed.
    """

    name: str
    display_name: str
    description: str
    default_prompt_template: str
    execution_order: int

    # UI metadata for sidebar / frontend rendering.
    # Subclasses set these to expose pages in the sidebar automatically.
    #
    # Convention:
    #   view_route  → ``/<name>``          (data-only page, e.g. "/contacts")
    #   config_route → ``/config/<name>``  (settings page, e.g. "/config/contacts")
    #
    # View and config pages are completely separate; a plugin may have
    # either, both, or neither.
    icon: str = ""
    has_view_page: bool = False
    view_route: str | None = None
    has_config_page: bool = False
    config_route: str | None = None

    # Key into the approval_modes settings object.  The frontend uses
    # this to hide sidebar entries for disabled plugins.  When empty,
    # the plugin is always shown (not gated by approval settings).
    approval_key: str = ""

    # Whether this plugin supports the "approval" mode in the UI.
    # When True the frontend shows Auto / Approval / Aus tabs.
    # When False only Auto / Aus are offered (no human review step).
    supports_approval: bool = True

    # Whether this plugin runs in the AI processing pipeline.
    # Plugins that don't run through the LLM (rules, contacts, notifications)
    # set this to False so the mail processor skips them.
    # This is orthogonal to supports_approval -- e.g. rules supports approval
    # but does not run in the AI pipeline.
    runs_in_pipeline: bool = True

    # Plugin-specific configuration defaults.
    # Subclasses override this dict to declare tuneable parameters
    # (e.g. confidence thresholds).  Values can be read at runtime via
    # ``self.get_config(key)`` which also checks Settings overrides.
    default_config: dict[str, Any] = {}

    # Resolved concrete response type (set by __init_subclass__)
    _response_type: type[BaseModel]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate required class attributes and resolve the response type."""
        super().__init_subclass__(**kwargs)
        # Skip validation on intermediate abstract classes
        if ABC in cls.__bases__:
            return
        required = ["name", "display_name", "description", "execution_order"]
        # AI pipeline plugins (default) also require a prompt template
        if getattr(cls, "runs_in_pipeline", True):
            required.append("default_prompt_template")
        missing = [attr for attr in required if not hasattr(cls, attr)]
        if missing:
            raise TypeError(
                f"Plugin {cls.__name__} must define class attributes: {', '.join(missing)}"
            )
        # Resolve Generic[ResponseT] → concrete type (only meaningful for AI plugins)
        for base in get_original_bases(cls):
            origin = getattr(base, "__origin__", None)
            if origin is AIFunctionPlugin:
                args = get_args(base)
                if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                    cls._response_type = args[0]
                    break

    @property
    def logger(self) -> structlog.stdlib.BoundLogger:
        """Return a logger bound to this plugin's name."""
        return structlog.get_logger().bind(plugin=self.name)

    def get_config(self, key: str) -> Any:
        """Return the value of a plugin configuration parameter.

        Looks up ``key`` in :attr:`default_config`.  Raises
        ``KeyError`` if the key is not declared in the plugin's
        ``default_config``.
        """
        if key not in self.default_config:
            raise KeyError(
                f"Plugin {self.name!r} has no config key {key!r}. "
                f"Declared keys: {list(self.default_config)}"
            )
        return self.default_config[key]

    @staticmethod
    def _no_action(label: str) -> ActionResult:
        """Return a success result with a single no-op label (e.g. 'spam_check_passed')."""
        return ActionResult(success=True, actions_taken=[label])

    @staticmethod
    def _meets_threshold(confidence: float, threshold: float) -> bool:
        """Check whether a confidence score meets or exceeds the given threshold.

        Centralises the confidence-gate pattern used by spam_detection,
        smart_folder, and similar plugins.
        """
        return confidence >= threshold

    def get_response_schema(self) -> type[ResponseT]:
        """Return the Pydantic model for validating LLM response.

        Default implementation returns the type argument from the generic
        base class (``AIFunctionPlugin[MyResponse]``).  Override only if
        the schema must be computed dynamically.
        """
        return self._response_type  # type: ignore[return-value]

    @abstractmethod
    async def execute(self, context: MailContext, ai_response: ResponseT) -> ActionResult:
        """Execute the action based on validated AI response."""

    @abstractmethod
    def get_approval_summary(self, ai_response: ResponseT) -> str:
        """Return a human-readable summary for the approval queue."""

    async def safe_execute(
        self,
        context: MailContext,
        ai_response: ResponseT,
        pipeline: PipelineContext | None = None,
    ) -> ActionResult:
        """Execute the plugin action with exception safety.

        Wraps ``execute()`` in a try/except so that individual plugin
        failures return a proper error result instead of propagating
        to the caller.

        When *pipeline* is provided, it is stored on ``self.pipeline``
        so that ``execute()`` implementations can inspect results from
        earlier plugins without changing the ``execute()`` signature.
        """
        self._pipeline = pipeline
        try:
            result = await self.execute(context, ai_response)
            # Store plugin result in pipeline context for downstream plugins
            if pipeline is not None:
                pipeline.set_result(
                    self.name,
                    ai_response.model_dump(mode="json"),
                )
                pipeline.executed.append(self.name)
            return result
        except Exception as exc:
            self.logger.exception(
                "plugin_execute_error",
                mail_uid=context.mail_uid,
                error=str(exc),
            )
            if pipeline is not None:
                pipeline.executed.append(self.name)
            return ActionResult(
                success=False,
                actions_taken=[],
                error=f"{self.name}: {exc}",
            )
        finally:
            self._pipeline = None

    @property
    def pipeline(self) -> PipelineContext | None:
        """Access the current pipeline context, if running inside a pipeline.

        Returns ``None`` when the plugin is executed outside a pipeline
        (e.g. from the approval executor).
        """
        return getattr(self, "_pipeline", None)
