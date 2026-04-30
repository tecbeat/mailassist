import { RefreshCw } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { AppButton } from "@/components/app-button";

interface QueryErrorProps {
  /** Error message to display. */
  message?: string;
  /** Callback to retry the failed query. */
  onRetry?: () => void;
}

/**
 * Generic error state for failed React Query queries.
 *
 * Shows a user-friendly error card with an optional retry button.
 * Use this in place of skeleton loaders when `isError` is true.
 */
export function QueryError({
  message = "Failed to load data. Please try again.",
  onRetry,
}: QueryErrorProps) {
  return (
    <Card className="border-destructive/50 bg-destructive/5">
      <CardContent className="flex flex-col items-center justify-center gap-3 py-8 text-center">
        <p className="text-sm text-destructive select-text cursor-text">{message}</p>
        {onRetry && (
          <AppButton icon={<RefreshCw />} label="Try again" onClick={onRetry}>
            Try again
          </AppButton>
        )}
      </CardContent>
    </Card>
  );
}
