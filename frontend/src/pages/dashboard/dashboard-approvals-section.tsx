import { Link } from "react-router";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, XCircle } from "lucide-react";

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
import { cn, formatRelativeTime, unwrapResponse } from "@/lib/utils";

import { CardSkeleton } from "./dashboard-helpers";
import {
  formatProposedAction,
  formatTimeRemaining,
  getActionConfig,
  isExpiringSoon,
} from "../approvals/approval-helpers";

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
            {approvalsData!.items.map((a) => {
              const actionConfig = getActionConfig(a.function_type);
              const proposedAction = formatProposedAction(
                a.proposed_action as Record<string, unknown>,
                a.function_type,
              );
              const expiringSoon = isExpiringSoon(a.expires_at);

              return (
                <div
                  key={a.id}
                  className={cn(
                    "flex items-start justify-between gap-4 rounded-md border px-4 py-3",
                    expiringSoon ? "border-yellow-500/50" : "border-border",
                  )}
                >
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium truncate">{a.mail_subject}</span>
                      <Badge variant={actionConfig.variant} className="shrink-0">
                        {actionConfig.label}
                      </Badge>
                    </div>
                    <p className="text-xs text-muted-foreground truncate">{proposedAction}</p>
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                      <span>{a.mail_from}</span>
                      <span>&middot;</span>
                      <span>{formatRelativeTime(a.created_at)}</span>
                      <span>&middot;</span>
                      <span className={cn(expiringSoon && "text-yellow-600 font-medium")}>
                        {formatTimeRemaining(a.expires_at)}
                      </span>
                    </div>
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
              );
            })}
            {(approvalsData!.total ?? 0) > 5 && (
              <p className="text-xs text-center text-muted-foreground">
                + {approvalsData!.total - 5} more pending &mdash;{" "}
                <Link to="/approvals" className="underline hover:text-foreground">
                  View all
                </Link>
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
