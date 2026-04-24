import { type ReactNode } from "react";
import { Settings } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
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
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-h-[85vh] overflow-y-auto sm:max-w-2xl"
        onPointerDownOutside={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && (
            <DialogDescription>{description}</DialogDescription>
          )}
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
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
