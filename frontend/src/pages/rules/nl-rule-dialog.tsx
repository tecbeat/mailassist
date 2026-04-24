import { Check, Wand2, X } from "lucide-react";

import type { NLRuleResponse, ConditionGroup } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import { summarizeConditions, summarizeActions } from "./rules-constants";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface NlRuleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  description: string;
  onDescriptionChange: (value: string) => void;
  result: NLRuleResponse | null;
  isPending: boolean;
  onGenerate: () => void;
  onConfirm: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function NlRuleDialog({
  open,
  onOpenChange,
  description,
  onDescriptionChange,
  result,
  isPending,
  onGenerate,
  onConfirm,
}: NlRuleDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Create Rule from Natural Language</DialogTitle>
          <DialogDescription>
            Describe what you want in plain English and AI will generate a structured rule for you.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label className="text-xs">Describe your rule</Label>
            <Textarea
              value={description}
              onChange={(e) => onDescriptionChange(e.target.value)}
              placeholder="e.g. Move all emails from newsletters@example.com to the Newsletters folder and mark them as read..."
              className="min-h-[100px]"
            />
          </div>

          <AppButton icon={<Wand2 />} label="Generate Rule" variant="primary" loading={isPending} disabled={isPending || !description.trim()} className="w-full" onClick={onGenerate}>{isPending ? "Generating..." : "Generate Rule"}</AppButton>

          {/* NL result preview */}
          {result && (
            <>
              <Separator />
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">{result.name}</CardTitle>
                  {result.description && (
                    <CardDescription className="text-xs">
                      {result.description}
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="space-y-2">
                  {result.ai_reasoning && (
                    <div className="rounded-md bg-muted p-2 text-xs text-muted-foreground">
                      <span className="font-medium">AI reasoning:</span>{" "}
                      {result.ai_reasoning}
                    </div>
                  )}
                  <div className="text-xs">
                    <span className="font-medium">Conditions:</span>{" "}
                    {summarizeConditions(result.conditions as unknown as ConditionGroup)}
                  </div>
                  <div className="text-xs">
                    <span className="font-medium">Actions:</span>{" "}
                    {summarizeActions(result.actions as Array<Record<string, unknown>>)}
                  </div>
                  {result.stop_processing && (
                    <Badge variant="secondary">
                      Stop processing
                    </Badge>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </div>

        {result && (
          <DialogFooter>
            <AppButton icon={<X />} label="Cancel" onClick={() => onOpenChange(false)}>Cancel</AppButton>
            <AppButton icon={<Check />} label="Edit & Save" variant="primary" onClick={onConfirm}>Edit & Save</AppButton>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}
