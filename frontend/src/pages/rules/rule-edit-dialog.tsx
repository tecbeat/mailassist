import { Save } from "lucide-react";
import type { UseFormReturn } from "react-hook-form";

import type { RuleAction, ConditionGroup } from "@/types/api";

import { AppDialog } from "@/components/app-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";

import {
  isConditionGroupValid,
  areActionsValid,
} from "./rules-constants";
import { ConditionBuilder } from "./condition-builder";
import { ActionsEditor } from "./actions-editor";
import type { RuleFormValues } from "./rule-form-schema";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface RuleEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editingRuleId: string | null;
  ruleForm: UseFormReturn<RuleFormValues>;
  conditions: ConditionGroup;
  onConditionsChange: (group: ConditionGroup) => void;
  actions: RuleAction[];
  onActionsChange: (actions: RuleAction[]) => void;
  isSaving: boolean;
  onSubmit: React.FormEventHandler<HTMLFormElement>;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function RuleEditDialog({
  open,
  onOpenChange,
  editingRuleId,
  ruleForm,
  conditions,
  onConditionsChange,
  actions,
  onActionsChange,
  isSaving,
  onSubmit,
}: RuleEditDialogProps) {
  return (
    <AppDialog
      open={open}
      onOpenChange={onOpenChange}
      title={editingRuleId ? "Edit Rule" : "Add Rule"}
      description={
        editingRuleId
          ? "Update rule conditions and actions."
          : "Define conditions to match emails and actions to execute."
      }
      size="wide"
      onCancel={() => onOpenChange(false)}
      cancelLabel="Cancel"
      primaryLabel={isSaving ? "Saving..." : editingRuleId ? "Update Rule" : "Create Rule"}
      primaryIcon={<Save />}
      loading={isSaving}
      primaryDisabled={isSaving || !isConditionGroupValid(conditions) || !areActionsValid(actions)}
      form="rule-form"
    >
      <form id="rule-form" onSubmit={onSubmit} className="space-y-4">
        {/* Name & Priority */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label className="text-xs">Name</Label>
            <Input
              {...ruleForm.register("name")}
              placeholder="Rule name..."
            />
            {ruleForm.formState.errors.name && (
              <p className="text-xs text-destructive">{ruleForm.formState.errors.name.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Priority</Label>
            <Input
              type="number"
              min={0}
              {...ruleForm.register("priority", { valueAsNumber: true })}
            />
            {ruleForm.formState.errors.priority && (
              <p className="text-xs text-destructive">{ruleForm.formState.errors.priority.message}</p>
            )}
          </div>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs">Description (optional)</Label>
          <Input
            {...ruleForm.register("description")}
            placeholder="What this rule does..."
          />
        </div>

        {/* Conditions */}
        <div className="space-y-1.5">
          <Label className="text-xs font-semibold">Conditions</Label>
          <ConditionBuilder
            group={conditions}
            onChange={onConditionsChange}
          />
        </div>

        <Separator />

        {/* Actions */}
        <div className="space-y-1.5">
          <Label className="text-xs font-semibold">Actions</Label>
          <ActionsEditor
            actions={actions}
            onChange={onActionsChange}
          />
        </div>

        <Separator />

        {/* Options */}
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <Label className="text-xs">Stop Processing</Label>
            <p className="text-[11px] text-muted-foreground">
              Skip remaining rules after this one matches.
            </p>
          </div>
          <Switch
            checked={ruleForm.watch("stop_processing")}
            onCheckedChange={(checked) => ruleForm.setValue("stop_processing", checked, { shouldDirty: true })}
          />
        </div>
      </form>
    </AppDialog>
  );
}
