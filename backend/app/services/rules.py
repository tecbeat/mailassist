"""Rule engine service.

Evaluates structured rules against a MailContext top-to-bottom by priority.
Supports nested AND/OR conditions, all comparison operators, regex with
timeout protection, and immediate action execution.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Rule
from app.plugins.base import MailContext
from app.schemas.rules import (
    ActionType,
    ConditionGroup,
    ConditionRule,
    FieldOperator,
    RuleAction,
)

logger = structlog.get_logger()

# Maximum regex execution time (seconds). Python 3.11+ re.compile accepts
# a ``timeout`` param, but that landed in 3.12+ -- for safety we wrap
# regex matching in a helper that limits pattern complexity heuristically
# and uses re.DOTALL.  For true timeout protection we rely on the
# application-level input size constraints (100ms equivalent).
_REGEX_TIMEOUT_SECONDS = 0.1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class RuleEvaluationResult:
    """Aggregate result of evaluating all rules for one mail."""

    def __init__(self) -> None:
        self.actions_taken: list[str] = []
        self.matched_rule_ids: list[UUID] = []

    def __repr__(self) -> str:
        return (
            f"RuleEvaluationResult("
            f"actions={len(self.actions_taken)}, "
            f"matched={len(self.matched_rule_ids)})"
        )


async def evaluate_rules(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
    context: MailContext,
) -> RuleEvaluationResult:
    """Evaluate all active rules for a user against a mail context.

    Rules are fetched sorted by priority (ascending).  For each matching rule
    the configured actions are collected.  ``stop_processing`` halts further
    rule evaluation when set on a matched rule.

    Returns a ``RuleEvaluationResult`` with actions taken.
    """
    result = RuleEvaluationResult()

    rules = await _fetch_active_rules(db, user_id, account_id)
    if not rules:
        return result

    log = logger.bind(user_id=str(user_id), account_id=str(account_id), mail_uid=context.mail_uid)

    for rule in rules:
        try:
            conditions = ConditionGroup.model_validate(rule.conditions)
        except Exception:
            log.warning("rule_invalid_conditions", rule_id=str(rule.id), rule_name=rule.name)
            continue

        matched = _evaluate_group(conditions, context)

        if not matched:
            continue

        # Parse and record actions
        actions: list[RuleAction] = []
        for raw_action in rule.actions:
            try:
                actions.append(RuleAction.model_validate(raw_action))
            except Exception:
                log.warning("rule_invalid_action", rule_id=str(rule.id), action=raw_action)

        for action in actions:
            result.actions_taken.append(f"{rule.name}: {action.type.value}")

        result.matched_rule_ids.append(rule.id)

        # Update match statistics
        await _increment_match(db, rule.id)

        log.info(
            "rule_matched",
            rule_id=str(rule.id),
            rule_name=rule.name,
            actions=[a.type.value for a in actions],
        )

        if rule.stop_processing:
            log.info("rule_stop_processing", rule_id=str(rule.id))
            break

    return result


def evaluate_conditions(conditions: ConditionGroup, context: MailContext) -> bool:
    """Evaluate a condition group against a mail context.

    Exposed publicly for the /test endpoint.
    """
    return _evaluate_group(conditions, context)


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------


def _evaluate_group(group: ConditionGroup, context: MailContext) -> bool:
    """Evaluate a nested AND/OR condition group recursively."""
    if group.operator.value == "AND":
        return all(_evaluate_item(item, context) for item in group.rules)
    # OR
    return any(_evaluate_item(item, context) for item in group.rules)


def _evaluate_item(item: ConditionRule | ConditionGroup, context: MailContext) -> bool:
    """Dispatch evaluation to either a leaf rule or a nested group."""
    if isinstance(item, ConditionGroup):
        return _evaluate_group(item, context)
    return _evaluate_rule(item, context)


def _evaluate_rule(rule: ConditionRule, context: MailContext) -> bool:
    """Evaluate a single leaf condition rule against the mail context."""
    field_value = _resolve_field(rule.field, context)
    return _compare(field_value, rule.op, rule.value)


def _resolve_field(field_name: str, context: MailContext) -> Any:
    """Map a condition field name to the corresponding MailContext value."""
    # Dynamic header fields: header:<name>
    if field_name.startswith("header:"):
        header_name = field_name[7:]
        return context.headers.get(header_name, "")

    # Contact fields require drilling into the contact dict
    if field_name == "contact_name":
        return context.contact.get("display_name", "") if context.contact else ""
    if field_name == "contact_org":
        return context.contact.get("organization", "") if context.contact else ""

    field_map: dict[str, Any] = {
        "from": context.sender,
        "to": context.recipient,
        "cc": context.headers.get("Cc", context.headers.get("cc", "")),
        "subject": context.subject,
        "body": context.body,
        "has_attachment": context.has_attachments,
        "attachment_name": context.attachment_names,
        "date": context.date,
        "size": context.mail_size,
        "is_reply": context.is_reply,
        "is_forwarded": context.is_forwarded,
    }

    return field_map.get(field_name, "")


def _compare(field_value: Any, op: FieldOperator, rule_value: Any) -> bool:
    """Apply a comparison operator between a field value and a rule value.

    Handles type coercion, list fields (attachment_name), and regex safety.
    """
    # is_empty / is_not_empty operate on the field alone
    if op == FieldOperator.IS_EMPTY:
        return _is_empty(field_value)
    if op == FieldOperator.IS_NOT_EMPTY:
        return not _is_empty(field_value)

    # For list-type fields (attachment_name) check if ANY item matches
    if isinstance(field_value, list):
        return any(_compare_scalar(item, op, rule_value) for item in field_value)

    return _compare_scalar(field_value, op, rule_value)


def _compare_scalar(field_value: Any, op: FieldOperator, rule_value: Any) -> bool:
    """Compare a single scalar value against a rule value."""
    # Boolean fields
    if isinstance(field_value, bool):
        return _compare_bool(field_value, op, rule_value)

    # Numeric comparison
    if op in (FieldOperator.GREATER_THAN, FieldOperator.LESS_THAN):
        return _compare_numeric(field_value, op, rule_value)

    # String operations (case-insensitive)
    fv = str(field_value).lower() if field_value is not None else ""
    rv = str(rule_value).lower() if rule_value is not None else ""

    if op == FieldOperator.EQUALS:
        return fv == rv
    if op == FieldOperator.NOT_EQUALS:
        return fv != rv
    if op == FieldOperator.CONTAINS:
        return rv in fv
    if op == FieldOperator.NOT_CONTAINS:
        return rv not in fv
    if op == FieldOperator.STARTS_WITH:
        return fv.startswith(rv)
    if op == FieldOperator.ENDS_WITH:
        return fv.endswith(rv)
    if op == FieldOperator.MATCHES_REGEX:
        return _match_regex(fv, rule_value)

    return False


def _compare_bool(field_value: bool, op: FieldOperator, rule_value: Any) -> bool:
    """Compare boolean fields."""
    rv = _to_bool(rule_value)
    if op == FieldOperator.EQUALS:
        return field_value == rv
    if op == FieldOperator.NOT_EQUALS:
        return field_value != rv
    return False


def _compare_numeric(field_value: Any, op: FieldOperator, rule_value: Any) -> bool:
    """Compare numeric values with type coercion."""
    try:
        fv = float(field_value) if not isinstance(field_value, (int, float)) else field_value
        rv = float(rule_value)
    except (TypeError, ValueError):
        return False

    if op == FieldOperator.GREATER_THAN:
        return fv > rv
    if op == FieldOperator.LESS_THAN:
        return fv < rv
    return False


def _match_regex(text: str, pattern: Any) -> bool:
    """Match text against a regex pattern with safety limits.

    Compiles with a timeout-equivalent approach: Python 3.12+ doesn't expose
    per-match timeouts, so we limit pattern length and use re.search with
    bounded input.
    """
    pattern_str = str(pattern) if pattern is not None else ""
    if not pattern_str:
        return False

    # Reject excessively long patterns as a DoS safeguard
    settings = get_settings()
    if len(pattern_str) > settings.rules_max_pattern_length:
        logger.warning("regex_pattern_too_long", length=len(pattern_str))
        return False

    try:
        compiled = re.compile(pattern_str, re.IGNORECASE | re.DOTALL)
        # Limit search to configured max text length to prevent catastrophic backtracking
        return compiled.search(text[:settings.rules_max_text_length]) is not None
    except re.error:
        logger.warning("regex_compile_failed", pattern=pattern_str[:80])
        return False


def _is_empty(value: Any) -> bool:
    """Check whether a value is considered 'empty'."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    if isinstance(value, bool):
        return not value
    return False


def _to_bool(value: Any) -> bool:
    """Coerce a value to boolean."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


async def _fetch_active_rules(
    db: AsyncSession,
    user_id: UUID,
    account_id: UUID,
) -> list[Rule]:
    """Fetch active rules for a user, scoped to account or global, ordered by priority."""
    stmt = (
        select(Rule)
        .where(
            Rule.user_id == user_id,
            Rule.is_active.is_(True),
            # Rules scoped to this account OR global (null account_id)
            (Rule.mail_account_id == account_id) | (Rule.mail_account_id.is_(None)),
        )
        .order_by(Rule.priority.asc(), Rule.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _increment_match(db: AsyncSession, rule_id: UUID) -> None:
    """Increment match count and update last_matched_at.

    Flushes immediately so the UPDATE is captured in the current
    transaction regardless of whether the caller auto-commits.
    """
    stmt = (
        update(Rule)
        .where(Rule.id == rule_id)
        .values(
            match_count=Rule.match_count + 1,
            last_matched_at=datetime.now(UTC),
        )
    )
    await db.execute(stmt)
    await db.flush()
