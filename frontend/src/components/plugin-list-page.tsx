import type { ReactNode } from "react";
import { PageHeader } from "@/components/layout/page-header";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import { SearchableCardList } from "@/components/searchable-card-list";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import type { UseSearchableListReturn } from "@/hooks/use-searchable-list";
import { usePageTitle } from "@/hooks/use-page-title";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PluginListPageProps<TItem> {
  /** Browser tab title. */
  pageTitle: string;
  /** Page header title and description. */
  header: { title: string; description: string };
  /** Card header title and description. */
  card: { title: string; description: string };
  /** Searchable list hook return value. */
  list: UseSearchableListReturn;
  /** The list items to display. */
  items: TItem[];
  /** Total number of pages. */
  totalPages: number;
  /** Total item count. */
  totalCount: number;
  /** Query state flags. */
  isError: boolean;
  isLoading: boolean;
  isFetching: boolean;
  /** Error message shown when query fails. */
  errorMessage: string;
  /** Retry callback. */
  onRetry: () => void;
  /** Search input placeholder. */
  searchPlaceholder: string;
  /** Whether any filters are active. */
  hasActiveFilters: boolean;
  /** Filter/sort popover content. */
  filterContent: ReactNode;
  /** Icon shown in empty state. */
  emptyIcon: ReactNode;
  /** Message shown in empty state. */
  emptyMessage: string;
  /** Render a single list item. */
  renderItem: (item: TItem) => ReactNode;
  /** Delete confirm dialog props. Omit to hide dialog. */
  deleteDialog?: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    title: string;
    description: ReactNode;
    onConfirm: () => void;
    isPending: boolean;
  };
  /** Extra content rendered before the main card. */
  beforeCard?: ReactNode;
  /** Extra content rendered after the dialog. */
  afterContent?: ReactNode;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Generic layout wrapper for plugin list pages.
 *
 * Provides the shared structure: PageHeader -> optional beforeCard ->
 * Card with SearchableCardList -> optional DeleteConfirmDialog -> afterContent.
 */
export function PluginListPage<TItem>({
  pageTitle,
  header,
  card,
  list,
  items,
  totalPages,
  totalCount,
  isError,
  isLoading,
  isFetching,
  errorMessage,
  onRetry,
  searchPlaceholder,
  hasActiveFilters,
  filterContent,
  emptyIcon,
  emptyMessage,
  renderItem,
  deleteDialog,
  beforeCard,
  afterContent,
}: PluginListPageProps<TItem>) {
  usePageTitle(pageTitle);

  return (
    <div className="space-y-6">
      <PageHeader title={header.title} description={header.description} />

      {beforeCard}

      <Card>
        <CardHeader>
          <CardTitle>{card.title}</CardTitle>
          <CardDescription>{card.description}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList
            list={list}
            items={items}
            totalPages={totalPages}
            totalCount={totalCount}
            isError={isError}
            isLoading={isLoading}
            isFetching={isFetching}
            errorMessage={errorMessage}
            onRetry={onRetry}
            searchPlaceholder={searchPlaceholder}
            hasActiveFilters={hasActiveFilters}
            filterContent={filterContent}
            emptyIcon={emptyIcon}
            emptyMessage={emptyMessage}
            renderItem={renderItem}
          />
        </CardContent>
      </Card>

      {deleteDialog && (
        <DeleteConfirmDialog
          open={deleteDialog.open}
          onOpenChange={deleteDialog.onOpenChange}
          title={deleteDialog.title}
          description={deleteDialog.description}
          onConfirm={deleteDialog.onConfirm}
          isPending={deleteDialog.isPending}
        />
      )}

      {afterContent}
    </div>
  );
}
