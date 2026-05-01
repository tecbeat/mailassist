"""Pydantic schemas for AI Provider API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AIProviderCreate(BaseModel):
    """Request schema for creating an AI provider."""

    name: str | None = Field(default=None, max_length=100, description="Display name for this provider")
    provider_type: str = Field(description="Provider type: 'openai' or 'ollama'")
    api_key: str | None = Field(default=None, max_length=500, description="API key (write-only, OpenAI only)")
    base_url: str = Field(max_length=500, description="Provider API base URL")
    model_name: str = Field(max_length=100, description="Model identifier (e.g. 'gpt-4o', 'llama3.1')")
    max_tokens: int = Field(default=1024, ge=64, le=32768)
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    timeout_seconds: int | None = Field(
        default=None, ge=10, le=600, description="Per-provider LLM timeout in seconds (overrides global default)"
    )

    @field_validator("provider_type")
    @classmethod
    def validate_provider_type(cls, v: str) -> str:
        if v not in ("openai", "ollama"):
            raise ValueError("provider_type must be 'openai' or 'ollama'")
        return v


class AIProviderUpdate(BaseModel):
    """Request schema for updating an AI provider."""

    name: str | None = Field(default=None, max_length=100)
    provider_type: str | None = None
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)
    model_name: str | None = Field(default=None, max_length=100)
    max_tokens: int | None = Field(default=None, ge=64, le=32768)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    timeout_seconds: int | None = Field(default=None, ge=10, le=600, description="Per-provider LLM timeout in seconds")
    is_default: bool | None = Field(default=None, description="Set as the default provider")

    @field_validator("provider_type")
    @classmethod
    def validate_provider_type(cls, v: str | None) -> str | None:
        if v is not None and v not in ("openai", "ollama"):
            raise ValueError("provider_type must be 'openai' or 'ollama'")
        return v


class AIProviderResponse(BaseModel):
    """Response schema for an AI provider (API key never returned)."""

    id: UUID
    name: str | None
    provider_type: str
    base_url: str
    model_name: str
    is_default: bool
    max_tokens: int
    temperature: float
    timeout_seconds: int | None
    consecutive_errors: int
    last_error: str | None
    last_error_at: datetime | None
    last_success_at: datetime | None
    is_paused: bool
    manually_paused: bool
    paused_reason: str | None
    paused_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AIProviderTestResult(BaseModel):
    """Result of testing an LLM connection."""

    success: bool
    message: str
    model: str


class PluginInfo(BaseModel):
    """Metadata about an available AI function plugin."""

    name: str
    display_name: str
    description: str
    execution_order: int
    default_prompt_template: str
    icon: str = ""
    has_view_page: bool = False
    view_route: str | None = None
    has_config_page: bool = False
    config_route: str | None = None
    approval_key: str = ""
    supports_approval: bool = True
    runs_in_pipeline: bool = True


class PauseUpdate(BaseModel):
    """Request schema for updating the pause state."""

    paused: bool = Field(description="Whether the provider should be paused")
    pause_reason: str = Field(default="manual", max_length=200, description="Reason for pausing")
