import { useState, useCallback } from "react";

export interface UseSearchableListOptions {
  /** Items per page (default: 20). */
  perPage?: number;
}

export interface UseSearchableListReturn {
  /** Current page number (1-based). */
  page: number;
  /** Set the current page. */
  setPage: (page: number) => void;
  /** Items per page. */
  perPage: number;
  /** Controlled value of the search input. */
  searchInput: string;
  /** Update the search input value. */
  setSearchInput: (value: string) => void;
  /** Committed search filter sent to the API. */
  searchFilter: string;
  /** Set the committed search filter directly (e.g. from badge click). */
  setSearchFilter: (value: string) => void;
  /** Commit the current searchInput as the active filter and reset to page 1. */
  handleSearch: () => void;
  /** Clear both input and filter, reset to page 1. */
  handleClearSearch: () => void;
}

/**
 * Shared state management for searchable, paginated lists.
 *
 * Provides page state, search input with enter-to-commit semantics,
 * and convenience handlers that every plugin page needs.
 */
export function useSearchableList(
  options: UseSearchableListOptions = {},
): UseSearchableListReturn {
  const perPage = options.perPage ?? 20;
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState("");
  const [searchFilter, setSearchFilter] = useState("");

  const handleSearch = useCallback(() => {
    setSearchFilter(searchInput.trim());
    setPage(1);
  }, [searchInput]);

  const handleClearSearch = useCallback(() => {
    setSearchInput("");
    setSearchFilter("");
    setPage(1);
  }, []);

  return {
    page,
    setPage,
    perPage,
    searchInput,
    setSearchInput,
    searchFilter,
    setSearchFilter,
    handleSearch,
    handleClearSearch,
  };
}
