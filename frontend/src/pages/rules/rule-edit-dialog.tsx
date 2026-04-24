import { X, Save } from "lucide-react";
import type { UseFormReturn } from "react-hook-form";

import type { RuleAction, ConditionGroup } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

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
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editingRuleId ? "Edit Rule" : "Add Rule"}</DialogTitle>
          <DialogDescription>
            {editingRuleId
              ? "Update rule conditions and actions."
              : "Define conditions to match emails and actions to execute."}
          </DialogDescription>
        </DialogHeader>

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

        <DialogFooter>
          <AppButton icon={<X />} label="Cancel" onClick={() => onOpenChange(false)}>Cancel</AppButton>
          <AppButton icon={<Save />} label={editingRuleId ? "Update Rule" : "Create Rule"} type="submit" form="rule-form" variant="primary" loading={isSaving} disabled={isSaving || !isConditionGroupValid(conditions) || !areActionsValid(actions)}>{isSaving ? "Saving..." : editingRuleId ? "Update Rule" : "Create Rule"}</AppButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
