"""Pydantic schemas for Prompt management API requests and responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PromptResponse(BaseModel):
    """Response schema for a prompt template."""

    id: UUID | None = None
    function_type: str
    system_prompt: str
    user_prompt: str | None
    is_custom: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class PromptUpdate(BaseModel):
    """Request schema for updating a prompt template."""

    system_prompt: str = Field(min_length=1, max_length=50000, description="Jinja2 system prompt template")
    user_prompt: str | None = Field(default=None, max_length=50000, description="Jinja2 user prompt template")


class PromptPreviewRequest(BaseModel):
    """Request schema for previewing a rendered prompt with sample data."""

    system_prompt: str = Field(min_length=1, max_length=50000)
    user_prompt: str | None = Field(default=None, max_length=50000)


class PromptPreviewResponse(BaseModel):
    """Response with the rendered prompt and any validation errors."""

    rendered_system: str
    rendered_user: str | None
    errors: list[str]


class TemplateVariable(BaseModel):
    """Metadata about an available template variable."""

    name: str
    var_type: str
    description: str
    example: str
