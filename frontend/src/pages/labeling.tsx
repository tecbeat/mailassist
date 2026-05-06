import { useState } from "react";
import {
  Tags,
  Trash2,
  X,
} from "lucide-react";
import {
  useListAppliedLabelsApiLabelsGet,
  useDeleteAppliedLabelApiLabelsLabelIdDelete,
  getListAppliedLabelsApiLabelsGetQueryKey,
  useGetLabelSummaryApiLabelsSummaryGet,
} from "@/services/api/labels/labels";

import { AppButton } from "@/components/app-button";
import { PluginListPage } from "@/components/plugin-list-page";
import { SortFilterContent } from "@/components/sort-filter-content";
import { FilterListItem } from "@/components/filter-list-item";
import { useSearchableList } from "@/hooks/use-searchable-list";
import { useDeleteHandler } from "@/hooks/use-delete-handler";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { formatDate, unwrapResponse } from "@/lib/utils";
import type {
  AppliedLabelResponse,
  AppliedLabelListResponse,
  ListAppliedLabelsApiLabelsGetSort,
  LabelSummaryListResponse,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function LabelingPage() {
  const list = useSearchableList();
  const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");

  const params = {
    page: list.page,
    per_page: list.perPage,
    sort: sortOrder as ListAppliedLabelsApiLabelsGetSort,
    ...(list.searchFilter ? { label: list.searchFilter } : {}),
  };

  const labelsQuery = useListAppliedLabelsApiLabelsGet(params);
  const listData = unwrapResponse<AppliedLabelListResponse>(labelsQuery.data);

  const summaryQuery = useGetLabelSummaryApiLabelsSummaryGet();
  const summaryData = unwrapResponse<LabelSummaryListResponse>(summaryQuery.data);
  const summaryItems = summaryData?.items ?? [];

  const items = listData?.items ?? [];
  const totalPages = listData?.pages ?? 1;

  const deleteMutation = useDeleteAppliedLabelApiLabelsLabelIdDelete();
  const { deleteTarget, setDeleteTarget, handleDelete, isPending } =
    useDeleteHandler<AppliedLabelResponse>({
      onDelete: (item) => deleteMutation.mutateAsync({ labelId: item.id }),
      queryKeys: [getListAppliedLabelsApiLabelsGetQueryKey()],
      isPending: deleteMutation.isPending,
      successTitle: "Label record removed",
      successDescription: "The label assignment has been deleted.",
      errorTitle: "Failed to remove label record",
      errorDescription: "Could not delete the label record. Please try again.",
    });

  const hasActiveFilters = sortOrder !== "newest";

  function handleLabelClick(label: string) {
    list.setSearchInput(label);
    list.setSearchFilter(label);
    list.setPage(1);
  }

  return (
    <PluginListPage<AppliedLabelResponse>
      pageTitle="Labels"
      header={{
        title: "Auto-Labeling",
        description: "Labels assigned to emails by the AI labeling plugin.",
      }}
      card={{
        title: "Applied Labels",
        description: "Labels will appear here as they are assigned to your incoming emails.",
      }}
      list={list}
      items={items}
      totalPages={totalPages}
      totalCount={listData?.total ?? 0}
      isError={labelsQuery.isError}
      isLoading={labelsQuery.isLoading}
      isFetching={labelsQuery.isFetching}
      errorMessage="Failed to load labels."
      onRetry={() => labelsQuery.refetch()}
      searchPlaceholder="Search by label..."
      hasActiveFilters={hasActiveFilters}
      filterContent={
        <SortFilterContent
          sortOrder={sortOrder}
          onSortChange={(o) => { setSortOrder(o); list.setPage(1); }}
          isFetching={labelsQuery.isFetching}
          hasActiveFilters={hasActiveFilters}
          onClearFilters={() => { setSortOrder("newest"); list.setPage(1); }}
        />
      }
      emptyIcon={<Tags className="mb-3 h-10 w-10 text-muted-foreground" />}
      emptyMessage="No labels applied yet. Labels will appear here as emails are processed."
      beforeCard={
        summaryItems.length > 0 ? (
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Label Summary</CardTitle>
              <CardDescription>Click a label to filter the list below.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {summaryItems.map((s) => (
                  <Badge
                    key={s.label}
                    variant={list.searchFilter === s.label ? "default" : "secondary"}
                    className="cursor-pointer select-none transition-colors"
                    onClick={() => handleLabelClick(s.label)}
                  >
                    {s.label}
                    <span className="ml-1 opacity-60">{s.count}</span>
                  </Badge>
                ))}
                {list.searchFilter && (
                  <AppButton
                    icon={<X />}
                    label="Clear filter"
                    variant="ghost"
                    className="h-6 text-xs"
                    onClick={list.handleClearSearch}
                  >
                    Clear filter
                  </AppButton>
                )}
              </div>
            </CardContent>
          </Card>
        ) : undefined
      }
      renderItem={(item) => (
        <FilterListItem
          key={item.id}
          icon={<Tags />}
          title={<Badge variant="default">{item.label}</Badge>}
          badges={
            item.is_new_label ? (
              <Badge variant="secondary" className="shrink-0">New</Badge>
            ) : undefined
          }
          subtitle={
            <>
              {item.mail_subject && (
                <p className="mt-1 truncate text-sm text-muted-foreground">{item.mail_subject}</p>
              )}
              {item.mail_from && (
                <p className="mt-0.5 truncate text-xs text-muted-foreground">{item.mail_from}</p>
              )}
            </>
          }
          date={formatDate(item.created_at)}
          actions={
            <AppButton
              icon={<Trash2 />}
              label="Delete"
              variant="ghost"
              color="destructive"
              onClick={() => setDeleteTarget(item)}
            />
          }
        />
      )}
      deleteDialog={{
        open: !!deleteTarget,
        onOpenChange: (open) => { if (!open) setDeleteTarget(null); },
        title: "Delete Label Record",
        description: (
          <>
            Are you sure you want to remove the label{" "}
            <span className="font-medium">{deleteTarget?.label}</span>
            {deleteTarget?.mail_subject ? ` from "${deleteTarget.mail_subject}"` : ""}?
            This action cannot be undone.
          </>
        ),
        onConfirm: handleDelete,
        isPending,
      }}
    />
  );
}
