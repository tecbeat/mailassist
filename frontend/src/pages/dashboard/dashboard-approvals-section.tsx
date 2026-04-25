import { Link } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  XCircle,
} from "lucide-react";

import {
  useListApprovalsApiApprovalsGet,
  useApproveActionApiApprovalsApprovalIdApprovePost,
  useRejectActionApiApprovalsApprovalIdRejectPost,
} from "@/services/api/approvals/approvals";
import type { ApprovalListResponse } from "@/types/api/approvalListResponse";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AppButton } from "@/components/app-button";
import { QueryError } from "@/components/query-error";
import { useToast } from "@/components/ui/toast";
import { formatRelativeTime, unwrapResponse } from "@/lib/utils";

import { actionLabel, CardSkeleton } from "./dashboard-helpers";

// ---------------------------------------------------------------------------
// Pending Approvals Section
// ---------------------------------------------------------------------------

export function DashboardApprovalsSection() {
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const approvalsQuery = useListApprovalsApiApprovalsGet({
    status: "pending",
    per_page: 5,
  });
  const approvalsData = unwrapResponse<ApprovalListResponse>(approvalsQuery.data);

  const approveAction = useApproveActionApiApprovalsApprovalIdApprovePost();
  const rejectAction = useRejectActionApiApprovalsApprovalIdRejectPost();

  // Hide section if no data to show
  if (!approvalsQuery.isLoading && !approvalsQuery.isError && !(approvalsData?.items?.length)) {
    return null;
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Pending Approvals</CardTitle>
          <CardDescription>AI actions waiting for your review</CardDescription>
        </div>
        <AppButton icon={<ArrowRight />} label="View all" asChild>
          <Link to="/approvals">View all</Link>
        </AppButton>
      </CardHeader>
      <CardContent>
        {approvalsQuery.isError ? (
          <QueryError message="Failed to load approvals." onRetry={() => approvalsQuery.refetch()} />
        ) : approvalsQuery.isLoading ? (
          <CardSkeleton />
        ) : (
          <div className="space-y-3">
            {approvalsData!.items.map((a) => (
              <div
                key={a.id}
                className="flex items-start justify-between gap-4 rounded-md border border-border px-4 py-3"
              >
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium truncate">{a.mail_subject}</span>
                    <Badge variant="secondary" className="shrink-0">
                      {actionLabel(a.function_type)}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground truncate">{a.mail_from}</p>
                  <p className="text-[11px] text-muted-foreground">{formatRelativeTime(a.created_at)}</p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <AppButton
                    icon={<Check />}
                    label="Approve"
                    variant="ghost"
                    loading={approveAction.isPending && approveAction.variables?.approvalId === a.id}
                    disabled={approveAction.isPending || rejectAction.isPending}
                    onClick={() =>
                      approveAction.mutate(
                        { approvalId: a.id },
                        {
                          onSuccess: () => {
                            toast({ title: "Approved", description: "The action has been approved and will be executed." });
                            queryClient.invalidateQueries({ queryKey: ["/api/approvals"] });
                            queryClient.invalidateQueries({ queryKey: ["dashboard", "stats"] });
                          },
                          onError: () => toast({ title: "Approval failed", description: "Could not approve the action. Please try again.", variant: "destructive" }),
                        },
                      )
                    }
                  />
                  <AppButton
                    icon={<XCircle />}
                    label="Reject"
                    variant="ghost"
                    loading={rejectAction.isPending && rejectAction.variables?.approvalId === a.id}
                    disabled={approveAction.isPending || rejectAction.isPending}
                    onClick={() =>
                      rejectAction.mutate(
                        { approvalId: a.id },
                        {
                          onSuccess: () => {
                            toast({ title: "Rejected", description: "The action has been rejected." });
                            queryClient.invalidateQueries({ queryKey: ["/api/approvals"] });
                            queryClient.invalidateQueries({ queryKey: ["dashboard", "stats"] });
                          },
                          onError: () => toast({ title: "Rejection failed", description: "Could not reject the action. Please try again.", variant: "destructive" }),
                        },
                      )
                    }
                  />
                </div>
              </div>
            ))}
            {(approvalsData!.total ?? 0) > 5 && (
              <p className="text-xs text-muted-foreground">
                + {approvalsData!.total - 5} more pending
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
