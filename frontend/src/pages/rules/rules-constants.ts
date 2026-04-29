import type { ConditionGroup, ConditionRule, RuleAction } from "@/types/api";
import { FieldOperator, ActionType } from "@/types/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const FIELD_OPTIONS = [
  { value: "from", label: "From" },
  { value: "to", label: "To" },
  { value: "cc", label: "CC" },
  { value: "subject", label: "Subject" },
  { value: "body", label: "Body" },
  { value: "has_attachments", label: "Has Attachments" },
  { value: "is_reply", label: "Is Reply" },
  { value: "is_forwarded", label: "Is Forwarded" },
  { value: "attachment_name", label: "Attachment Name" },
  { value: "contact_name", label: "Contact Name" },
  { value: "contact_org", label: "Contact Org" },
  { value: "header:X-Mailer", label: "Header: X-Mailer" },
  { value: "header:X-Spam-Score", label: "Header: X-Spam-Score" },
  { value: "header:List-Unsubscribe", label: "Header: List-Unsubscribe" },
] as const;

export const OPERATOR_OPTIONS = Object.values(FieldOperator).map((op) => ({
  value: op,
  label: op.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
}));

export const OPERATORS_WITHOUT_VALUE: string[] = [FieldOperator.is_empty, FieldOperator.is_not_empty];

export const ACTION_TYPE_OPTIONS = Object.values(ActionType).map((t) => ({
  value: t,
  label: t.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
}));

export const ACTIONS_NEEDING_VALUE: ActionType[] = [
  ActionType.label,
  ActionType.remove_label,
  ActionType.flag,
];

export const ACTIONS_NEEDING_TARGET: ActionType[] = [
  ActionType.move,
  ActionType.copy,
  ActionType.notify,
  ActionType.create_draft,
];

export const MAX_NESTING_DEPTH = 5;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function isConditionGroup(rule: ConditionRule | ConditionGroup): rule is ConditionGroup {
  return "operator" in rule && "rules" in rule;
}

/**
 * Client-only key for stable React rendering.
 * Stripped before sending to the API; lives as an extra property
 * that the generated types do not declare.
 */
export const KEY_PROP = "_key" as const;

export function assignKey<T extends object>(obj: T): T & { [KEY_PROP]: string } {
  return { ...obj, [KEY_PROP]: crypto.randomUUID() };
}

const stableKeys = new WeakMap<object, string>();

export function getKey(obj: object): string {
  const rec = obj as Record<string, unknown>;
  const existing = rec[KEY_PROP] as string | undefined;
  if (existing) return existing;
  let key = stableKeys.get(obj);
  if (!key) {
    key = crypto.randomUUID();
    stableKeys.set(obj, key);
  }
  return key;
}

export function createEmptyConditionRule(): ConditionRule {
  return assignKey({ field: "from", op: FieldOperator.contains, value: "" });
}

export function createEmptyConditionGroup(): ConditionGroup {
  return assignKey({
    operator: "AND" as ConditionGroup["operator"],
    rules: [createEmptyConditionRule()],
  });
}

export function createEmptyAction(): RuleAction {
  return assignKey({ type: ActionType.label, value: "", target: null });
}

export function summarizeConditions(group: ConditionGroup | Record<string, unknown>, depth = 0): string {
  if (depth > 3) return "...";
  const g = group as ConditionGroup;
  if (!g.rules?.length) return "(empty)";

  const parts = g.rules.map((r) => {
    if (isConditionGroup(r as ConditionRule | ConditionGroup)) {
      return `(${summarizeConditions(r as ConditionGroup, depth + 1)})`;
    }
    const cr = r as ConditionRule;
    const op = String(cr.op).replace(/_/g, " ");
    if (OPERATORS_WITHOUT_VALUE.includes(cr.op)) {
      return `${cr.field} ${op}`;
    }
    return `${cr.field} ${op} "${cr.value ?? ""}"`;
  });

  return parts.join(` ${g.operator} `);
}

export function summarizeActions(actions: Array<Record<string, unknown> | RuleAction>): string {
  return actions
    .map((a) => {
      const label = String(a.type ?? "").replace(/_/g, " ");
      if (a.value) return `${label}: ${a.value}`;
      if (a.target) return `${label} -> ${a.target}`;
      return label;
    })
    .join(", ");
}

/** Validate that conditions have required values filled in. */
export function isConditionGroupValid(group: ConditionGroup): boolean {
  if (!group.rules?.length) return false;
  return group.rules.every((rule) => {
    if (isConditionGroup(rule as ConditionRule | ConditionGroup)) {
      return isConditionGroupValid(rule as ConditionGroup);
    }
    const cr = rule as ConditionRule;
    if (!cr.field || !cr.op) return false;
    if (OPERATORS_WITHOUT_VALUE.includes(cr.op)) return true;
    return typeof cr.value === "string" ? cr.value.trim().length > 0 : cr.value != null;
  });
}

/** Validate that all actions have required fields filled in. */
export function areActionsValid(actions: RuleAction[]): boolean {
  if (!actions.length) return false;
  return actions.every((action) => {
    if (!action.type) return false;
    if (ACTIONS_NEEDING_VALUE.includes(action.type as ActionType)) {
      return typeof action.value === "string" && action.value.trim().length > 0;
    }
    if (ACTIONS_NEEDING_TARGET.includes(action.type as ActionType)) {
      return typeof action.target === "string" && action.target.trim().length > 0;
    }
    return true;
  });
}
