import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { MailX, RotateCcw, XCircle } from "lucide-react";

import {
  useGetFailedMailsApiDashboardFailedMailsGet,
  useRetryFailedMailApiDashboardFailedMailsTrackedEmailIdRetryPost,
  useResolveFailedMailApiDashboardFailedMailsTrackedEmailIdResolvePost,
  getGetFailedMailsApiDashboardFailedMailsGetQueryKey,
  getGetDashboardStatsApiDashboardStatsGetQueryKey,
} from "@/services/api/dashboard/dashboard";
import type { FailedMailsResponse } from "@/types/api/failedMailsResponse";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AppButton } from "@/components/app-button";
import { Pagination } from "@/components/pagination";
import { QueryError } from "@/components/query-error";
import { formatRelativeTime, unwrapResponse } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";

import { CardSkeleton } from "./dashboard-helpers";

// ---------------------------------------------------------------------------
// Failed Mails Section
// ---------------------------------------------------------------------------

export function DashboardFailedMailsSection() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [failedPage, setFailedPage] = useState(1);

  const failedMailsQuery = useGetFailedMailsApiDashboardFailedMailsGet(
    { page: failedPage, per_page: 5 },
    { query: { refetchInterval: 15000 } },
  );
  const failedMailsData = unwrapResponse<FailedMailsResponse>(failedMailsQuery.data);

  const retryFailedMutation = useRetryFailedMailApiDashboardFailedMailsTrackedEmailIdRetryPost({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetFailedMailsApiDashboardFailedMailsGetQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetDashboardStatsApiDashboardStatsGetQueryKey() });
      },
      onError: () => {
        toast({ title: "Retry failed", description: "Could not retry this email. Please try again.", variant: "destructive" });
      },
    },
  });

  const resolveFailedMutation = useResolveFailedMailApiDashboardFailedMailsTrackedEmailIdResolvePost({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetFailedMailsApiDashboardFailedMailsGetQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetDashboardStatsApiDashboardStatsGetQueryKey() });
      },
      onError: () => {
        toast({ title: "Dismiss failed", description: "Could not dismiss this email. Please try again.", variant: "destructive" });
      },
    },
  });

  // Hide if no failed mails
  if ((failedMailsData?.total ?? 0) === 0) return null;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div className="flex items-center gap-2">
          <MailX className="h-4 w-4 text-destructive" />
          <div>
            <CardTitle>Failed Mails</CardTitle>
            <CardDescription>Emails that could not be processed</CardDescription>
          </div>
        </div>
        <Badge variant="destructive">{failedMailsData?.total ?? 0} unresolved</Badge>
      </CardHeader>
      <CardContent>
        {failedMailsQuery.isError ? (
          <QueryError message="Failed to load dead-letter queue." onRetry={() => failedMailsQuery.refetch()} />
        ) : failedMailsQuery.isLoading ? (
          <CardSkeleton />
        ) : !failedMailsData?.items?.length ? (
          <p className="text-sm text-muted-foreground">No failed mails.</p>
        ) : (
          <div className="space-y-3">
            {failedMailsData.items.map((fm) => (
              <div
                key={fm.id}
                className="flex items-start justify-between gap-4 rounded-md border border-destructive/20 bg-destructive/5 px-4 py-3"
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">
                      {fm.sender || `UID ${fm.mail_uid}`}
                    </span>
                    {fm.folder && (
                      <Badge variant="secondary" className="shrink-0">{fm.folder}</Badge>
                    )}
                  </div>
                  <p className="truncate text-xs text-muted-foreground">{fm.last_error}</p>
                  <p className="text-[11px] text-muted-foreground">
                    {fm.created_at ? formatRelativeTime(fm.created_at) : "Unknown time"}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <AppButton
                    icon={<RotateCcw />}
                    label="Retry"
                    variant="ghost"
                    disabled={retryFailedMutation.isPending && retryFailedMutation.variables?.trackedEmailId === fm.id}
                    loading={retryFailedMutation.isPending && retryFailedMutation.variables?.trackedEmailId === fm.id}
                    onClick={() => retryFailedMutation.mutate({ trackedEmailId: fm.id })}
                  />
                  <AppButton
                    icon={<XCircle />}
                    label="Dismiss"
                    variant="ghost"
                    disabled={resolveFailedMutation.isPending && resolveFailedMutation.variables?.trackedEmailId === fm.id}
                    loading={resolveFailedMutation.isPending && resolveFailedMutation.variables?.trackedEmailId === fm.id}
                    onClick={() => resolveFailedMutation.mutate({ trackedEmailId: fm.id })}
                  />
                </div>
              </div>
            ))}
            {(failedMailsData.pages ?? 1) > 1 && (
              <Pagination
                page={failedMailsData.page ?? 1}
                totalPages={failedMailsData.pages ?? 1}
                totalCount={failedMailsData.total ?? 0}
                onPageChange={setFailedPage}
                compact
                className="pt-1"
              />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
