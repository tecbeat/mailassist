import { useState, useCallback, useEffect, useMemo } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { useQueryClient } from "@tanstack/react-query";
import {
  Check,
  XCircle,
  RefreshCw,
  RotateCcw,
  Pencil,
} from "lucide-react";

import {
  useListApprovalsApiApprovalsGet,
  getListApprovalsApiApprovalsGetQueryKey,
  useApproveActionApiApprovalsApprovalIdApprovePost,
  useRejectActionApiApprovalsApprovalIdRejectPost,
  useEditApprovalApiApprovalsApprovalIdPatch,
} from "@/services/api/approvals/approvals";
import type {
  ApprovalResponse,
  ApprovalListResponse,
  ListApprovalsApiApprovalsGetSort,
} from "@/types/api";

import { AppButton } from "@/components/app-button";
import { FilterListItem } from "@/components/filter-list-item";
import { PageHeader } from "@/components/layout/page-header";
import { SearchableCardList } from "@/components/searchable-card-list";
import { SortToggle } from "@/components/sort-toggle";
import { useSearchableList } from "@/hooks/use-searchable-list";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn, formatRelativeTime, unwrapResponse } from "@/lib/utils";

import {
  STATUS_TABS,
  AUTO_REFRESH_MS,
  type StatusFilter,
  getActionConfig,
  formatProposedAction,
  formatTimeRemaining,
  isExpiringSoon,
} from "./approval-helpers";
import { ApprovalEditForm } from "./approval-edit-form";
import { ApprovalCardSkeleton } from "./approval-card-skeleton";
import { HttpError } from "@/services/client";

// ---------------------------------------------------------------------------
// Approvals Page
// ---------------------------------------------------------------------------

