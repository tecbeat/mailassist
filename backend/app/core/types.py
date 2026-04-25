"""Shared domain types used across service and API layers.

Houses dataclasses and lightweight types that don't fit into Pydantic schemas
(API layer) or SQLAlchemy models (persistence layer).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionTestResult:
    """Unified result type for external service connectivity tests.

    Used by IMAP, CardDAV, CalDAV, and LLM connection test functions.
    Provides a consistent interface for the API layer to build responses from.
    """

    success: bool
    message: str
    details: dict[str, object] | None = None
