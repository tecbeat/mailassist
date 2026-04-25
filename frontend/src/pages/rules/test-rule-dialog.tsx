import {
  Check,
  FlaskConical,
  X,
  XCircle,
} from "lucide-react";

import type { TestMailInput, TestRuleResult } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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

import { summarizeActions } from "./rules-constants";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface TestRuleDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  testInput: TestMailInput;
  onTestInputChange: React.Dispatch<React.SetStateAction<TestMailInput>>;
  testResult: TestRuleResult | null;
  isPending: boolean;
  onRunTest: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TestRuleDialog({
  open,
  onOpenChange,
  testInput,
  onTestInputChange,
  testResult,
  isPending,
  onRunTest,
}: TestRuleDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Test Rule</DialogTitle>
          <DialogDescription>
            Enter sample email data to test if this rule would match.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label className="text-xs">Sender</Label>
              <Input
                value={testInput.sender ?? ""}
                onChange={(e) => onTestInputChange((s) => ({ ...s, sender: e.target.value }))}
                placeholder="sender@example.com"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Recipient</Label>
              <Input
                value={testInput.recipient ?? ""}
                onChange={(e) => onTestInputChange((s) => ({ ...s, recipient: e.target.value }))}
                placeholder="you@example.com"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Subject</Label>
            <Input
              value={testInput.subject ?? ""}
              onChange={(e) => onTestInputChange((s) => ({ ...s, subject: e.target.value }))}
              placeholder="Email subject..."
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Body</Label>
            <Textarea
              value={testInput.body ?? ""}
              onChange={(e) => onTestInputChange((s) => ({ ...s, body: e.target.value }))}
              placeholder="Email body..."
              className="min-h-[80px]"
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <div className="flex items-center gap-2">
              <Switch
                id="test-attachments"
                checked={testInput.has_attachments ?? false}
                onCheckedChange={(checked) => onTestInputChange((s) => ({ ...s, has_attachments: checked }))}
              />
              <Label htmlFor="test-attachments" className="text-xs">
                Has Attachments
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="test-reply"
                checked={testInput.is_reply ?? false}
                onCheckedChange={(checked) => onTestInputChange((s) => ({ ...s, is_reply: checked }))}
              />
              <Label htmlFor="test-reply" className="text-xs">
                Is Reply
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="test-forwarded"
                checked={testInput.is_forwarded ?? false}
                onCheckedChange={(checked) => onTestInputChange((s) => ({ ...s, is_forwarded: checked }))}
              />
              <Label htmlFor="test-forwarded" className="text-xs">
                Is Forwarded
              </Label>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label className="text-xs">Contact Name</Label>
              <Input
                value={testInput.contact_name ?? ""}
                onChange={(e) => onTestInputChange((s) => ({ ...s, contact_name: e.target.value || null }))}
                placeholder="John Doe"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Contact Org</Label>
              <Input
                value={testInput.contact_org ?? ""}
                onChange={(e) => onTestInputChange((s) => ({ ...s, contact_org: e.target.value || null }))}
                placeholder="Acme Inc."
              />
            </div>
          </div>
        </div>

        {/* Test result */}
        {testResult && (
          <>
            <Separator />
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                {testResult.matched ? (
                  <>
                    <Check className="h-5 w-5 text-green-500" />
                    <span className="text-sm font-semibold text-green-600">Rule Matched</span>
                  </>
                ) : (
                  <>
                    <XCircle className="h-5 w-5 text-red-500" />
                    <span className="text-sm font-semibold text-red-600">No Match</span>
                  </>
                )}
              </div>

              {testResult.evaluation_details && (
                <pre className="max-h-[200px] overflow-auto whitespace-pre-wrap rounded-md bg-muted p-3 text-xs">
                  {testResult.evaluation_details}
                </pre>
              )}

              {testResult.matched && testResult.actions_that_would_execute.length > 0 && (
                <div className="space-y-1">
                  <p className="text-xs font-medium">Actions that would execute:</p>
                  <div className="flex flex-wrap gap-1">
                    {testResult.actions_that_would_execute.map((action, i) => (
                      <Badge key={i} variant="secondary">
                        {summarizeActions([action as Record<string, unknown>])}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        <DialogFooter>
          <AppButton icon={<X />} label="Close" onClick={() => onOpenChange(false)}>Close</AppButton>
          <AppButton icon={<FlaskConical />} label="Run Test" variant="primary" loading={isPending} disabled={isPending} onClick={onRunTest}>{isPending ? "Testing..." : "Run Test"}</AppButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
