"""Pydantic schemas for Approval system API requests and responses."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ApprovalResponse(BaseModel):
    """Response schema for an approval queue entry."""

    id: UUID
    mail_account_id: UUID
    function_type: str
    mail_uid: str
    mail_subject: str
    mail_from: str
    proposed_action: dict[str, Any]
    edited_actions: dict[str, Any] | None = None
    ai_reasoning: str
    status: str
    created_at: datetime
    resolved_at: datetime | None
    expires_at: datetime

    model_config = {"from_attributes": True}


class ApprovalListResponse(BaseModel):
    """Paginated list of approvals."""

    items: list[ApprovalResponse]
    total: int
    page: int
    per_page: int
    pages: int


class ApprovalEditRequest(BaseModel):
    """Request body for editing proposed actions on an approval."""

    edited_actions: dict[str, Any] = Field(
        description="User-edited actions to override the AI-proposed actions.",
    )
