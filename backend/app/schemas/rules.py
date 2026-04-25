"""Pydantic schemas for the Rule system.

Defines condition trees (nested AND/OR), action definitions, and
CRUD / NL-to-rule / test request/response models.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# -- Enums -----------------------------------------------------------------

MAX_NESTING_DEPTH = 5
MAX_RULES_PER_GROUP = 20


class ConditionOperator(str, Enum):
    """Logical grouping operator for condition groups."""

    AND = "AND"
    OR = "OR"


class FieldOperator(str, Enum):
    """Comparison operators for individual condition rules."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    MATCHES_REGEX = "matches_regex"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"


class ActionType(str, Enum):
    """Available rule action types."""

    MOVE = "move"
    COPY = "copy"
    LABEL = "label"
    REMOVE_LABEL = "remove_label"
    MARK_READ = "mark_read"
    MARK_UNREAD = "mark_unread"
    FLAG = "flag"
    DELETE = "delete"
    NOTIFY = "notify"
    CREATE_DRAFT = "create_draft"
    CREATE_CALENDAR_EVENT = "create_calendar_event"


# -- Condition schemas ------------------------------------------------------


class ConditionRule(BaseModel):
    """A single field comparison rule within a condition group."""

    field: str = Field(
        description=(
            "Mail field to evaluate. Supported: from, to, cc, subject, body, "
            "has_attachment, attachment_name, date, size, header:<name>, "
            "contact_name, contact_org, is_reply, is_forwarded"
        ),
    )
    op: FieldOperator
    value: Any = Field(
        default=None,
        description="Comparison value. Not required for is_empty / is_not_empty.",
    )


class ConditionGroup(BaseModel):
    """Nested AND/OR condition group.

    Contains either leaf-level ``ConditionRule`` items or nested ``ConditionGroup``
    items (but not both at the same time in a single list entry -- the discriminator
    is the presence of the ``operator`` key).
    """

    operator: ConditionOperator
    rules: list[ConditionRule | ConditionGroup] = Field(
        min_length=1,
        max_length=MAX_RULES_PER_GROUP,
    )

    @model_validator(mode="after")
    def _validate_nesting_depth(self) -> ConditionGroup:
        _check_depth(self, current_depth=1)
        return self


def _check_depth(group: ConditionGroup, current_depth: int) -> None:
    """Recursively verify that nesting does not exceed MAX_NESTING_DEPTH."""
    if current_depth > MAX_NESTING_DEPTH:
        raise ValueError(
            f"Condition nesting exceeds maximum depth of {MAX_NESTING_DEPTH}"
        )
    for rule in group.rules:
        if isinstance(rule, ConditionGroup):
            _check_depth(rule, current_depth + 1)


# -- Action schemas ---------------------------------------------------------


class RuleAction(BaseModel):
    """A single action to execute when a rule matches."""

    type: ActionType
    target: str | None = Field(
        default=None,
        description="Target folder for move/copy, Jinja2 template for notify.",
    )
    value: str | None = Field(
        default=None,
        description="Label value for label/remove_label.",
    )

    @model_validator(mode="after")
    def _validate_params(self) -> RuleAction:
        """Ensure required parameters are present for actions that need them."""
        if self.type in (ActionType.MOVE, ActionType.COPY) and not self.target:
            raise ValueError(f"Action '{self.type.value}' requires a 'target' folder")
        if self.type in (ActionType.LABEL, ActionType.REMOVE_LABEL) and not self.value:
            raise ValueError(f"Action '{self.type.value}' requires a 'value'")
        if self.type == ActionType.NOTIFY and not self.target:
            raise ValueError("Action 'notify' requires a 'target' (Jinja2 template)")
        return self


# -- CRUD schemas -----------------------------------------------------------


class RuleCreate(BaseModel):
    """Request body for creating a new rule."""

    mail_account_id: UUID | None = Field(
        default=None,
        description="Scope to a specific account. null = all accounts.",
    )
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: int = Field(ge=0, description="Lower number = evaluated first")
    is_active: bool = True
    conditions: ConditionGroup
    actions: list[RuleAction] = Field(min_length=1)
    stop_processing: bool = False


class RuleUpdate(BaseModel):
    """Request body for updating an existing rule. All fields optional."""

    mail_account_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    priority: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    conditions: ConditionGroup | None = None
    actions: list[RuleAction] | None = Field(default=None, min_length=1)
    stop_processing: bool | None = None


class RuleResponse(BaseModel):
    """Response schema for a rule."""

    id: UUID
    user_id: UUID
    mail_account_id: UUID | None
    name: str
    description: str | None
    priority: int
    is_active: bool
    conditions: dict
    actions: list[dict]
    stop_processing: bool
    match_count: int
    last_matched_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RuleListResponse(BaseModel):
    """Paginated list of rules."""

    items: list[RuleResponse]
    total: int
    page: int = 1
    per_page: int = 0
    pages: int = 1


class ReorderItem(BaseModel):
    """A single rule ID + new priority for bulk reorder."""

    id: UUID
    priority: int = Field(ge=0)


class ReorderRequest(BaseModel):
    """Bulk reorder request."""

    rules: list[ReorderItem] = Field(min_length=1, max_length=200)


# -- NL-to-rule schemas -----------------------------------------------------


class NLRuleRequest(BaseModel):
    """Request for natural-language to structured rule translation."""

    description: str = Field(
        min_length=5,
        max_length=2000,
        description="Natural language rule description.",
    )
    mail_account_id: UUID | None = Field(
        default=None,
        description="Optional account scope for context.",
    )


class NLRuleResponse(BaseModel):
    """AI-generated structured rule from natural language (not auto-saved)."""

    name: str
    description: str | None = None
    conditions: dict
    actions: list[dict]
    stop_processing: bool = False
    ai_reasoning: str | None = Field(
        default=None,
        description="Explanation of the AI's interpretation.",
    )


# -- Test schemas -----------------------------------------------------------


class TestMailInput(BaseModel):
    """Sample mail data for testing a rule."""

    sender: str = Field(default="test@example.com")
    sender_name: str = Field(default="Test Sender")
    recipient: str = Field(default="me@example.com")
    subject: str = Field(default="Test subject")
    body: str = Field(default="Test body content")
    headers: dict[str, str] = Field(default_factory=dict)
    date: str = Field(default="2026-01-01T00:00:00Z")
    has_attachments: bool = False
    attachment_names: list[str] = Field(default_factory=list)
    mail_size: int = Field(default=1024)
    is_reply: bool = False
    is_forwarded: bool = False
    contact_name: str | None = None
    contact_org: str | None = None


class TestRuleResult(BaseModel):
    """Result of testing a rule against sample mail data."""

    matched: bool
    actions_that_would_execute: list[dict]
    evaluation_details: str | None = Field(
        default=None,
        description="Human-readable trace of condition evaluation.",
    )
