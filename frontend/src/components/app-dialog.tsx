import type { ReactNode } from "react";
import { X, Save } from "lucide-react";

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

const SIZE_CLASSES = {
  default: "",
  wide: "sm:max-w-2xl",
} as const;

export interface AppDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  size?: keyof typeof SIZE_CLASSES;
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
  size = "default",
  preventClose,
  footer,
  onCancel,
  cancelLabel = "Cancel",
  primaryLabel,
  primaryIcon = <Save />,
  loading = false,
  primaryDisabled,
  form,
  onPrimaryClick,
  primaryVariant = "primary",
  contentClassName,
}: AppDialogProps) {
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
          "max-h-[90vh] overflow-y-auto",
          SIZE_CLASSES[size],
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
                    icon={primaryIcon}
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
