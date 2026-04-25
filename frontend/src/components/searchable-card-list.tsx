import { type ReactNode } from "react";
import { Search, X } from "lucide-react";

import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { FilterPopover } from "@/components/filter-popover";
import { ListSkeleton } from "@/components/list-skeleton";
import { QueryError } from "@/components/query-error";
import { Pagination } from "@/components/pagination";

import type { UseSearchableListReturn } from "@/hooks/use-searchable-list";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SearchableCardListProps<T> {
  /** Return value from `useSearchableList()`. */
  list: UseSearchableListReturn;

  // -- Data ------------------------------------------------------------------

  /** Items to render. */
  items: T[];
  /** Total number of pages. */
  totalPages: number;
  /** Total item count (for pagination label). */
  totalCount: number;

  // -- Query state -----------------------------------------------------------

  /** Whether the query is in an error state. */
  isError: boolean;
  /** Whether the initial load is in progress. */
  isLoading: boolean;
  /** Whether a background refetch is in progress (used by SortToggle). */
  isFetching?: boolean;
  /** Error message shown in the error state. */
  errorMessage?: string;
  /** Retry callback for the error state. */
  onRetry?: () => void;

  // -- Search ----------------------------------------------------------------

  /** Placeholder text for the search input. */
  searchPlaceholder?: string;
  /**
   * Search mode:
   * - `"enter"` (default): user commits search by pressing Enter
   * - `"button"`: like `"enter"`, but also shows an explicit Search button
   *   inside the input (useful when the search is not obvious)
   * - `"disabled"`: search input is rendered but disabled
   * - `"none"`: search input is completely hidden
   */
  searchMode?: "enter" | "button" | "disabled" | "none";

  // -- Filter ----------------------------------------------------------------

  /** Content rendered inside the FilterPopover. */
  filterContent?: ReactNode;
  /** Whether any filters are active (controls FilterPopover badge). */
  hasActiveFilters?: boolean;
  /** Number of active filters (optional, for count badge). */
  activeFilterCount?: number;
  /** When true the FilterPopover is hidden entirely. */
  hideFilter?: boolean;

  // -- Rendering -------------------------------------------------------------

  /** Render a single item. */
  renderItem: (item: T, index: number) => ReactNode;
  /** Icon shown in the empty state. */
  emptyIcon?: ReactNode;
  /** Message shown in the empty state. */
  emptyMessage?: string;
  /** Completely custom empty state (overrides emptyIcon + emptyMessage). */
  emptyState?: ReactNode;
  /** Custom skeleton (overrides ListSkeleton). */
  skeleton?: ReactNode;
  /** Layout mode: vertical list (default) or responsive grid. */
  layout?: "list" | "grid";
  /** Custom class name for the item container (e.g. grid columns). */
  itemContainerClassName?: string;
  /** Noun label for pagination (default: "total"). */
  paginationNoun?: string;
  /** Extra content rendered above the search bar (e.g. tabs). */
  headerExtra?: ReactNode;
  /** Extra content rendered between the search/filter bar and the list (e.g. select-all row, bulk actions). */
  toolbarExtra?: ReactNode;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Reusable wrapper for the searchable, filterable, paginated card list
 * pattern shared across all plugin pages.
 *
 * Encapsulates:
 * - Search bar with enter-to-commit, clear button
 * - FilterPopover slot
 * - Three-state conditional rendering (error / loading / empty / data)
 * - Pagination
 *
 * **Does not** render the outer `<Card>` / `<CardHeader>` — that stays
 * in the page component so each page retains full control over its
 * card title, description, and any extra sections.
 */
export function SearchableCardList<T>({
  list,
  items,
  totalPages,
  totalCount,
  isError,
  isLoading,
  errorMessage = "Failed to load data.",
  onRetry,
  searchPlaceholder = "Search...",
  searchMode = "enter",
  filterContent,
  hasActiveFilters = false,
  activeFilterCount,
  hideFilter = false,
  renderItem,
  emptyIcon,
  emptyMessage = "No items found.",
  emptyState,
  skeleton,
  layout = "list",
  itemContainerClassName,
  paginationNoun,
  headerExtra,
  toolbarExtra,
}: SearchableCardListProps<T>) {
  const containerClass =
    itemContainerClassName ??
    (layout === "grid"
      ? "grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      : "space-y-3");

  return (
    <>
      {/* Optional header extra (e.g. tabs) */}
      {headerExtra}

      {/* Search + Filter bar */}
      {searchMode !== "none" && (
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder={searchPlaceholder}
              value={searchMode === "disabled" ? "" : list.searchInput}
              onChange={
                searchMode === "disabled"
                  ? undefined
                  : (e) => list.setSearchInput(e.target.value)
              }
              onKeyDown={
                searchMode === "disabled"
                  ? undefined
                  : (e) => {
                      if (e.key === "Enter") list.handleSearch();
                    }
              }
              disabled={searchMode === "disabled"}
              className={`pl-9 ${searchMode === "button" ? "pr-16" : ""}`}
            />
            {searchMode === "button" ? (
              <div className="absolute right-1 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
                {list.searchInput && (
                  <AppButton
                    icon={<X />}
                    label="Clear search"
                    variant="ghost"
                    className="h-7 w-7"
                    onClick={list.handleClearSearch}
                  />
                )}
                <AppButton
                  icon={<Search />}
                  label="Search"
                  variant="ghost"
                  className="h-7 w-7"
                  onClick={list.handleSearch}
                />
              </div>
            ) : (
              searchMode !== "disabled" && list.searchInput && (
                <AppButton
                  icon={<X />}
                  label="Clear search"
                  variant="ghost"
                  className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2"
                  onClick={list.handleClearSearch}
                />
              )
            )}
          </div>
          {!hideFilter && filterContent && (
            <FilterPopover
              hasActiveFilters={hasActiveFilters}
              activeFilterCount={activeFilterCount}
            >
              {filterContent}
            </FilterPopover>
          )}
        </div>
      )}

      {/* Optional toolbar extra (e.g. select-all row, bulk actions) */}
      {toolbarExtra}

      {/* List: error / loading / empty / data */}
      {isError ? (
        <QueryError message={errorMessage} onRetry={onRetry} />
      ) : isLoading ? (
        skeleton ?? <ListSkeleton />
      ) : items.length === 0 ? (
        emptyState ?? (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            {emptyIcon}
            <p className="text-sm text-muted-foreground">{emptyMessage}</p>
          </div>
        )
      ) : (
        <div className={containerClass}>
          {items.map((item, index) => renderItem(item, index))}
        </div>
      )}

      {/* Pagination */}
      <Pagination
        page={list.page}
        totalPages={totalPages}
        totalCount={totalCount}
        onPageChange={list.setPage}
        noun={paginationNoun}
        compact
      />
    </>
  );
}
