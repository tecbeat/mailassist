import { z } from "zod/v4";

import type { RuleResponse, RuleAction, ConditionGroup, NLRuleResponse } from "@/types/api";

import { createEmptyConditionGroup, createEmptyAction } from "./rules-constants";

// ---------------------------------------------------------------------------
// Rule form schema (top-level fields validated by zod)
// ---------------------------------------------------------------------------

export const ruleFormSchema = z.object({
  name: z.string().trim().min(1, "Name is required"),
  description: z.string(),
  priority: z.number().int().min(0, "Priority must be non-negative"),
  is_active: z.boolean(),
  stop_processing: z.boolean(),
});

export type RuleFormValues = z.infer<typeof ruleFormSchema>;

export function emptyFormDefaults(priority = 0): RuleFormValues {
  return { name: "", description: "", priority, is_active: true, stop_processing: false };
}

export function ruleToFormValues(rule: RuleResponse): RuleFormValues {
  return {
    name: rule.name,
    description: rule.description ?? "",
    priority: rule.priority,
    is_active: rule.is_active,
    stop_processing: rule.stop_processing,
  };
}

export function ruleToConditions(rule: RuleResponse): ConditionGroup {
  const conditions = rule.conditions as unknown as ConditionGroup;
  return conditions?.operator ? conditions : createEmptyConditionGroup();
}

export function ruleToActions(rule: RuleResponse): RuleAction[] {
  const actions = rule.actions as unknown as RuleAction[];
  return actions?.length ? actions : [createEmptyAction()];
}

export function nlResponseToFormValues(nl: NLRuleResponse): RuleFormValues {
  return {
    name: nl.name,
    description: nl.description ?? "",
    priority: 0,
    is_active: true,
    stop_processing: nl.stop_processing ?? false,
  };
}

export function nlResponseToConditions(nl: NLRuleResponse): ConditionGroup {
  const conditions = nl.conditions as unknown as ConditionGroup;
  return conditions?.operator ? conditions : createEmptyConditionGroup();
}

export function nlResponseToActions(nl: NLRuleResponse): RuleAction[] {
  const actions = nl.actions as unknown as RuleAction[];
  return actions?.length ? actions : [createEmptyAction()];
}
