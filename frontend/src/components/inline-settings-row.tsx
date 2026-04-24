import type { ReactNode } from "react";
import { Save } from "lucide-react";
import { AppButton } from "@/components/app-button";

// ---------------------------------------------------------------------------
// InlineSettingsRow – renders editable settings inside a resource list row,
// matching the visual style of account / provider rows (icon + title on
// row 1, details grid on row 2).
// ---------------------------------------------------------------------------

export interface SettingsField {
  /** Unique key for React list rendering */
  key: string;
  /** Small label displayed above the value */
  label: string;
  /** The form input element */
  input: ReactNode;
  /** Optional helper text below the input */
  hint?: string;
  /** Optional error message */
  error?: string;
}

interface InlineSettingsRowProps {
  /** Icon rendered to the left of the title (should be a Lucide icon element) */
  icon: ReactNode;
  /** Row title */
  title: string;
  /** Editable fields displayed in the details grid */
  fields: SettingsField[];
  /** Called when the user clicks Save */
  onSave: () => void;
  /** Whether a save mutation is in progress */
  saving?: boolean;
  /** Disable Save button (e.g. form is not dirty) */
  saveDisabled?: boolean;
}

export function InlineSettingsRow({
  icon,
  title,
  fields,
  onSave,
  saving = false,
  saveDisabled = false,
}: InlineSettingsRowProps) {
  return (
    <div className="px-6 py-4 space-y-3">
      {/* Row 1: Icon + title + save button */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <span className="h-4 w-4 shrink-0 text-muted-foreground [&>svg]:h-4 [&>svg]:w-4">
            {icon}
          </span>
          <span className="font-medium text-sm truncate">{title}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <AppButton
            icon={<Save />}
            label="Save settings"
            size="sm"
            loading={saving}
            disabled={saveDisabled || saving}
            onClick={onSave}
          >
            Save
          </AppButton>
        </div>
      </div>

      {/* Row 2: Details grid with editable fields */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-3 text-sm pl-7">
        {fields.map((field) => (
          <div key={field.key} className="space-y-1">
            <span className="text-muted-foreground text-xs">{field.label}</span>
            {field.input}
            {field.error && (
              <p className="text-xs text-destructive">{field.error}</p>
            )}
            {field.hint && (
              <p className="text-[10px] text-muted-foreground">{field.hint}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
