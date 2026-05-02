import { useState, useCallback, useEffect, useMemo } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import {
  RefreshCw,
  RotateCcw,
  RotateCw,
  Inbox,
  Play,
} from "lucide-react";

import {
  useListQueueApiQueueGet,
  useRetryEmailApiQueueEmailIdRetryPost,
  useReprocessEmailApiQueueEmailIdReprocessPost,
} from "@/services/api/queue/queue";
import { useListMailAccountsApiMailAccountsGet } from "@/services/api/mail-accounts/mail-accounts";
import type {
  TrackedEmailListResponse,
  TrackedEmailResponse,
  TrackedEmailStatus,
  ErrorType,
  MailAccountResponse,
  PluginResultEntry,
  PipelineProgress,
  PipelinePluginName,
} from "@/types/api";

import { AppButton } from "@/components/app-button";
import { FilterListItem } from "@/components/filter-list-item";
import { ListSkeleton } from "@/components/list-skeleton";
import { PageHeader } from "@/components/layout/page-header";
import { SearchableCardList } from "@/components/searchable-card-list";
import { ToggleBadge } from "@/components/toggle-badge";
import { useSearchableList } from "@/hooks/use-searchable-list";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { BadgeProps } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { cn, formatRelativeTime, unwrapResponse } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Auto-refresh interval when processing mails are present (3s). */
const ACTIVE_REFRESH_MS = 3_000;

