import { RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

import { AppButton } from "@/components/app-button";
import { SortToggle } from "@/components/sort-toggle";
import { Label } from "@/components/ui/label";

interface SortFilterContentProps {
  /** Current sort order passed to SortToggle. */
  sortOrder: "newest" | "oldest";
  /** Called when the user toggles the sort order. */
  onSortChange: (order: "newest" | "oldest") => void;
  /** Whether a background refetch is in progress (shows spinner in SortToggle). */
  isFetching?: boolean;
  /** When true, the "Clear filters" button is shown. */
  hasActiveFilters: boolean;
  /** Called when the user clicks "Clear filters". */
  onClearFilters: () => void;
  /**
   * Optional extra filter controls rendered above the sort toggle.
   * Each child should be a self-contained labelled filter block.
   */
  children?: ReactNode;
}

/**
 * Shared filter-panel content used by all plugin list pages.
 *
 * Renders optional extra filter controls, a labelled SortToggle, and a
 * conditional "Clear filters" button — eliminating the copy-paste pattern
 * that existed across labeling, auto-reply, newsletters, calendar, coupons,
 * and summaries pages.
 */
export function SortFilterContent({
  sortOrder,
  onSortChange,
  isFetching,
  hasActiveFilters,
  onClearFilters,
  children,
}: SortFilterContentProps) {
  return (
    <div className="space-y-3">
      {children}
      <div className="space-y-1.5">
        <Label className="text-xs">Sort Order</Label>
        <SortToggle
          sortOrder={sortOrder}
          onToggle={onSortChange}
          isFetching={isFetching}
          variant="inline"
        />
      </div>
      {hasActiveFilters && (
        <AppButton
          icon={<RotateCcw />}
          label="Clear filters"
          variant="ghost"
          className="h-7 w-full text-xs"
          onClick={onClearFilters}
        >
          Clear filters
        </AppButton>
      )}
    </div>
  );
}
