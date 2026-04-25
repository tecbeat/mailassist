import { ChevronLeft, ChevronRight } from "lucide-react";

import { AppButton } from "@/components/app-button";
import { cn } from "@/lib/utils";

interface PaginationProps {
  page: number;
  totalPages: number;
  totalCount: number;
  onPageChange: (page: number) => void;
  /** Label appended after the count (default: "total"). */
  noun?: string;
  /** Compact mode: icon-only buttons, smaller text. Ideal for card contexts. */
  compact?: boolean;
  className?: string;
}

export function Pagination({
  page,
  totalPages,
  totalCount,
  onPageChange,
  noun = "total",
  compact = false,
  className,
}: PaginationProps) {
  if (totalPages <= 1) return null;

  if (compact) {
    return (
      <div className={cn("flex items-center justify-between", className)}>
        <span className="text-xs text-muted-foreground">
          Page {page} of {totalPages}
        </span>
        <div className="flex items-center gap-1">
          <AppButton
            icon={<ChevronLeft />}
            label="Previous page"
            variant="outline"
            size="sm"
            className="h-6 w-6"
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page <= 1}
          />
          <AppButton
            icon={<ChevronRight />}
            label="Next page"
            variant="outline"
            size="sm"
            className="h-6 w-6"
            onClick={() => onPageChange(Math.min(totalPages, page + 1))}
            disabled={page >= totalPages}
          />
        </div>
      </div>
    );
  }

  return (
    <div className={cn("flex items-center justify-between", className)}>
      <p className="text-sm text-muted-foreground">
        Page {page} of {totalPages} ({totalCount} {noun})
      </p>
      <div className="flex gap-2">
        <AppButton
          icon={<ChevronLeft />}
          label="Previous page"
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1}
        >
          Previous
        </AppButton>
        <AppButton
          icon={<ChevronRight />}
          label="Next page"
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages}
        >
          Next
        </AppButton>
      </div>
    </div>
  );
}
