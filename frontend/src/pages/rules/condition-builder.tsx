import { Plus, X } from "lucide-react";

import type { ConditionGroup, ConditionRule } from "@/types/api";
import { ConditionOperator } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import {
  FIELD_OPTIONS,
  OPERATOR_OPTIONS,
  OPERATORS_WITHOUT_VALUE,
  MAX_NESTING_DEPTH,
  isConditionGroup,
  createEmptyConditionRule,
  createEmptyConditionGroup,
} from "./rules-constants";

// ---------------------------------------------------------------------------
// Single condition rule row
// ---------------------------------------------------------------------------

interface ConditionRuleRowProps {
  rule: ConditionRule;
  onChange: (rule: ConditionRule) => void;
  onRemove: () => void;
  canRemove: boolean;
}

function ConditionRuleRow({ rule, onChange, onRemove, canRemove }: ConditionRuleRowProps) {
  const needsValue = !OPERATORS_WITHOUT_VALUE.includes(rule.op);

  return (
    <div className="flex items-center gap-2">
      <Select value={rule.field} onValueChange={(v) => onChange({ ...rule, field: v })}>
        <SelectTrigger className="h-7 w-[140px] text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {FIELD_OPTIONS.map((f) => (
            <SelectItem key={f.value} value={f.value}>
              {f.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={rule.op} onValueChange={(v) => onChange({ ...rule, op: v as ConditionRule["op"] })}>
        <SelectTrigger className="h-7 w-[130px] text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {OPERATOR_OPTIONS.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {needsValue && (
        <Input
          value={String(rule.value ?? "")}
          onChange={(e) => onChange({ ...rule, value: e.target.value })}
          className="h-7 flex-1 text-xs"
          placeholder="Value..."
        />
      )}

      <AppButton
        icon={<X />}
        label="Remove condition"
        variant="ghost"
        color="destructive"
        className="h-7 w-7 shrink-0"
        onClick={onRemove}
        disabled={!canRemove}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Condition builder (recursive)
// ---------------------------------------------------------------------------

interface ConditionBuilderProps {
  group: ConditionGroup;
  onChange: (group: ConditionGroup) => void;
  depth?: number;
}

export function ConditionBuilder({ group, onChange, depth = 0 }: ConditionBuilderProps) {
  const updateOperator = (op: string) => {
    onChange({ ...group, operator: op as ConditionGroup["operator"] });
  };

  const updateRule = (index: number, updated: ConditionRule | ConditionGroup) => {
    const newRules = [...group.rules];
    newRules[index] = updated;
    onChange({ ...group, rules: newRules });
  };

  const addRule = () => {
    onChange({ ...group, rules: [...group.rules, createEmptyConditionRule()] });
  };

  const addGroup = () => {
    if (depth >= MAX_NESTING_DEPTH - 1) return;
    onChange({ ...group, rules: [...group.rules, createEmptyConditionGroup()] });
  };

  const removeRule = (index: number) => {
    if (group.rules.length <= 1) return;
    const newRules = group.rules.filter((_, i) => i !== index);
    onChange({ ...group, rules: newRules });
  };

  return (
    <div
      className={cn(
        "rounded-md border border-border p-3 space-y-2",
        depth > 0 && "ml-4 border-dashed",
      )}
    >
      {/* Group header */}
      <div className="flex items-center gap-2">
        <Select value={group.operator} onValueChange={updateOperator}>
          <SelectTrigger className="w-20 h-7 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ConditionOperator.AND}>AND</SelectItem>
            <SelectItem value={ConditionOperator.OR}>OR</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">
          {group.operator === ConditionOperator.AND
            ? "All conditions must match"
            : "Any condition must match"}
        </span>
      </div>

      {/* Rules */}
      {group.rules.map((rule, index) => {
        const isGroup = isConditionGroup(rule as ConditionRule | ConditionGroup);
        return (
          <div key={index} className="relative">
            {isGroup ? (
              <div className="flex items-start gap-1">
                <div className="flex-1">
                  <ConditionBuilder
                    group={rule as ConditionGroup}
                    onChange={(updated) => updateRule(index, updated)}
                    depth={depth + 1}
                  />
                </div>
                <AppButton
                  icon={<X />}
                  label="Remove condition group"
                  variant="ghost"
                  color="destructive"
                  className="h-7 w-7 shrink-0"
                  onClick={() => removeRule(index)}
                  disabled={group.rules.length <= 1}
                />
              </div>
            ) : (
              <ConditionRuleRow
                rule={rule as ConditionRule}
                onChange={(updated) => updateRule(index, updated)}
                onRemove={() => removeRule(index)}
                canRemove={group.rules.length > 1}
              />
            )}
          </div>
        );
      })}

      {/* Add buttons */}
      <div className="flex gap-2 pt-1">
        <AppButton icon={<Plus />} label="Add condition" className="h-7 text-xs" type="button" onClick={addRule}>Condition</AppButton>
        {depth < MAX_NESTING_DEPTH - 1 && (
          <AppButton icon={<Plus />} label="Add condition group" className="h-7 text-xs" type="button" onClick={addGroup}>Group</AppButton>
        )}
      </div>
    </div>
  );
}
