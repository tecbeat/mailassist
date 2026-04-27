import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  Tags,
  Trash2,
  RotateCcw,
  X,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useListAppliedLabelsApiLabelsGet,
  useDeleteAppliedLabelApiLabelsLabelIdDelete,
  getListAppliedLabelsApiLabelsGetQueryKey,
  useGetLabelSummaryApiLabelsSummaryGet,
} from "@/services/api/labels/labels";

import { AppButton } from "@/components/app-button";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/layout/page-header";
import { SortToggle } from "@/components/sort-toggle";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import { SearchableCardList } from "@/components/searchable-card-list";
import { FilterListItem } from "@/components/filter-list-item";
import { useSearchableList } from "@/hooks/use-searchable-list";
import { Label } from "@/components/ui/label";
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
  usePageTitle("Labels");
  const list = useSearchableList();
  const [sortOrder, setSortOrder] = useState<string>("newest");
  const [deleteTarget, setDeleteTarget] = useState<AppliedLabelResponse | null>(null);
  const { toast } = useToast();
  const queryClient = useQueryClient();

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

  const hasActiveFilters = sortOrder !== "newest";

  async function handleDelete(id: string) {
    try {
      await deleteMutation.mutateAsync({ labelId: id });
      queryClient.invalidateQueries({
        queryKey: getListAppliedLabelsApiLabelsGetQueryKey(params),
      });
      setDeleteTarget(null);
      toast({ title: "Label record removed", description: "The label assignment has been deleted." });
    } catch {
      toast({ title: "Failed to remove label record", description: "Could not delete the label record. Please try again.", variant: "destructive" });
    }
  }

  function handleLabelClick(label: string) {
    list.setSearchInput(label);
    list.setSearchFilter(label);
    list.setPage(1);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Auto-Labeling"
        description="Labels assigned to emails by the AI labeling plugin."
      />

      {/* Label Summary */}
      {summaryItems.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Label Summary</CardTitle>
            <CardDescription>
              Click a label to filter the list below.
            </CardDescription>
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
      )}

      {/* Applied Labels List */}
      <Card>
        <CardHeader>
          <CardTitle>Applied Labels</CardTitle>
          <CardDescription>
            Labels will appear here as they are assigned to your incoming emails.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList
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
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Sort Order</Label>
                  <SortToggle
                    sortOrder={sortOrder}
                    onToggle={(o) => { setSortOrder(o); list.setPage(1); }}
                    isFetching={labelsQuery.isFetching}
                    variant="inline"
                  />
                </div>
                {hasActiveFilters && (
                  <AppButton
                    icon={<RotateCcw />}
                    label="Clear filters"
                    variant="ghost"
                    className="h-7 w-full text-xs"
                    onClick={() => {
                      setSortOrder("newest");
                      list.setPage(1);
                    }}
                  >
                    Clear filters
                  </AppButton>
                )}
              </div>
            }
            emptyIcon={<Tags className="mb-3 h-10 w-10 text-muted-foreground" />}
            emptyMessage="No labels applied yet. Labels will appear here as emails are processed."
            renderItem={(item: AppliedLabelResponse) => (
              <FilterListItem
                key={item.id}
                icon={<Tags />}
                title={<Badge variant="default">{item.label}</Badge>}
                badges={
                  item.is_new_label ? (
                    <Badge variant="secondary" className="shrink-0">
                      New
                    </Badge>
                  ) : undefined
                }
                subtitle={
                  <>
                    {item.mail_subject && (
                      <p className="mt-1 truncate text-sm text-muted-foreground">
                        {item.mail_subject}
                      </p>
                    )}
                    {item.mail_from && (
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {item.mail_from}
                      </p>
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
          />
        </CardContent>
      </Card>

      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete Label Record"
        description={
          <>
            Are you sure you want to remove the label{" "}
            <span className="font-medium">{deleteTarget?.label}</span>
            {deleteTarget?.mail_subject ? ` from "${deleteTarget.mail_subject}"` : ""}?
            This action cannot be undone.
          </>
        }
        onConfirm={() => {
          if (deleteTarget) handleDelete(deleteTarget.id);
        }}
        isPending={deleteMutation.isPending}
      />
    </div>
  );
}
