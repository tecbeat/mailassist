import type { ReactNode } from "react";

import { AppDialog } from "@/components/app-dialog";

interface DeleteConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: ReactNode;
  onConfirm: () => void;
  isPending?: boolean;
  confirmLabel?: string;
  confirmVariant?: "destructive" | "default";
}

export function DeleteConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  onConfirm,
  isPending = false,
  confirmLabel = "Delete",
  confirmVariant = "destructive",
}: DeleteConfirmDialogProps) {
  return (
    <AppDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      loading={isPending}
      primaryLabel={confirmLabel}
      primaryVariant={confirmVariant === "destructive" ? "destructive" : "primary"}
      onPrimaryClick={onConfirm}
      onCancel={() => onOpenChange(false)}
    />
  );
}
