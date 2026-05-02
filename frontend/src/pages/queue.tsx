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
} from "@/types/api";

import { AppButton } from "@/components/app-button";
import { FilterListItem } from "@/components/filter-list-item";
import { ListSkeleton } from "@/components/list-skeleton";
import { PageHeader } from "@/components/layout/page-header";
import { SearchableCardList } from "@/components/searchable-card-list";
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

/** Auto-refresh interval when processing mails are present (10s). */
const ACTIVE_REFRESH_MS = 10_000;

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

// Plugin pill color classes by result status
const PLUGIN_PILL_CLASSES: Record<string, string> = {
  completed: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50",
  failed: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50",
  warning: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400 hover:bg-yellow-200 dark:hover:bg-yellow-900/50",
  skipped: "bg-muted text-muted-foreground hover:bg-muted/80",
  pending: "bg-gray-100 text-gray-500 dark:bg-gray-800/30 dark:text-gray-500",
  processing: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 animate-pulse",
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
// Plugin pill with click-to-expand result
// ---------------------------------------------------------------------------

interface PluginPillProps {
  name: string;
  result: PluginResultEntry | undefined;
  emailStatus: TrackedEmailStatus;
  isSelected: boolean;
  onClick: () => void;
}

function PluginPill({ name, result, emailStatus, isSelected, onClick }: PluginPillProps) {
  // Determine pill status based on result or email status
  let pillStatus: string;
  if (result) {
    pillStatus = result.status;
  } else if (emailStatus === "processing") {
    pillStatus = "processing";
  } else if (emailStatus === "queued") {
    pillStatus = "pending";
  } else {
    pillStatus = "pending";
  }

  const displayName = result?.display_name ?? name;
  const pillClass = PLUGIN_PILL_CLASSES[pillStatus] ?? PLUGIN_PILL_CLASSES.pending;

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded px-1.5 py-0.5 text-xs transition-colors cursor-pointer",
        pillClass,
        isSelected ? "font-semibold" : "font-medium opacity-75",
      )}
    >
      {displayName}
    </button>
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

  // Collect all known plugins from results, completed, failed, skipped lists
  const allPlugins = new Set<string>();
  if (pluginResults) {
    for (const name of Object.keys(pluginResults)) allPlugins.add(name);
  }
  for (const name of email.plugins_completed ?? []) allPlugins.add(name);
  for (const name of email.plugins_failed ?? []) allPlugins.add(name);
  for (const name of email.plugins_skipped ?? []) allPlugins.add(name);

  const hasPlugins = allPlugins.size > 0;
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
          <p className="mb-1.5 text-xs font-medium text-muted-foreground">Plugins</p>
          <div className="flex flex-wrap gap-1">
            {[...allPlugins].map((name) => (
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

              // Expandable when there are plugin results, error details, or plugin lists
              const hasPluginInfo = !!(
                email.plugin_results && Object.keys(email.plugin_results).length > 0
              ) || (email.plugins_completed?.length ?? 0) > 0
                || (email.plugins_failed?.length ?? 0) > 0
                || (email.plugins_skipped?.length ?? 0) > 0;
              const isExpandable = (email.status === "failed" && !!email.last_error) || hasPluginInfo;
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
