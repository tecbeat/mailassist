import type { ReactNode } from "react";
import { X, Save, Trash2 } from "lucide-react";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { AppButton } from "@/components/app-button";
import { cn } from "@/lib/utils";

export interface AppDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  preventClose?: boolean;
  footer?: ReactNode;
  onCancel?: () => void;
  cancelLabel?: string;
  primaryLabel?: string;
  primaryIcon?: ReactNode;
  loading?: boolean;
  primaryDisabled?: boolean;
  form?: string;
  onPrimaryClick?: () => void;
  primaryVariant?: "primary" | "destructive";
  contentClassName?: string;
}

export function AppDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  preventClose,
  footer,
  onCancel,
  cancelLabel = "Cancel",
  primaryLabel,
  primaryIcon,
  loading = false,
  primaryDisabled,
  form,
  onPrimaryClick,
  primaryVariant = "primary",
  contentClassName,
}: AppDialogProps) {
  // Pick a sensible default icon based on variant when none is provided
  const resolvedIcon = primaryIcon ?? (primaryVariant === "destructive" ? <Trash2 /> : <Save />);

  const preventProps = preventClose
    ? {
        onPointerDownOutside: (e: Event) => e.preventDefault(),
        onInteractOutside: (e: Event) => e.preventDefault(),
        onEscapeKeyDown: (e: KeyboardEvent) => e.preventDefault(),
      }
    : {};

  const hasAutoFooter = Boolean(onCancel) || Boolean(primaryLabel);
  const showCancel = Boolean(onCancel);
  const showPrimary = Boolean(primaryLabel);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "w-[calc(100vw-2rem)] max-w-lg sm:max-w-xl md:max-w-2xl max-h-[90vh] overflow-y-auto",
          contentClassName,
        )}
        {...preventProps}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>

        {children}

        {footer !== undefined
          ? footer
          : hasAutoFooter && (
              <DialogFooter>
                {showCancel && (
                  <AppButton
                    icon={<X />}
                    label={cancelLabel}
                    onClick={onCancel}
                    disabled={loading}
                  >
                    {cancelLabel}
                  </AppButton>
                )}
                {showPrimary && (
                  <AppButton
                    icon={resolvedIcon}
                    label={primaryLabel!}
                    variant="primary"
                    color={primaryVariant === "destructive" ? "destructive" : "default"}
                    loading={loading}
                    disabled={loading || primaryDisabled}
                    type={form ? "submit" : "button"}
                    {...(form ? { form } : {})}
                    {...(onPrimaryClick ? { onClick: onPrimaryClick } : {})}
                  >
                    {primaryLabel}
                  </AppButton>
                )}
              </DialogFooter>
            )}
      </DialogContent>
    </Dialog>
  );
}
