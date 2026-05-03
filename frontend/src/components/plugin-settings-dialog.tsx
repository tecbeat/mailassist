import { type ReactNode } from "react";
import { Settings } from "lucide-react";

import { AppDialog } from "@/components/app-dialog";
import { AppButton } from "@/components/app-button";

interface PluginSettingsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
}

/**
 * Reusable dialog shell for plugin-specific settings.
 *
 * Opened via the settings gear icon rendered by PluginSettingsButton.
 */
export function PluginSettingsDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
}: PluginSettingsDialogProps) {
  return (
    <AppDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      size="wide"
      preventClose
      contentClassName="max-h-[85vh]"
    >
      {children}
    </AppDialog>
  );
}

interface PluginSettingsButtonProps {
  onClick: () => void;
}

/**
 * Gear icon button placed in PageHeader actions to open the settings dialog.
 */
export function PluginSettingsButton({ onClick }: PluginSettingsButtonProps) {
  return (
    <AppButton icon={<Settings />} label="Plugin Settings" variant="outline" onClick={onClick} />
  );
}
