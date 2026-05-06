import { useState, useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/ui/toast";

export interface UseDeleteHandlerOptions<T> {
  /** Execute the delete. Called with the item to delete. */
  onDelete: (item: T) => Promise<unknown>;
  /** Query keys to invalidate on success. */
  queryKeys: readonly (readonly unknown[])[];
  /** Whether the mutation is currently pending. */
  isPending: boolean;
  /** Toast messages. */
  successTitle: string;
  successDescription: string;
  errorTitle: string;
  errorDescription: string;
}

export interface UseDeleteHandlerReturn<T> {
  /** The item currently targeted for deletion (shown in confirm dialog). */
  deleteTarget: T | null;
  /** Set an item as the delete target (opens confirm dialog). */
  setDeleteTarget: (item: T | null) => void;
  /** Execute the deletion of the current target. */
  handleDelete: () => Promise<void>;
  /** Whether the delete mutation is in progress. */
  isPending: boolean;
}

/**
 * Shared delete confirmation + mutation logic for plugin list pages.
 *
 * Manages the delete target state, executes the mutation, invalidates
 * queries, and shows success/error toasts.
 */
export function useDeleteHandler<T>(
  options: UseDeleteHandlerOptions<T>,
): UseDeleteHandlerReturn<T> {
  const [deleteTarget, setDeleteTarget] = useState<T | null>(null);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const handleDelete = useCallback(async () => {
    if (!deleteTarget) return;
    try {
      await options.onDelete(deleteTarget);
      for (const key of options.queryKeys) {
        queryClient.invalidateQueries({ queryKey: key });
      }
      setDeleteTarget(null);
      toast({ title: options.successTitle, description: options.successDescription });
    } catch {
      toast({
        title: options.errorTitle,
        description: options.errorDescription,
        variant: "destructive",
      });
    }
  }, [deleteTarget, options, queryClient, toast]);

  return {
    deleteTarget,
    setDeleteTarget,
    handleDelete,
    isPending: options.isPending,
  };
}
