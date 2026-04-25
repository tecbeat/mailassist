import { type ReactNode } from "react";
import { SlidersHorizontal } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { AppButton } from "@/components/app-button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

interface FilterPopoverProps {
  /** Whether any filters are currently active. Shows a visual indicator. */
  hasActiveFilters?: boolean;
  /** Number of active filters. When > 0, shown as a count badge. */
  activeFilterCount?: number;
  /** Content rendered inside the popover (filter controls). */
  children: ReactNode;
}

/**
 * Reusable filter button with popover.
 *
 * Place this next to the search input. The trigger button shows a label
 * ("Filters") with an optional count badge so users can immediately see
 * that filters are applied and how many.
 */
export function FilterPopover({
  hasActiveFilters = false,
  activeFilterCount,
  children,
}: FilterPopoverProps) {
  const showBadge =
    hasActiveFilters || (activeFilterCount != null && activeFilterCount > 0);
  const count = activeFilterCount ?? (hasActiveFilters ? 1 : 0);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <AppButton
          icon={<SlidersHorizontal />}
          label="Filters"
          className="h-9 shrink-0"
        >
          Filters
          {showBadge && (
            <Badge
              variant="secondary"
              className="ml-0.5 h-5 min-w-5 justify-center rounded-full font-semibold"
            >
              {count}
            </Badge>
          )}
        </AppButton>
      </PopoverTrigger>
      <PopoverContent className="w-72 space-y-4" align="end">
        <p className="text-xs font-medium text-muted-foreground">
          Filter & Sort
        </p>
        {children}
      </PopoverContent>
    </Popover>
  );
}
