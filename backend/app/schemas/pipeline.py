"""Pydantic schemas for pipeline testing.

Defines request/response models for the dry-run pipeline test endpoint.
"""

from typing import Any

from pydantic import BaseModel, Field


class PipelineTestRequest(BaseModel):
    """Input for testing the AI processing pipeline with sample email data."""

    sender: str = Field(
        default="test@example.com",
        max_length=320,
        description="Sender email address",
    )
    sender_name: str = Field(
        default="Test Sender",
        max_length=200,
        description="Sender display name",
    )
    recipient: str = Field(
        default="me@example.com",
        max_length=320,
        description="Recipient email address",
    )
    subject: str = Field(
        default="Test Email Subject",
        max_length=998,
        description="Email subject",
    )
    body: str = Field(
        default="This is a test email body for pipeline testing.",
        max_length=50000,
        description="Email body (plain text)",
    )
    date: str = Field(
        default="",
        description="Email date (ISO format). Defaults to current time.",
    )
    has_attachments: bool = Field(
        default=False,
        description="Whether the email has attachments",
    )
    is_reply: bool = Field(
        default=False,
        description="Whether this is a reply",
    )
    is_forwarded: bool = Field(
        default=False,
        description="Whether this is a forwarded email",
    )


class PluginTestResult(BaseModel):
    """Result of a single plugin execution during testing."""

    plugin_name: str
    display_name: str
    success: bool
    actions: list[str] = []
    ai_response: dict[str, Any] | None = None
    tokens_used: int = 0
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None


class PipelineTestResponse(BaseModel):
    """Response from the pipeline test endpoint."""

    success: bool
    plugins_executed: int = 0
    total_tokens: int = 0
    results: list[PluginTestResult] = []
    error: str | None = None