export default function ApprovalsPage() {
  usePageTitle("Approvals");
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const list = useSearchableList();

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [functionTypeFilter, setFunctionTypeFilter] = useState<string>("all");
  const [sortOrder, setSortOrder] = useState<string>("newest");
  const [processingIds, setProcessingIds] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editedAction, setEditedAction] = useState<Record<string, unknown>>({});

  useEffect(() => {
    list.setPage(1);
    // list.setPage is a stable useState setter — omitting it from deps is safe
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, functionTypeFilter, sortOrder]);

  // --- Data fetching ---
  const queryParams = useMemo(
    () => ({
      status: statusFilter === "all" ? undefined : statusFilter,
      function_type: functionTypeFilter === "all" ? undefined : functionTypeFilter,
      sort: sortOrder as ListApprovalsApiApprovalsGetSort,
      ...(list.searchFilter ? { search: list.searchFilter } : {}),
      page: list.page,
      per_page: list.perPage,
    }),
    [statusFilter, functionTypeFilter, sortOrder, list.searchFilter, list.page, list.perPage],
  );

  const listQuery = useListApprovalsApiApprovalsGet(queryParams, {
    query: { refetchInterval: AUTO_REFRESH_MS },
  });

  const listData = unwrapResponse<ApprovalListResponse>(listQuery.data);
  const approvals: ApprovalResponse[] = listData?.items ?? [];
  const totalPages = listData?.pages ?? 1;
  const totalCount = listData?.total ?? 0;

  // --- Mutations ---
  const approveMutation = useApproveActionApiApprovalsApprovalIdApprovePost();
  const rejectMutation = useRejectActionApiApprovalsApprovalIdRejectPost();
  const editMutation = useEditApprovalApiApprovalsApprovalIdPatch();

  // --- Optimistic update helper ---
  const performOptimisticRemoval = useCallback(
    (ids: string[]) => {
      const queryKey = getListApprovalsApiApprovalsGetQueryKey(queryParams);
      const previousData = queryClient.getQueryData(queryKey);

      queryClient.setQueryData(queryKey, (old: unknown) => {
        if (!old || typeof old !== "object") return old;
        const data = (old as { data?: ApprovalListResponse }).data;
        if (!data) return old;
        const removedSet = new Set(ids);
        return {
          ...old,
          data: {
            ...data,
            items: data.items.filter((item: ApprovalResponse) => !removedSet.has(item.id)),
            total: Math.max(0, data.total - ids.length),
          },
        };
      });

      return { queryKey, previousData };
    },
    [queryClient, queryParams],
  );

  const rollback = useCallback(
    (queryKey: readonly unknown[], previousData: unknown) => {
      queryClient.setQueryData(queryKey, previousData);
    },
    [queryClient],
  );

  const handleApprove = useCallback(
    (id: string) => {
      setProcessingIds((prev) => new Set(prev).add(id));
      const { queryKey, previousData } = performOptimisticRemoval([id]);

      approveMutation.mutate(
        { approvalId: id },
        {
          onSuccess: () => {
            toast({ title: "Approved", description: "Action has been approved and will be executed." });
            queryClient.invalidateQueries({ queryKey: ["/api/approvals"] });
            queryClient.invalidateQueries({ queryKey: ["/api/folders"] });
          },
          onError: (err) => {
            const status = err instanceof HttpError ? err.status : 0;
            if (status === 409 || status === 410) {
              // Approval was already processed or has expired — drop the optimistic
              // state and refresh so the stale item disappears without a page reload.
              queryClient.invalidateQueries({ queryKey: ["/api/approvals"] });
              const description =
                status === 410
                  ? "This approval has expired and has been removed from your queue."
                  : "This approval was already processed by another session.";
              toast({ title: "Approval no longer actionable", description, variant: "destructive" });
            } else {
              rollback(queryKey, previousData);
              toast({ title: "Approval failed", description: "Could not approve this action. Please try again.", variant: "destructive" });
            }
          },
          onSettled: () => {
            setProcessingIds((prev) => { const next = new Set(prev); next.delete(id); return next; });
          },
        },
      );
    },
    [approveMutation, performOptimisticRemoval, rollback, queryClient, toast],
  );

  const handleReject = useCallback(
    (id: string) => {
      setProcessingIds((prev) => new Set(prev).add(id));
      const { queryKey, previousData } = performOptimisticRemoval([id]);

      rejectMutation.mutate(
        { approvalId: id },
        {
          onSuccess: () => {
            toast({ title: "Rejected", description: "Action has been rejected." });
            queryClient.invalidateQueries({ queryKey: ["/api/approvals"] });
          },
          onError: (err) => {
            const status = err instanceof HttpError ? err.status : 0;
            if (status === 409 || status === 410) {
              queryClient.invalidateQueries({ queryKey: ["/api/approvals"] });
              const description =
                status === 410
                  ? "This approval has expired and has been removed from your queue."
                  : "This approval was already processed by another session.";
              toast({ title: "Approval no longer actionable", description, variant: "destructive" });
            } else {
              rollback(queryKey, previousData);
              toast({ title: "Rejection failed", description: "Could not reject this action. Please try again.", variant: "destructive" });
            }
          },
          onSettled: () => {
            setProcessingIds((prev) => { const next = new Set(prev); next.delete(id); return next; });
          },
        },
      );
    },
    [rejectMutation, performOptimisticRemoval, rollback, queryClient, toast],
  );

  const handleStartEdit = useCallback(
    (approval: ApprovalResponse) => {
      setEditingId(approval.id);
      setEditedAction({ ...(approval.edited_actions ?? approval.proposed_action) });
    },
    [],
  );

  const handleSaveAndApprove = useCallback(
    (id: string) => {
      // Snapshot editedAction at call time to avoid stale-closure reads
      // if state updates between when the callback was created and invoked.
      const actionSnapshot = editedAction;
      setProcessingIds((prev) => new Set(prev).add(id));

      editMutation.mutate(
        { approvalId: id, data: { edited_actions: actionSnapshot } },
        {
          onSuccess: () => {
            const { queryKey, previousData } = performOptimisticRemoval([id]);
            approveMutation.mutate(
              { approvalId: id },
              {
                onSuccess: () => {
                  setEditingId(null);
                  setEditedAction({});
                  toast({ title: "Approved (edited)", description: "Edited action has been approved and will be executed." });
                  queryClient.invalidateQueries({ queryKey: ["/api/approvals"] });
                  queryClient.invalidateQueries({ queryKey: ["/api/folders"] });
                },
                onError: (err) => {
                  const status = err instanceof HttpError ? err.status : 0;
                  if (status === 409 || status === 410) {
                    queryClient.invalidateQueries({ queryKey: ["/api/approvals"] });
                    const description =
                      status === 410
                        ? "This approval has expired and has been removed from your queue."
                        : "This approval was already processed by another session.";
                    toast({ title: "Approval no longer actionable", description, variant: "destructive" });
                  } else {
                    rollback(queryKey, previousData);
                    toast({ title: "Approval failed", description: "Could not approve the edited action. Please try again.", variant: "destructive" });
                  }
                },
                onSettled: () => {
                  setProcessingIds((prev) => { const next = new Set(prev); next.delete(id); return next; });
                },
              },
            );
          },
          onError: () => {
            toast({ title: "Save failed", description: "Could not save the edited action. Please try again.", variant: "destructive" });
            setProcessingIds((prev) => { const next = new Set(prev); next.delete(id); return next; });
          },
        },
      );
    },
    [editMutation, approveMutation, editedAction, performOptimisticRemoval, rollback, queryClient, toast],
  );

  const handleCancelEdit = useCallback(() => {
    setEditingId(null);
    setEditedAction({});
  }, []);

  const hasActiveFilters = functionTypeFilter !== "all" || sortOrder !== "newest";

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      <PageHeader
        title="Pending Approvals"
        description="Review and manage AI-proposed actions on your mail."
        actions={
          <AppButton
            icon={<RefreshCw />}
            label="Refresh"
            variant="outline"
            size="sm"
            loading={listQuery.isFetching}
            onClick={() => listQuery.refetch()}
            disabled={listQuery.isFetching}
          >
            Refresh
          </AppButton>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Approval Queue</CardTitle>
          <CardDescription>
            Review and approve or reject AI-proposed actions on your emails.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList<ApprovalResponse>
            list={list}
            items={approvals}
            totalPages={totalPages}
            totalCount={totalCount}
            isError={listQuery.isError}
            isLoading={listQuery.isLoading}
            isFetching={listQuery.isFetching}
            errorMessage="Failed to load approvals."
            onRetry={() => listQuery.refetch()}
            searchPlaceholder="Search by subject or sender..."
            hasActiveFilters={hasActiveFilters}
            filterContent={
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Status</Label>
                  <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Status" /></SelectTrigger>
                    <SelectContent>
                      {STATUS_TABS.map((tab) => (
                        <SelectItem key={tab.value} value={tab.value}>{tab.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Plugin</Label>
                  <Select value={functionTypeFilter} onValueChange={(v) => setFunctionTypeFilter(v)}>
                    <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="All plugins" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All plugins</SelectItem>
                      <SelectItem value="labeling">Auto-Labeling</SelectItem>
                      <SelectItem value="smart_folder">Smart Folders</SelectItem>
                      <SelectItem value="auto_reply">Auto Reply</SelectItem>
                      <SelectItem value="spam_detection">Spam Detection</SelectItem>
                      <SelectItem value="newsletter_detection">Newsletter</SelectItem>
                      <SelectItem value="coupon_extraction">Coupon</SelectItem>
                      <SelectItem value="calendar_extraction">Calendar</SelectItem>
                      <SelectItem value="email_summary">Summary</SelectItem>
                      <SelectItem value="contacts">Contacts</SelectItem>
                      <SelectItem value="notifications">Notifications</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Sort Order</Label>
                  <SortToggle
                    sortOrder={sortOrder}
                    onToggle={(o) => { setSortOrder(o); list.setPage(1); }}
                    isFetching={listQuery.isFetching}
                    variant="inline"
                  />
                </div>
                {(hasActiveFilters || statusFilter !== "pending") && (
                  <AppButton
                    icon={<RotateCcw />}
                    label="Clear filters"
                    variant="ghost"
                    size="sm"
                    className="h-7 w-full text-xs"
                    onClick={() => {
                      setStatusFilter("pending");
                      setFunctionTypeFilter("all");
                      setSortOrder("newest");
                      list.setPage(1);
                    }}
                  >
                    Clear filters
                  </AppButton>
                )}
              </div>
            }
            headerExtra={
              <Tabs value={statusFilter} onValueChange={(v) => setStatusFilter(v as StatusFilter)}>
                <TabsList>
                  {STATUS_TABS.map((tab) => (
                    <TabsTrigger key={tab.value} value={tab.value}>{tab.label}</TabsTrigger>
                  ))}
                </TabsList>
              </Tabs>
            }
            skeleton={
              <div className="space-y-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <ApprovalCardSkeleton key={i} />
                ))}
              </div>
            }
            emptyIcon={<Check className="mb-3 h-10 w-10 text-muted-foreground" />}
            emptyMessage={
              statusFilter === "pending"
                ? "You're all caught up! No actions are awaiting your review."
                : `No ${statusFilter === "all" ? "" : statusFilter + " "}approvals to display.`
            }
            renderItem={(approval) => {
              const config = getActionConfig(approval.function_type);
              const isProcessing = processingIds.has(approval.id);
              const isPending = approval.status === "pending";
              const expiringSoon = isPending && isExpiringSoon(approval.expires_at);
              const isEditing = editingId === approval.id;

              return (
                <FilterListItem
                  key={approval.id}
                  className={cn(
                    "transition-all",
                    isProcessing && "opacity-50",
                    expiringSoon && "border-yellow-500/50",
                  )}
                  icon={config.icon}
                  title={approval.mail_subject}
                  badges={
                    <>
                      <Badge variant={config.variant}>{config.label}</Badge>
                      {!isPending && (
                        <Badge
                          variant={
                            approval.status === "approved"
                              ? "success"
                              : approval.status === "rejected"
                                ? "destructive"
                                : "secondary"
                          }
                        >
                          {approval.status}
                        </Badge>
                      )}
                    </>
                  }
                  subtitle={
                    <p className="truncate text-xs text-muted-foreground">
                      {isPending
                        ? approval.mail_from
                        : formatProposedAction(approval.proposed_action, approval.function_type)}
                    </p>
                  }
                  preview={
                    isPending
                      ? `${formatProposedAction(approval.proposed_action, approval.function_type)}${approval.ai_reasoning ? `: ${approval.ai_reasoning}` : ""}`
                      : approval.ai_reasoning
                  }
                  previewLines={2}
                  expandable={isEditing}
                  expanded={isEditing}
                  onToggleExpand={handleCancelEdit}
                  expandedContent={
                    isEditing ? (
                      <ApprovalEditForm
                        approval={approval}
                        editedAction={editedAction}
                        onChangeAction={setEditedAction}
                        onSave={() => handleSaveAndApprove(approval.id)}
                        onCancel={handleCancelEdit}
                        isSaving={isProcessing}
                      />
                    ) : undefined
                  }
                  date={
                    isPending
                      ? formatTimeRemaining(approval.expires_at)
                      : formatRelativeTime(approval.created_at)
                  }
                  actions={
                    isPending ? (
                      <div className="flex gap-1">
                        <AppButton
                          icon={<Pencil />}
                          label="Edit before approving"
                          variant="ghost"
                          disabled={isProcessing || isEditing}
                          onClick={() => handleStartEdit(approval)}
                        />
                        <AppButton
                          icon={<Check />}
                          label="Approve"
                          variant="ghost"
                          loading={isProcessing && !isEditing}
                          disabled={isProcessing || isEditing}
                          onClick={() => handleApprove(approval.id)}
                        />
                        <AppButton
                          icon={<XCircle />}
                          label="Reject"
                          variant="ghost"
                          loading={isProcessing && !isEditing}
                          disabled={isProcessing || isEditing}
                          onClick={() => handleReject(approval.id)}
                        />
                      </div>
                    ) : undefined
                  }
                />
              );
            }}
          />

          {listQuery.dataUpdatedAt > 0 && (
            <p className="text-xs text-muted-foreground">
              Last updated: {new Date(listQuery.dataUpdatedAt).toLocaleString()}
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