const STATUS_OPTIONS: { value: TrackedEmailStatus | "all"; label: string }[] = [
  { value: "all", label: "All statuses" },
  { value: "queued", label: "Queued" },
  { value: "processing", label: "Processing" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
];

const ERROR_TYPE_OPTIONS: { value: ErrorType | "all"; label: string }[] = [
  { value: "all", label: "All error types" },
  { value: "provider_imap", label: "IMAP Provider" },
  { value: "provider_ai", label: "AI Provider" },
  { value: "mail", label: "Mail Error" },
  { value: "timeout", label: "Timeout" },
];

const STATUS_BADGE_CONFIG: Record<TrackedEmailStatus, { label: string; variant: "default" | "secondary" | "destructive" | "success" | "warning"; className?: string }> = {
  queued: { label: "Queued", variant: "secondary" },
  processing: { label: "Processing", variant: "default", className: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" },
  completed: { label: "Completed", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
};

const ERROR_TYPE_LABELS: Record<string, string> = {
  provider_imap: "IMAP Error",
  provider_ai: "AI Error",
  mail: "Mail Error",
  timeout: "Timeout",
};

// Plugin pill Badge variant by result status
const PLUGIN_STATUS_VARIANT: Record<string, BadgeProps["variant"]> = {
  completed: "success",
  failed: "destructive",
  warning: "warning",
  skipped: "secondary",
  pending: "secondary",
  processing: "default",
};

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: TrackedEmailStatus }) {
  const { label, variant, className } = STATUS_BADGE_CONFIG[status] ?? { label: status, variant: "secondary" as const };
  return (
    <Badge variant={variant} className={cn("text-xs font-medium", className)}>
      {status === "processing" && (
        <RotateCw className="mr-1 h-3 w-3 animate-spin" />
      )}
      {label}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Plugin pill using ToggleBadge
// ---------------------------------------------------------------------------

interface PluginPillProps {
  name: string;
  result: PluginResultEntry | undefined;
  emailStatus: TrackedEmailStatus;
  isSelected: boolean;
  onClick: () => void;
}

function PluginPill({ name, result, emailStatus, isSelected, onClick }: PluginPillProps) {
  let pillStatus: string;
  if (result) {
    pillStatus = result.status;
  } else if (emailStatus === "processing") {
    pillStatus = "processing";
  } else {
    pillStatus = "pending";
  }

  const displayName = result?.display_name ?? name;
  const variant = PLUGIN_STATUS_VARIANT[pillStatus] ?? "secondary";

  return (
    <ToggleBadge
      selected={isSelected}
      selectedVariant={variant}
      unselectedVariant={variant}
      onClick={onClick}
      className={cn(
        !isSelected && "opacity-75",
        pillStatus === "processing" && "animate-pulse",
      )}
    >
      {displayName}
    </ToggleBadge>
  );
}

// ---------------------------------------------------------------------------
// Plugin result detail panel
// ---------------------------------------------------------------------------

function PluginResultDetail({ result }: { result: PluginResultEntry }) {
  return (
    <div className="rounded-md border border-border bg-muted/30 p-3 text-xs space-y-2">
      <div className="flex items-center gap-2">
        <span className="font-medium">{result.display_name}</span>
        <Badge
          variant={
            result.status === "completed" ? "success" :
            result.status === "failed" ? "destructive" :
            result.status === "warning" ? "warning" :
            "secondary"
          }
          className="text-[10px]"
        >
          {result.status}
        </Badge>
      </div>
      {result.summary && (
        <p className="text-muted-foreground">{result.summary}</p>
      )}
      {result.details && (
        <details className="text-muted-foreground">
          <summary className="cursor-pointer font-medium text-foreground">Details</summary>
          <pre className="mt-1 overflow-auto rounded bg-muted p-2 text-[11px]">
            {JSON.stringify(result.details, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helper: derive plugin pill list for processing mails from pipeline_progress
// ---------------------------------------------------------------------------

interface DerivedPlugin {
  name: string;
  displayName: string;
  status: string; // "completed" | "processing" | "pending"
}

function deriveProcessingPlugins(progress: PipelineProgress): DerivedPlugin[] {
  const names: PipelinePluginName[] = progress.plugin_names ?? [];
  if (names.length === 0) return [];

  const currentIdx = progress.plugin_index ?? 0;

  return names.map((p, i) => {
    const idx = i + 1; // plugin_index is 1-based
    let status: string;
    if (idx < currentIdx) {
      status = "completed";
    } else if (idx === currentIdx) {
      status = "processing";
    } else {
      status = "pending";
    }
    return { name: p.name, displayName: p.display_name, status };
  });
}

// ---------------------------------------------------------------------------
// Expanded content: error detail + plugin pills with click-to-show results
// ---------------------------------------------------------------------------

function ExpandedContent({
  email,
  selectedPlugin,
  onSelectPlugin,
}: {
  email: TrackedEmailResponse;
  selectedPlugin: string | null;
  onSelectPlugin: (name: string | null) => void;
}) {
  const hasError = email.status === "failed" && email.last_error;
  const pluginResults = email.plugin_results;
  const progress = email.pipeline_progress;

  // For processing mails: derive plugin list from live pipeline progress
  const isProcessing = email.status === "processing";
  const processingPlugins = isProcessing && progress ? deriveProcessingPlugins(progress) : [];

  // For completed/failed mails: collect plugins from results + status lists
  const allPlugins = new Set<string>();
  if (!isProcessing) {
    if (pluginResults) {
      for (const name of Object.keys(pluginResults)) allPlugins.add(name);
    }
    for (const name of email.plugins_completed ?? []) allPlugins.add(name);
    for (const name of email.plugins_failed ?? []) allPlugins.add(name);
    for (const name of email.plugins_skipped ?? []) allPlugins.add(name);
  }

  const hasPlugins = isProcessing ? processingPlugins.length > 0 : allPlugins.size > 0;
  if (!hasError && !hasPlugins) return null;

  const selectedResult = selectedPlugin && pluginResults?.[selectedPlugin];

  return (
    <div className="space-y-3">
      {hasError && (
        <div>
          <p className="mb-1 text-xs font-medium text-red-600 dark:text-red-400">
            {email.error_type ? (ERROR_TYPE_LABELS[email.error_type] ?? email.error_type) : "Error"}
          </p>
          <p className="rounded bg-red-50 px-2 py-1.5 text-xs text-red-700 dark:bg-red-900/20 dark:text-red-400">
            {email.last_error}
          </p>
        </div>
      )}

      {hasPlugins && (
        <div>
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">
            {isProcessing && progress
              ? `Plugins (${progress.plugin_index ?? 0}/${progress.plugins_total ?? processingPlugins.length})`
              : "Plugins"}
          </p>
          <div className="flex flex-wrap gap-1">
            {isProcessing
              ? processingPlugins.map((p) => {
                  const variant = PLUGIN_STATUS_VARIANT[p.status] ?? "secondary";
                  return (
                    <ToggleBadge
                      key={p.name}
                      selected={false}
                      selectedVariant={variant}
                      unselectedVariant={variant}
                      className={cn(
                        p.status === "processing" && "animate-pulse",
                        p.status === "pending" && "opacity-50",
                      )}
                    >
                      {p.displayName}
                    </ToggleBadge>
                  );
                })
              : [...allPlugins].map((name) => (
                  <PluginPill
                    key={name}
                    name={name}
                    result={pluginResults?.[name]}
                    emailStatus={email.status}
                    isSelected={selectedPlugin === name}
                    onClick={() => onSelectPlugin(selectedPlugin === name ? null : name)}
                  />
                ))}
          </div>
          {selectedResult && (
            <div className="mt-2">
              <PluginResultDetail result={selectedResult} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Queue Page
// ---------------------------------------------------------------------------

export default function QueuePage() {
  usePageTitle("Mail Queue");
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const list = useSearchableList();

  const [searchParams] = useSearchParams();
  const initialStatus = (searchParams.get("status") as TrackedEmailStatus | null) ?? "all";

  const [statusFilter, setStatusFilter] = useState<TrackedEmailStatus | "all">(
    STATUS_OPTIONS.some((o) => o.value === initialStatus) ? initialStatus : "all",
  );
  const [accountFilter, setAccountFilter] = useState<string>("all");
  const [errorTypeFilter, setErrorTypeFilter] = useState<ErrorType | "all">("all");
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set());
  const [reprocessingIds, setReprocessingIds] = useState<Set<string>>(new Set());
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [selectedPlugins, setSelectedPlugins] = useState<Record<string, string | null>>({});

  // Reset to page 1 when filters change
  useEffect(() => {
    list.setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, accountFilter, errorTypeFilter]);

  // Fetch mail accounts for the filter dropdown
  const accountsQuery = useListMailAccountsApiMailAccountsGet();
  const accounts = unwrapResponse<MailAccountResponse[]>(accountsQuery.data) ?? [];

  // Build query params
  const queryParams = useMemo(
    () => ({
      ...(statusFilter !== "all" ? { status: statusFilter } : {}),
      ...(accountFilter !== "all" ? { account_id: accountFilter } : {}),
      ...(errorTypeFilter !== "all" ? { error_type: errorTypeFilter } : {}),
      ...(list.searchFilter ? { q: list.searchFilter } : {}),
      page: list.page,
      per_page: list.perPage,
    }),
    [statusFilter, accountFilter, errorTypeFilter, list.searchFilter, list.page, list.perPage],
  );

  const listQuery = useListQueueApiQueueGet(queryParams, {
    query: {
      // Auto-refresh when processing mails are present
      refetchInterval: (query) => {
        const data = unwrapResponse<TrackedEmailListResponse>(query.state.data);
        const hasProcessing = data?.items.some((e) => e.status === "processing");
        return hasProcessing ? ACTIVE_REFRESH_MS : false;
      },
    },
  });

  const listData = unwrapResponse<TrackedEmailListResponse>(listQuery.data);
  const emails: TrackedEmailResponse[] = listData?.items ?? [];
  const totalPages = listData?.pages ?? 1;
  const totalCount = listData?.total ?? 0;

  // Account name lookup map
  const accountMap = useMemo(
    () => Object.fromEntries(accounts.map((a) => [a.id, a.name])),
    [accounts],
  );

  // Retry mutation (for failed emails)
  const retryMutation = useRetryEmailApiQueueEmailIdRetryPost();

  const handleRetry = useCallback(
    (id: string) => {
      setRetryingIds((prev) => new Set(prev).add(id));
      retryMutation.mutate(
        { emailId: id },
        {
          onSuccess: () => {
            toast({ title: "Retry queued", description: "The email has been re-queued for processing." });
            queryClient.invalidateQueries({ queryKey: ["/api/queue"] });
          },
          onError: () => {
            toast({ title: "Retry failed", description: "Could not retry this email. Please try again.", variant: "destructive" });
          },
          onSettled: () => {
            setRetryingIds((prev) => {
              const next = new Set(prev);
              next.delete(id);
              return next;
            });
          },
        },
      );
    },
    [retryMutation, queryClient, toast],
  );

  // Reprocess mutation (for any email)
  const reprocessMutation = useReprocessEmailApiQueueEmailIdReprocessPost();

  const handleReprocess = useCallback(
    (id: string) => {
      setReprocessingIds((prev) => new Set(prev).add(id));
      reprocessMutation.mutate(
        { emailId: id },
        {
          onSuccess: () => {
            toast({ title: "Reprocessing queued", description: "The email has been re-queued for full reprocessing." });
            queryClient.invalidateQueries({ queryKey: ["/api/queue"] });
          },
          onError: () => {
            toast({ title: "Reprocessing failed", description: "Could not reprocess this email. Please try again.", variant: "destructive" });
          },
          onSettled: () => {
            setReprocessingIds((prev) => {
              const next = new Set(prev);
              next.delete(id);
              return next;
            });
          },
        },
      );
    },
    [reprocessMutation, queryClient, toast],
  );

  const toggleExpanded = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const handleSelectPlugin = useCallback((emailId: string, pluginName: string | null) => {
    setSelectedPlugins((prev) => ({ ...prev, [emailId]: pluginName }));
  }, []);

  // Auto-expand processing mails that have live pipeline progress
  useEffect(() => {
    const processingWithProgress = emails.filter(
      (e) => e.status === "processing" && !!e.pipeline_progress?.plugin_names?.length,
    );
    if (processingWithProgress.length > 0) {
      setExpandedIds((prev) => {
        const next = new Set(prev);
        let changed = false;
        for (const e of processingWithProgress) {
          if (!next.has(e.id)) {
            next.add(e.id);
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }
  }, [emails]);

  const hasActiveFilters =
    statusFilter !== "all" || accountFilter !== "all" || errorTypeFilter !== "all";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Mail Queue"
        description="Paginated view of all tracked emails and their processing status."
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
          <CardTitle>Processing Queue</CardTitle>
          <CardDescription>
            All emails discovered by the worker, sorted by last updated.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList<TrackedEmailResponse>
            list={list}
            items={emails}
            totalPages={totalPages}
            totalCount={totalCount}
            isError={listQuery.isError}
            isLoading={listQuery.isLoading}
            isFetching={listQuery.isFetching}
            errorMessage="Failed to load the mail queue."
            onRetry={() => listQuery.refetch()}
            searchPlaceholder="Search by subject or sender..."
            hasActiveFilters={hasActiveFilters}
            filterContent={
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Status</Label>
                  <Select
                    value={statusFilter}
                    onValueChange={(v) => setStatusFilter(v as TrackedEmailStatus | "all")}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="All statuses" />
                    </SelectTrigger>
                    <SelectContent>
                      {STATUS_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {accounts.length > 0 && (
                  <div className="space-y-1.5">
                    <Label className="text-xs">Mail Account</Label>
                    <Select value={accountFilter} onValueChange={setAccountFilter}>
                      <SelectTrigger className="h-8 text-xs">
                        <SelectValue placeholder="All accounts" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">All accounts</SelectItem>
                        {accounts.map((a) => (
                          <SelectItem key={a.id} value={a.id}>{a.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                <div className="space-y-1.5">
                  <Label className="text-xs">Error Type</Label>
                  <Select
                    value={errorTypeFilter}
                    onValueChange={(v) => setErrorTypeFilter(v as ErrorType | "all")}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="All error types" />
                    </SelectTrigger>
                    <SelectContent>
                      {ERROR_TYPE_OPTIONS.map((o) => (
                        <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {hasActiveFilters && (
                  <AppButton
                    icon={<RotateCcw />}
                    label="Clear filters"
                    variant="ghost"
                    size="sm"
                    className="h-7 w-full text-xs"
                    onClick={() => {
                      setStatusFilter("all");
                      setAccountFilter("all");
                      setErrorTypeFilter("all");
                      list.setPage(1);
                    }}
                  >
                    Clear filters
                  </AppButton>
                )}
              </div>
            }
            skeleton={<ListSkeleton count={5} lines={["w-1/2", "w-1/3"]} />}
            emptyIcon={<Inbox className="mb-3 h-10 w-10 text-muted-foreground" />}
            emptyMessage="No emails in the queue."
            renderItem={(email) => {
              const isRetrying = retryingIds.has(email.id);
              const isReprocessing = reprocessingIds.has(email.id);
              const isBusy = isRetrying || isReprocessing;

              // Expandable when there are plugin results, error details, plugin lists,
              // or live pipeline progress for processing mails
              const hasPluginInfo = !!(
                email.plugin_results && Object.keys(email.plugin_results).length > 0
              ) || (email.plugins_completed?.length ?? 0) > 0
                || (email.plugins_failed?.length ?? 0) > 0
                || (email.plugins_skipped?.length ?? 0) > 0;
              const hasLiveProgress = email.status === "processing" && !!email.pipeline_progress?.plugin_names?.length;
              const isExpandable = (email.status === "failed" && !!email.last_error) || hasPluginInfo || hasLiveProgress;
              const isExpanded = expandedIds.has(email.id);
              const accountName = accountMap[email.mail_account_id];

              return (
                <FilterListItem
                  key={email.id}
                  className={cn(isBusy && "opacity-50")}
                  title={email.subject ?? email.mail_uid}
                  badges={
                    <>
                      <StatusBadge status={email.status} />
                      {email.retry_count > 0 && (
                        <Badge variant="warning" className="text-xs">
                          {email.retry_count} retr{email.retry_count === 1 ? "y" : "ies"}
                        </Badge>
                      )}
                    </>
                  }
                  subtitle={
                    <p className="truncate text-xs text-muted-foreground">
                      {email.sender ?? "\u2014"}
                      {accountName && (
                        <span className="ml-2 text-muted-foreground/60">&middot; {accountName}</span>
                      )}
                    </p>
                  }
                  date={formatRelativeTime(email.updated_at)}
                  expandable={isExpandable}
                  expanded={isExpanded}
                  onToggleExpand={() => toggleExpanded(email.id)}
                  expandedContent={
                    <ExpandedContent
                      email={email}
                      selectedPlugin={selectedPlugins[email.id] ?? null}
                      onSelectPlugin={(name) => handleSelectPlugin(email.id, name)}
                    />
                  }
                  actions={
                    <div className="flex items-center gap-1">
                      {email.status === "failed" && (
                        <AppButton
                          icon={<RotateCcw />}
                          label="Retry"
                          variant="ghost"
                          size="sm"
                          loading={isRetrying}
                          disabled={isBusy}
                          onClick={() => handleRetry(email.id)}
                        />
                      )}
                      {email.status !== "processing" && (
                        <AppButton
                          icon={<Play />}
                          label="Reprocess"
                          variant="ghost"
                          size="sm"
                          loading={isReprocessing}
                          disabled={isBusy}
                          onClick={() => handleReprocess(email.id)}
                        />
                      )}
                    </div>
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
