import { Plus, X } from "lucide-react";

import type { RuleAction } from "@/types/api";
import { ActionType } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  ACTION_TYPE_OPTIONS,
  ACTIONS_NEEDING_VALUE,
  ACTIONS_NEEDING_TARGET,
  createEmptyAction,
  getKey,
} from "./rules-constants";

// ---------------------------------------------------------------------------
// Actions editor
// ---------------------------------------------------------------------------

interface ActionsEditorProps {
  actions: RuleAction[];
  onChange: (actions: RuleAction[]) => void;
}

export function ActionsEditor({ actions, onChange }: ActionsEditorProps) {
  const updateAction = (index: number, updated: RuleAction) => {
    const newActions = [...actions];
    newActions[index] = updated;
    onChange(newActions);
  };

  const addAction = () => {
    onChange([...actions, createEmptyAction()]);
  };

  const removeAction = (index: number) => {
    if (actions.length <= 1) return;
    onChange(actions.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2">
      {actions.map((action, index) => (
        <div key={getKey(action)} className="flex items-center gap-2">
          <Select
            value={action.type}
            onValueChange={(v) =>
              updateAction(index, { ...action, type: v as RuleAction["type"] })
            }
          >
            <SelectTrigger className="h-8 w-[160px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ACTION_TYPE_OPTIONS.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {ACTIONS_NEEDING_VALUE.includes(action.type as ActionType) && (
            <Input
              value={action.value ?? ""}
              onChange={(e) => updateAction(index, { ...action, value: e.target.value })}
              className="h-8 flex-1 text-xs"
              placeholder="Value (e.g. label name)..."
            />
          )}

          {ACTIONS_NEEDING_TARGET.includes(action.type as ActionType) && (
            <Input
              value={action.target ?? ""}
              onChange={(e) => updateAction(index, { ...action, target: e.target.value })}
              className="h-8 flex-1 text-xs"
              placeholder="Target (e.g. folder path)..."
            />
          )}

          <AppButton
            icon={<X />}
            label="Remove action"
            variant="ghost"
            color="destructive"
            className="h-7 w-7 shrink-0"
            onClick={() => removeAction(index)}
            disabled={actions.length <= 1}
          />
        </div>
      ))}

      <AppButton icon={<Plus />} label="Add action" className="h-7 text-xs" type="button" onClick={addAction}>Action</AppButton>
    </div>
  );
}
