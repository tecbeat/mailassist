"""Rule system API endpoints.

Provides CRUD for structured mail processing rules, bulk reorder,
rule testing against sample mail, and natural-language-to-rule AI translation.
"""

from typing import Any, cast
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUserId, DbSession, get_or_404
from app.core.security import get_encryption
from app.models import Rule, UserSettings
from app.plugins.base import MailContext
from app.schemas.rules import (
    ConditionGroup,
    NLRuleRequest,
    NLRuleResponse,
    ReorderRequest,
    RuleCreate,
    RuleListResponse,
    RuleResponse,
    RuleUpdate,
    TestMailInput,
    TestRuleResult,
)
from app.services.provider_resolver import get_default_provider
from app.services.rules import evaluate_conditions

logger = structlog.get_logger()

router = APIRouter(prefix="/api/rules", tags=["rules"])


# ---------------------------------------------------------------------------
# Fixed-path routes MUST come before parameterized {rule_id} routes so
# FastAPI does not try to parse "reorder" / "from-natural-language" as UUIDs.
# ---------------------------------------------------------------------------


@router.put("/reorder")
async def reorder_rules(
    data: ReorderRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> RuleListResponse:
    """Bulk update rule priorities for drag-drop reordering."""
    uid = UUID(user_id)

    # Fetch all referenced rules in one query
    rule_ids = [item.id for item in data.rules]
    stmt = select(Rule).where(Rule.user_id == uid, Rule.id.in_(rule_ids))
    result = await db.execute(stmt)
    rules_by_id = {r.id: r for r in result.scalars().all()}

    updated = 0
    for item in data.rules:
        rule = rules_by_id.get(item.id)
        if rule is None:
            continue
        rule.priority = item.priority
        updated += 1

    await db.flush()
    logger.info("rules_reordered", count=updated, user_id=user_id)

    # Return updated list (pass explicit None to avoid Query() sentinel leaking)
    return await list_rules(db, user_id, mail_account_id=None, is_active=None)


class _NLRuleAIResponse(BaseModel):
    """Schema for LLM output when translating NL to a structured rule."""

    name: str
    description: str | None = None
    conditions: dict[str, Any]
    actions: list[dict[str, Any]]
    stop_processing: bool = False
    reasoning: str | None = None


@router.post("/from-natural-language")
async def nl_to_rule(
    data: NLRuleRequest,
    db: DbSession,
    user_id: CurrentUserId,
) -> NLRuleResponse:
    """Translate a natural language description into a structured rule.

    Uses the user's default AI provider to generate the rule structure.
    The result is NOT auto-saved -- the user must confirm and create via POST.
    """
    uid = UUID(user_id)

    # Resolve default provider
    provider = await get_default_provider(db, uid)
    if provider is None:
        raise HTTPException(
            status_code=422,
            detail="No AI provider configured. Add a provider before using NL rule creation.",
        )

    encryption = get_encryption()
    api_key = None
    if provider.api_key:
        api_key = encryption.decrypt(provider.api_key)

    system_prompt = _NL_SYSTEM_PROMPT
    user_prompt = f"Create a mail processing rule from this description:\n\n{data.description}"

    from app.services.ai import call_llm

    user_settings = (await db.execute(select(UserSettings).where(UserSettings.user_id == uid))).scalar_one_or_none()

    try:
        ai_response, _tokens = await call_llm(
            provider_type=provider.provider_type.value,
            base_url=provider.base_url,
            model_name=provider.model_name,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=_NLRuleAIResponse,
            max_tokens=provider.max_tokens,
            temperature=0.3,
            user_id=user_id,
            timeout=provider.timeout_seconds or (user_settings.ai_timeout_seconds if user_settings else None),
        )
    except ValueError as e:
        logger.warning("nl_to_rule_validation_failed", error=str(e), user_id=user_id)
        raise HTTPException(status_code=422, detail="AI could not generate a valid rule") from None
    except Exception as e:
        logger.error("nl_to_rule_llm_failed", error=str(e), user_id=user_id)
        raise HTTPException(status_code=502, detail="AI provider error") from None

    nl_response = cast("_NLRuleAIResponse", ai_response)
    return NLRuleResponse(
        name=nl_response.name,
        description=nl_response.description,
        conditions=nl_response.conditions,
        actions=nl_response.actions,
        stop_processing=nl_response.stop_processing,
        ai_reasoning=nl_response.reasoning,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.get("")
async def list_rules(
    db: DbSession,
    user_id: CurrentUserId,
    mail_account_id: UUID | None = Query(default=None, description="Filter by account"),
    is_active: bool | None = Query(default=None, description="Filter by active status"),
) -> RuleListResponse:
    """List all rules for the current user, ordered by priority."""
    uid = UUID(user_id)
    stmt = select(Rule).where(Rule.user_id == uid)

    if mail_account_id is not None:
        stmt = stmt.where((Rule.mail_account_id == mail_account_id) | (Rule.mail_account_id.is_(None)))
    if is_active is not None:
        stmt = stmt.where(Rule.is_active == is_active)

    stmt = stmt.order_by(Rule.priority.asc(), Rule.created_at.asc())
    result = await db.execute(stmt)
    rules = result.scalars().all()

    return RuleListResponse(
        items=[RuleResponse.model_validate(r) for r in rules],
        total=len(rules),
        page=1,
        per_page=len(rules),
        pages=1,
    )


@router.post("", status_code=201)
async def create_rule(
    data: RuleCreate,
    db: DbSession,
    user_id: CurrentUserId,
) -> RuleResponse:
    """Create a new processing rule."""
    uid = UUID(user_id)

    rule = Rule(
        user_id=uid,
        mail_account_id=data.mail_account_id,
        name=data.name,
        description=data.description,
        priority=data.priority,
        is_active=data.is_active,
        conditions=data.conditions.model_dump(),
        actions=[a.model_dump() for a in data.actions],
        stop_processing=data.stop_processing,
    )
    db.add(rule)
    await db.flush()

    logger.info("rule_created", rule_id=str(rule.id), name=rule.name, user_id=user_id)
    return RuleResponse.model_validate(rule)


@router.get("/{rule_id}")
async def get_rule(
    rule_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> RuleResponse:
    """Get a single rule by ID."""
    rule = await get_or_404(db, Rule, rule_id, user_id, "Rule not found")
    return RuleResponse.model_validate(rule)


@router.put("/{rule_id}")
async def update_rule(
    rule_id: UUID,
    data: RuleUpdate,
    db: DbSession,
    user_id: CurrentUserId,
) -> RuleResponse:
    """Update a rule. Only provided fields are changed."""
    rule = await get_or_404(db, Rule, rule_id, user_id, "Rule not found")

    update_data = data.model_dump(exclude_unset=True)

    # Serialize nested Pydantic models to dicts for JSON columns
    if "conditions" in update_data and update_data["conditions"] is not None:
        update_data["conditions"] = data.conditions.model_dump()  # type: ignore[union-attr]
    if "actions" in update_data and update_data["actions"] is not None:
        update_data["actions"] = [a.model_dump() for a in data.actions]  # type: ignore[union-attr]

    for field, value in update_data.items():
        setattr(rule, field, value)

    await db.flush()
    logger.info("rule_updated", rule_id=str(rule_id), user_id=user_id)
    return RuleResponse.model_validate(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: UUID,
    db: DbSession,
    user_id: CurrentUserId,
) -> None:
    """Delete a rule."""
    rule = await get_or_404(db, Rule, rule_id, user_id, "Rule not found")
    await db.delete(rule)
    await db.flush()
    logger.info("rule_deleted", rule_id=str(rule_id), user_id=user_id)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@router.post("/{rule_id}/test")
async def test_rule(
    rule_id: UUID,
    data: TestMailInput,
    db: DbSession,
    user_id: CurrentUserId,
) -> TestRuleResult:
    """Test a rule against sample mail data without executing actions."""
    rule = await get_or_404(db, Rule, rule_id, user_id, "Rule not found")

    # Build a MailContext from the sample data
    context = _build_test_context(data)

    try:
        conditions = ConditionGroup.model_validate(rule.conditions)
    except Exception as e:
        logger.error("invalid_rule_conditions", rule_id=str(rule_id), error=str(e))
        raise HTTPException(status_code=422, detail="Invalid rule conditions") from e

    matched = evaluate_conditions(conditions, context)

    return TestRuleResult(
        matched=matched,
        actions_that_would_execute=rule.actions if matched else [],
        evaluation_details=f"Rule '{rule.name}' {'matched' if matched else 'did not match'} the sample mail.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_test_context(data: TestMailInput) -> MailContext:
    """Build a MailContext from test sample data."""
    contact = None
    if data.contact_name or data.contact_org:
        contact = {
            "display_name": data.contact_name or "",
            "organization": data.contact_org or "",
        }

    return MailContext(
        user_id="test",
        account_id="test",
        mail_uid="test-uid",
        sender=data.sender,
        sender_name=data.sender_name,
        recipient=data.recipient,
        subject=data.subject,
        body=data.body,
        body_plain=data.body,
        body_html="",
        headers=data.headers,
        date=data.date,
        has_attachments=data.has_attachments,
        attachment_names=data.attachment_names,
        account_name="Test Account",
        account_email="test@example.com",
        existing_labels=[],
        existing_folders=[],
        folder_separator="/",
        mail_size=data.mail_size,
        thread_length=1,
        is_reply=data.is_reply,
        is_forwarded=data.is_forwarded,
        contact=contact,
        excluded_folders=[],
    )


_NL_SYSTEM_PROMPT = """You are an email rule creation assistant. Convert natural language
descriptions into structured email processing rules.

You MUST respond with a JSON object matching this exact schema:
{
  "name": "Short rule name",
  "description": "Optional description",
  "conditions": {
    "operator": "AND" or "OR",
    "rules": [
      {"field": "<field>", "op": "<operator>", "value": "<value>"},
      ...or nested groups with "operator" and "rules"
    ]
  },
  "actions": [
    {"type": "<action_type>", "target": "<optional>", "value": "<optional>"},
    ...
  ],
  "stop_processing": false,
  "reasoning": "Brief explanation of your interpretation"
}

Available condition fields:
- from, to, cc, subject, body (string fields)
- has_attachment (boolean), attachment_name (string)
- date (datetime string), size (integer, bytes)
- header:<name> (any mail header)
- contact_name, contact_org (from address book)
- is_reply, is_forwarded (boolean)

Available operators:
- equals, not_equals, contains, not_contains
- starts_with, ends_with, matches_regex
- greater_than, less_than (for numeric/date fields)
- is_empty, is_not_empty

Available action types:
- move (requires target: folder path)
- copy (requires target: folder path)
- label (requires value: label name)
- remove_label (requires value: label name)
- mark_read, mark_unread, flag, delete (no params)
- notify (requires target: notification template text)
- create_draft, create_calendar_event (no params)

Rules:
- Use case-insensitive matching for string comparisons
- Prefer "contains" for partial matches unless the user explicitly wants exact match
- Only use "matches_regex" when the user explicitly describes a pattern
- Set stop_processing to true only if the user says to stop further rules
- Keep conditions as simple as possible while capturing the user's intent
"""
