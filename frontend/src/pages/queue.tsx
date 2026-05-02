import { useState, useCallback, useEffect, useMemo } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router";
import {
  RefreshCw,
  RotateCcw,
  RotateCw,
  Inbox,
  ChevronDown,
  ChevronRight,
} from "lucide-react";

import {
  useListQueueApiQueueGet,
  useRetryEmailApiQueueEmailIdRetryPost,
} from "@/services/api/queue/queue";
import { useListMailAccountsApiMailAccountsGet } from "@/services/api/mail-accounts/mail-accounts";
import type {
  TrackedEmailListResponse,
  TrackedEmailResponse,
  TrackedEmailStatus,
  ErrorType,
  MailAccountResponse,
} from "@/types/api";

import { AppButton } from "@/components/app-button";
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
import { Skeleton } from "@/components/ui/skeleton";
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

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: TrackedEmailStatus }) {
  const config: Record<TrackedEmailStatus, { label: string; variant: "default" | "secondary" | "destructive" | "success" | "warning"; className?: string }> = {
    queued: { label: "Queued", variant: "secondary" },
    processing: { label: "Processing", variant: "default", className: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" },
    completed: { label: "Completed", variant: "success" },
    failed: { label: "Failed", variant: "destructive" },
  };
  const { label, variant, className } = config[status] ?? { label: status, variant: "secondary" as const };
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
// Plugin pills
// ---------------------------------------------------------------------------

function PluginPills({
  completed,
  failed,
  skipped,
}: {
  completed: string[] | null | undefined;
  failed: string[] | null | undefined;
  skipped: string[] | null | undefined;
}) {
  const [expanded, setExpanded] = useState(false);
  const all = [
    ...(completed ?? []).map((p) => ({ name: p, state: "completed" as const })),
    ...(failed ?? []).map((p) => ({ name: p, state: "failed" as const })),
    ...(skipped ?? []).map((p) => ({ name: p, state: "skipped" as const })),
  ];
  if (all.length === 0) return null;

  const pillClass: Record<string, string> = {
    completed: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
    failed: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    skipped: "bg-muted text-muted-foreground",
  };

  return (
    <div className="mt-2">
      <button
        className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {all.length} plugin{all.length !== 1 ? "s" : ""}
      </button>
      {expanded && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {all.map(({ name, state }) => (
            <span
              key={`${state}-${name}`}
              className={cn("rounded px-1.5 py-0.5 text-xs font-medium", pillClass[state])}
            >
              {name}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Error detail row
// ---------------------------------------------------------------------------

function ErrorDetail({ error, errorType }: { error: string | null | undefined; errorType: ErrorType | null | undefined }) {
  const [expanded, setExpanded] = useState(false);
  if (!error) return null;

  const label = errorType
    ? { provider_imap: "IMAP Error", provider_ai: "AI Error", mail: "Mail Error", timeout: "Timeout" }[errorType] ?? errorType
    : "Error";

  return (
    <div className="mt-2">
      <button
        className="flex items-center gap-1 text-xs text-red-600 hover:text-red-700 dark:text-red-400"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {label}
      </button>
      {expanded && (
        <p className="mt-1 rounded bg-red-50 px-2 py-1.5 text-xs text-red-700 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Queue row skeleton
// ---------------------------------------------------------------------------

function QueueRowSkeleton() {
  return (
    <div className="flex items-start gap-3 rounded-lg border p-3">
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-3 w-32" />
      </div>
      <Skeleton className="h-5 w-20" />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Queue row
// ---------------------------------------------------------------------------

function QueueRow({
  email,
  accountName,
  onRetry,
  isRetrying,
}: {
  email: TrackedEmailResponse;
  accountName: string | undefined;
  onRetry: (id: string) => void;
  isRetrying: boolean;
}) {
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">
            {email.subject ?? email.mail_uid}
          </p>
          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {email.sender ?? "—"}
            {accountName && (
              <span className="ml-2 text-muted-foreground/60">· {accountName}</span>
            )}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusBadge status={email.status} />
          {email.status === "failed" && (
            <AppButton
              icon={<RotateCcw />}
              label="Retry"
              variant="ghost"
              size="sm"
              loading={isRetrying}
              disabled={isRetrying}
              onClick={() => onRetry(email.id)}
            />
          )}
        </div>
      </div>

      <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
        {email.received_at && (
          <span>Received {formatRelativeTime(email.received_at)}</span>
        )}
        <span>Updated {formatRelativeTime(email.updated_at)}</span>
        {email.retry_count > 0 && (
          <span className="text-orange-600 dark:text-orange-400">
            {email.retry_count} retr{email.retry_count === 1 ? "y" : "ies"}
          </span>
        )}
      </div>

      {email.status === "failed" && (
        <ErrorDetail error={email.last_error} errorType={email.error_type} />
      )}

      {email.status === "completed" && (
        <PluginPills
          completed={email.plugins_completed}
          failed={email.plugins_failed}
          skipped={email.plugins_skipped}
        />
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

  // Retry mutation
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
            skeleton={
              <div className="space-y-2">
                {Array.from({ length: 5 }).map((_, i) => (
                  <QueueRowSkeleton key={i} />
                ))}
              </div>
            }
            emptyIcon={<Inbox className="mb-3 h-10 w-10 text-muted-foreground" />}
            emptyMessage="No emails in the queue."
            renderItem={(email) => (
              <QueueRow
                key={email.id}
                email={email}
                accountName={accountMap[email.mail_account_id]}
                onRetry={handleRetry}
                isRetrying={retryingIds.has(email.id)}
              />
            )}
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
