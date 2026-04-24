import { X, Save } from "lucide-react";

import type { ApprovalResponse } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ApprovalEditFormProps {
  approval: ApprovalResponse;
  editedAction: Record<string, unknown>;
  onChangeAction: (action: Record<string, unknown>) => void;
  onSave: () => void;
  onCancel: () => void;
  isSaving: boolean;
}

// ---------------------------------------------------------------------------
// Known function types with structured edit fields
// ---------------------------------------------------------------------------

const KNOWN_TYPES = [
  "labeling",
  "smart_folder",
  "auto_reply",
  "calendar_extraction",
  "notifications",
  "email_summary",
  "coupon_extraction",
  "contacts",
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ApprovalEditForm({
  approval,
  editedAction,
  onChangeAction,
  onSave,
  onCancel,
  isSaving,
}: ApprovalEditFormProps) {
  const ft = approval.function_type;

  const updateField = (key: string, value: unknown) => {
    onChangeAction({ ...editedAction, [key]: value });
  };

  return (
    <div className="space-y-3">
      <p className="text-xs font-medium text-muted-foreground">
        Edit proposed action before approving
      </p>

      {ft === "labeling" && (
        <div className="space-y-1.5">
          <Label className="text-xs">Label name</Label>
          <Input
            value={String(editedAction.label_name ?? editedAction.label ?? "")}
            onChange={(e) => updateField("label_name", e.target.value)}
          />
        </div>
      )}

      {ft === "smart_folder" && (
        <div className="space-y-1.5">
          <Label className="text-xs">Destination folder</Label>
          <Input
            value={String(editedAction.folder ?? editedAction.destination ?? "")}
            onChange={(e) => updateField("folder", e.target.value)}
          />
        </div>
      )}

      {ft === "auto_reply" && (
        <div className="space-y-1.5">
          <Label className="text-xs">Reply body</Label>
          <Textarea
            rows={6}
            value={String(editedAction.body ?? "")}
            onChange={(e) => updateField("body", e.target.value)}
          />
        </div>
      )}

      {ft === "calendar_extraction" && (
        <div className="space-y-1.5">
          <Label className="text-xs">Event summary</Label>
          <Input
            value={String(editedAction.summary ?? editedAction.title ?? "")}
            onChange={(e) => updateField("summary", e.target.value)}
          />
        </div>
      )}

      {ft === "notifications" && (
        <div className="space-y-1.5">
          <Label className="text-xs">Notification message</Label>
          <Input
            value={String(editedAction.message ?? editedAction.body ?? "")}
            onChange={(e) => updateField("message", e.target.value)}
          />
        </div>
      )}

      {ft === "email_summary" && (
        <div className="space-y-1.5">
          <Label className="text-xs">Summary</Label>
          <Textarea
            rows={4}
            value={String(editedAction.summary ?? "")}
            onChange={(e) => updateField("summary", e.target.value)}
          />
        </div>
      )}

      {ft === "coupon_extraction" && (
        <>
          <div className="space-y-1.5">
            <Label className="text-xs">Coupon code</Label>
            <Input
              value={String(editedAction.code ?? "")}
              onChange={(e) => updateField("code", e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label className="text-xs">Description</Label>
            <Input
              value={String(editedAction.description ?? "")}
              onChange={(e) => updateField("description", e.target.value)}
            />
          </div>
        </>
      )}

      {ft === "contacts" && (
        <div className="space-y-1.5">
          <Label className="text-xs">Contact name</Label>
          <Input
            value={String(editedAction.contact_name ?? editedAction.name ?? "")}
            onChange={(e) => updateField("contact_name", e.target.value)}
          />
        </div>
      )}

      {/* Fallback: raw JSON for unknown types */}
      {!KNOWN_TYPES.includes(ft) && (
        <div className="space-y-1.5">
          <Label className="text-xs">Action data (JSON)</Label>
          <Textarea
            rows={4}
            value={JSON.stringify(editedAction, null, 2)}
            onChange={(e) => {
              try {
                onChangeAction(JSON.parse(e.target.value));
              } catch {
                // ignore invalid JSON while typing
              }
            }}
          />
        </div>
      )}

      {/* AI reasoning (read-only) */}
      {approval.ai_reasoning && (
        <div className="space-y-1">
          <Label className="text-xs">AI reasoning</Label>
          <p className="whitespace-pre-wrap text-xs italic text-muted-foreground">
            {approval.ai_reasoning}
          </p>
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <AppButton
          icon={<Save />}
          label="Save & Approve"
          variant="primary"
          loading={isSaving}
          disabled={isSaving}
          onClick={onSave}
        >
          Save &amp; Approve
        </AppButton>
        <AppButton
          icon={<X />}
          label="Cancel"
          variant="outline"
          disabled={isSaving}
          onClick={onCancel}
        >
          Cancel
        </AppButton>
      </div>
    </div>
  );
}
