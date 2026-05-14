"""Base schema for plugin response models that reference a TrackedEmail."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator


class PluginResponseBase(BaseModel):
    """Mixin that extracts mail metadata from the ``tracked_email`` relationship.

    All plugin result tables (EmailSummary, AssignedFolder, AppliedLabel, …)
    store a ``mail_id`` FK to ``tracked_emails`` and expose a
    ``tracked_email`` ORM relationship.  The frontend expects each plugin
    response to carry ``mail_uid``, ``mail_account_id``, ``mail_subject``,
    ``mail_from``, and ``mail_date`` — which all live on ``TrackedEmail``,
    not on the plugin table itself.

    Subclasses must set ``model_config = {"from_attributes": True}``.
    """

    mail_uid: str | None = None
    mail_account_id: UUID | None = None
    mail_subject: str | None = None
    mail_from: str | None = None
    mail_date: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _extract_tracked_email_fields(cls, data: Any) -> Any:
        """Pull mail metadata from the tracked_email relationship."""
        # When validating from ORM attributes (not a dict), read the
        # relationship directly.
        if isinstance(data, dict):
            return data

        # ORM object — access the eager-loaded relationship.
        tracked = getattr(data, "tracked_email", None)
        if tracked is None:
            return data

        # Inject values so Pydantic finds them during attribute access.
        # We wrap in a thin namespace that delegates attribute reads to the
        # original ORM object but adds/overrides the four fields.
        return _OrmProxy(data, tracked)


class _OrmProxy:
    """Proxy that overlays tracked-email fields onto a plugin ORM object."""

    __slots__ = ("_obj", "_overrides")

    def __init__(self, obj: Any, tracked: Any) -> None:
        self._obj = obj
        # Only override fields that do not already exist on the ORM object
        # (e.g. Approval already has mail_subject/mail_from columns).
        overrides: dict[str, Any] = {}
        mapping: dict[str, str] = {
            "mail_uid": "mail_uid",
            "mail_account_id": "mail_account_id",
            "mail_subject": "subject",
            "mail_from": "sender",
            "mail_date": "received_at",
        }
        for field, tracked_attr in mapping.items():
            if not hasattr(obj, field):
                overrides[field] = getattr(tracked, tracked_attr, None)
        self._overrides = overrides

    def __getattr__(self, name: str) -> Any:
        if name in ("_obj", "_overrides"):
            return object.__getattribute__(self, name)
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, "_obj"), name)
