import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  RotateCcw,
  Trash2,
} from "lucide-react";
import {
  useListSummariesApiSummariesGet,
  useDeleteSummaryApiSummariesSummaryIdDelete,
  getListSummariesApiSummariesGetQueryKey,
} from "@/services/api/summaries/summaries";
import { useQueryClient } from "@tanstack/react-query";

import { SpamButton } from "@/components/spam-button";
import { CreateContactButton } from "@/components/create-contact-button";
import { PageHeader } from "@/components/layout/page-header";
import { SortToggle } from "@/components/sort-toggle";
import { ListSkeleton } from "@/components/list-skeleton";
import { SearchableCardList } from "@/components/searchable-card-list";
import { FilterListItem } from "@/components/filter-list-item";
import { useSearchableList } from "@/hooks/use-searchable-list";
import {
  PluginSettingsDialog,
  PluginSettingsButton,
} from "@/components/plugin-settings-dialog";
import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/ui/toast";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { formatDate, unwrapResponse } from "@/lib/utils";
import { Label } from "@/components/ui/label";
import type {
  EmailSummaryResponse,
  EmailSummaryListResponse,
  ListSummariesApiSummariesGetSort,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function urgencyBadgeVariant(
  urgency: string,
): "default" | "secondary" | "destructive" {
  if (urgency === "critical") return "destructive";
  if (urgency === "high") return "default";
  return "secondary";
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function SummariesPage() {
  usePageTitle("Summaries");
  const list = useSearchableList({ perPage: 10 });
  const [urgencyFilter, setUrgencyFilter] = useState<string>("all");
  const [actionFilter, setActionFilter] = useState<string>("all");
  const [sortOrder, setSortOrder] = useState<string>("newest");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<EmailSummaryResponse | null>(null);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const params = {
    page: list.page,
    per_page: list.perPage,
    sort: sortOrder as ListSummariesApiSummariesGetSort,
    ...(urgencyFilter !== "all" ? { urgency: urgencyFilter } : {}),
    ...(actionFilter === "yes" ? { action_required: true } : {}),
    ...(actionFilter === "no" ? { action_required: false } : {}),
    ...(list.searchFilter ? { search: list.searchFilter } : {}),
  };

  const summariesQuery = useListSummariesApiSummariesGet(params);
  const listData = unwrapResponse<EmailSummaryListResponse>(summariesQuery.data);

  const items = listData?.items ?? [];
  const totalPages = listData?.pages ?? 1;

  const deleteMutation = useDeleteSummaryApiSummariesSummaryIdDelete();

  const hasActiveFilters = urgencyFilter !== "all" || actionFilter !== "all" || sortOrder !== "newest" || !!list.searchFilter;

  function toggleExpand(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  async function handleDelete(id: string) {
    try {
      await deleteMutation.mutateAsync({ summaryId: id });
      queryClient.invalidateQueries({
        queryKey: getListSummariesApiSummariesGetQueryKey(params),
      });
      setDeleteTarget(null);
      toast({ title: "Summary deleted", description: "The email summary has been removed." });
    } catch {
      toast({ title: "Failed to delete summary", description: "Could not delete the summary. Please try again.", variant: "destructive" });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Email Summaries"
        description="AI-generated email summaries."
        actions={
          <div className="flex items-center gap-2">
            <PluginSettingsButton onClick={() => setSettingsOpen(true)} />
          </div>
        }
      />

      {/* Summary List Card */}
      <Card>
        <CardHeader>
          <CardTitle>Summaries</CardTitle>
          <CardDescription>
            AI-generated summaries of your incoming emails with urgency levels
            and action indicators.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList
            list={list}
            items={items}
            totalPages={totalPages}
            totalCount={listData?.total ?? 0}
            isError={summariesQuery.isError}
            isLoading={summariesQuery.isLoading}
            isFetching={summariesQuery.isFetching}
            errorMessage="Failed to load summaries."
            onRetry={() => summariesQuery.refetch()}
            searchMode="enter"
            searchPlaceholder="Search summaries..."
            hasActiveFilters={hasActiveFilters}
            filterContent={
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Urgency</Label>
                  <Select
                    value={urgencyFilter}
                    onValueChange={(v) => {
                      setUrgencyFilter(v);
                      list.setPage(1);
                    }}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="All urgencies" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All urgencies</SelectItem>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                      <SelectItem value="critical">Critical</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Action Required</Label>
                  <Select
                    value={actionFilter}
                    onValueChange={(v) => {
                      setActionFilter(v);
                      list.setPage(1);
                    }}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="All" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All</SelectItem>
                      <SelectItem value="yes">Action required</SelectItem>
                      <SelectItem value="no">No action</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Sort Order</Label>
                   <SortToggle
                    sortOrder={sortOrder}
                    onToggle={(o) => { setSortOrder(o); list.setPage(1); }}
                    isFetching={summariesQuery.isFetching}
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
                      setUrgencyFilter("all");
                      setActionFilter("all");
                      setSortOrder("newest");
                      list.setPage(1);
                    }}
                  >
                    Clear filters
                  </AppButton>
                )}
              </div>
            }
            skeleton={<ListSkeleton lines={["w-1/3", "w-full"]} />}
            emptyMessage="No email summaries found."
            renderItem={(summary: EmailSummaryResponse) => {
              const expanded = expandedId === summary.id;
              return (
                <FilterListItem
                  key={summary.id}
                  title={summary.mail_subject ?? `UID ${summary.mail_uid}`}
                  badges={
                    <>
                      {summary.action_required && (
                        <Badge variant="default" className="shrink-0">
                          Action
                        </Badge>
                      )}
                      <Badge variant={urgencyBadgeVariant(summary.urgency)}>
                        {summary.urgency}
                      </Badge>
                    </>
                  }
                  subtitle={
                    summary.mail_from ? (
                      <p className="truncate text-xs text-muted-foreground">
                        {summary.mail_from}
                      </p>
                    ) : undefined
                  }
                  preview={summary.summary}
                  previewLines={2}
                  expandable
                  expanded={expanded}
                  onToggleExpand={() => toggleExpand(summary.id)}
                  expandedContent={
                    <>
                      <div>
                        <Label className="text-xs text-muted-foreground">
                          Full Summary
                        </Label>
                        <p className="mt-1 text-sm">{summary.summary}</p>
                      </div>

                      {summary.key_points.length > 0 && (
                        <div>
                          <Label className="text-xs text-muted-foreground">
                            Key Points
                          </Label>
                          <ul className="mt-1 list-inside list-disc space-y-1 text-sm">
                            {summary.key_points.map((point, i) => (
                              <li key={i}>{point}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {summary.action_description && (
                        <div>
                          <Label className="text-xs text-muted-foreground">
                            Required Action
                          </Label>
                          <p className="mt-1 text-sm">
                            {summary.action_description}
                          </p>
                        </div>
                      )}

                      <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                        {summary.mail_from && (
                          <span>From: {summary.mail_from}</span>
                        )}
                        {summary.mail_date && (
                          <span>Date: {summary.mail_date}</span>
                        )}
                        <span>
                          Summarized: {formatDate(summary.created_at)}
                        </span>
                        {summary.notified && (
                          <Badge variant="secondary">
                            Notified
                          </Badge>
                        )}
                      </div>
                      {summary.mail_from && (
                        <div className="flex justify-end gap-1 pt-2">
                          <CreateContactButton senderEmail={summary.mail_from} />
                          <SpamButton
                            variant="mail"
                            mailId={summary.mail_uid}
                            mailAccountId={summary.mail_account_id}
                            senderEmail={summary.mail_from}
                            subject={summary.mail_subject}
                          />
                        </div>
                      )}
                    </>
                  }
                  date={summary.mail_date ?? formatDate(summary.created_at)}
                  actions={
                    <AppButton
                      icon={<Trash2 />}
                      label="Delete"
                      variant="ghost"
                      color="destructive"
                      onClick={() => setDeleteTarget(summary)}
                    />
                  }
                />
              );
            }}
          />
        </CardContent>
      </Card>

      {/* Settings Dialog */}
      <PluginSettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        title="Email Summary Settings"
        description="Configure email summary behavior."
      >
        <div className="py-4 text-center text-sm text-muted-foreground">
          No additional settings available for this plugin yet.
        </div>
      </PluginSettingsDialog>

      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete Summary"
        description={
          <>
            Are you sure you want to delete the summary for{" "}
            <span className="font-medium">{deleteTarget?.mail_subject ?? "this email"}</span>?
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
