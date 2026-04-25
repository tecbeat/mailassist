import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Clock,
  CheckCircle2,
  Loader2,
  Inbox,
  Play,
  Timer,
  Info,
  MailX,
} from "lucide-react";

import {
  useGetJobQueueStatusApiDashboardJobsGet,
  useGetCronJobsApiDashboardCronsGet,
  useTriggerCronJobApiDashboardCronsCronNameTriggerPost,
  getGetCronJobsApiDashboardCronsGetQueryKey,
} from "@/services/api/dashboard/dashboard";
import type { JobQueueStatusResponse } from "@/types/api/jobQueueStatusResponse";
import type { CronJobsResponse } from "@/types/api/cronJobsResponse";

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
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { unwrapResponse, formatRelativeTime } from "@/lib/utils";
import { useToast } from "@/components/ui/toast";

import { jobLabel, CardSkeleton, JobStat } from "./dashboard-helpers";

// ---------------------------------------------------------------------------
// Cron Jobs + Job Queue (side-by-side grid)
// ---------------------------------------------------------------------------

export function DashboardJobsSection() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [processingPage, setProcessingPage] = useState(1);

  // --- Cron jobs ---
  const cronsQuery = useGetCronJobsApiDashboardCronsGet({
    query: { refetchInterval: 15000 },
  });
  const cronsData = unwrapResponse<CronJobsResponse>(cronsQuery.data);

  const triggerCronMutation = useTriggerCronJobApiDashboardCronsCronNameTriggerPost({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetCronJobsApiDashboardCronsGetQueryKey() });
      },
      onError: () => {
        toast({ title: "Trigger failed", description: "Could not trigger the cron job. Please try again.", variant: "destructive" });
      },
    },
  });

  // --- Job queue ---
  const jobsQuery = useGetJobQueueStatusApiDashboardJobsGet(
    { queue_page: 1, queue_per_page: 5 },
    { query: { refetchInterval: 5000 } },
  );
  const jobsData = unwrapResponse<JobQueueStatusResponse>(jobsQuery.data);
  const isProcessing = (jobsData?.in_progress ?? 0) > 0 || (jobsData?.queued ?? 0) > 0;

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* Cron Jobs */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Timer className="h-4 w-4 text-muted-foreground" />
            <CardTitle>Cron Jobs</CardTitle>
          </div>
          <CardDescription className="flex items-center gap-1.5">
            Scheduled background tasks running every {cronsData?.interval_minutes ?? "..."} minutes
            <Tooltip>
              <TooltipTrigger asChild>
                <Info className="h-3.5 w-3.5 shrink-0 cursor-help text-muted-foreground" />
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-xs">
                <p className="text-xs">
                  Cron jobs safely do nothing when no mail accounts or AI
                  providers are configured. They will start processing
                  automatically once you add an account and provider.
                  The interval is controlled by the CRON_INTERVAL_MINUTES
                  environment variable (requires worker restart).
                </p>
              </TooltipContent>
            </Tooltip>
          </CardDescription>
        </CardHeader>
        <CardContent>
          {cronsQuery.isError ? (
            <QueryError message="Failed to load cron job status." onRetry={() => cronsQuery.refetch()} />
          ) : cronsQuery.isLoading ? (
            <CardSkeleton />
          ) : !cronsData?.jobs?.length ? (
            <p className="text-sm text-muted-foreground">No cron job data available.</p>
          ) : (
            <div className="space-y-3">
              {cronsData.jobs.map((cron) => (
                <div
                  key={cron.name}
                  className="flex items-center justify-between gap-4 rounded-md border border-border px-4 py-3"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      {cron.is_running ? (
                        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-blue-500" />
                      ) : (
                        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-500" />
                      )}
                      <span className="text-sm font-medium">{cron.display_name}</span>
                      <Badge variant="secondary">{cron.schedule}</Badge>
                    </div>
                    <p className="mt-0.5 text-xs text-muted-foreground">{cron.description}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3">
                    <span className="text-xs text-muted-foreground">
                      {cron.last_run ? formatRelativeTime(cron.last_run) : "Never"}
                    </span>
                    <AppButton
                      icon={<Play />}
                      label="Run Now"
                      className="h-7 px-2 text-xs"
                      disabled={
                        cron.is_running ||
                        (triggerCronMutation.isPending && triggerCronMutation.variables?.cronName === cron.name)
                      }
                      loading={
                        triggerCronMutation.isPending && triggerCronMutation.variables?.cronName === cron.name
                      }
                      onClick={() => triggerCronMutation.mutate({ cronName: cron.name })}
                    >
                      Run Now
                    </AppButton>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Job queue */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            {isProcessing ? (
              <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
            ) : (
              <CheckCircle2 className="h-4 w-4 text-green-500" />
            )}
            <CardTitle>Job Queue</CardTitle>
          </div>
          <CardDescription>
            {isProcessing ? "Processing emails..." : "No active jobs"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {jobsQuery.isError ? (
            <QueryError message="Failed to load job queue status." onRetry={() => jobsQuery.refetch()} />
          ) : jobsQuery.isLoading ? (
            <CardSkeleton />
          ) : !jobsData ? (
            <p className="text-sm text-muted-foreground">No job queue data available.</p>
          ) : (
            <div className="space-y-4">
              {jobsData.error && (
                <div className="flex items-center gap-2 rounded border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-sm text-muted-foreground">
                  <AlertTriangle className="h-4 w-4 shrink-0 text-yellow-500" />
                  {jobsData.error}
                </div>
              )}
              <div className="grid grid-cols-3 gap-4">
                <JobStat
                  label="Queued"
                  value={jobsData.queued ?? 0}
                  icon={<Inbox className="h-4 w-4 text-muted-foreground" />}
                />
                <JobStat
                  label="Processing"
                  value={jobsData.in_progress ?? 0}
                  icon={
                    (jobsData.in_progress ?? 0) > 0
                      ? <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
                      : <Clock className="h-4 w-4 text-muted-foreground" />
                  }
                />
                <JobStat
                  label="Failed"
                  value={jobsData.failed_total ?? 0}
                  icon={<MailX className="h-4 w-4 text-destructive" />}
                />
              </div>
              {(jobsData.in_progress_jobs?.length ?? 0) > 0 && (
                <div className="space-y-1.5">
                  <p className="text-xs font-medium text-muted-foreground">
                    Currently processing {jobsData.in_progress_jobs!.length}{" "}
                    {jobsData.in_progress_jobs!.length === 1 ? "item" : "items"}
                  </p>
                  {(() => {
                    const PER_PAGE = 4;
                    const all = jobsData.in_progress_jobs!;
                    const totalPages = Math.max(1, Math.ceil(all.length / PER_PAGE));
                    const safePage = Math.min(processingPage, totalPages);
                    const offset = (safePage - 1) * PER_PAGE;
                    const visible = all.slice(offset, offset + PER_PAGE);
                    return (
                      <>
                        {visible.map((job) => (
                          <div
                            key={job.job_id}
                            className="rounded border border-border bg-muted/50 px-3 py-1.5"
                          >
                            <div className="flex items-center gap-2">
                              <Loader2 className="h-3 w-3 shrink-0 animate-spin text-blue-500" />
                              <span className="truncate text-xs">
                                {jobLabel(job.function ?? "", job.mail_uid)}
                              </span>
                            </div>
                            <div className="mt-1 pl-5">
                              {(() => {
                                const nPlugins = job.plugins_total ?? 8;
                                const totalSteps = nPlugins + 3;
                                let currentStep: number;
                                let label: string;

                                if (job.phase === "ai_pipeline" && job.plugin_index != null) {
                                  currentStep = 2 + job.plugin_index;
                                  label = `${job.plugin_index}/${nPlugins} ${job.current_plugin_display ?? job.current_plugin ?? ""}`;
                                } else if (job.phase === "imap_fetch") {
                                  currentStep = 2;
                                  label = "Fetching email...";
                                } else if (job.phase === "imap_actions") {
                                  currentStep = nPlugins + 3;
                                  label = "Executing IMAP actions...";
                                } else {
                                  currentStep = 1;
                                  label = "Preparing...";
                                }

                                const pct = (currentStep / totalSteps) * 100;

                                return (
                                  <>
                                    <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                                      <span>{label}</span>
                                    </div>
                                    <div className="mt-0.5 h-1 w-full rounded-full bg-muted">
                                      <div
                                        className="h-1 rounded-full bg-blue-500 transition-all duration-300"
                                        style={{ width: `${pct}%` }}
                                      />
                                    </div>
                                  </>
                                );
                              })()}
                            </div>
                          </div>
                        ))}
                        {totalPages > 1 && (
                          <Pagination
                            page={safePage}
                            totalPages={totalPages}
                            totalCount={all.length}
                            onPageChange={setProcessingPage}
                            compact
                            className="pt-1"
                          />
                        )}
                      </>
                    );
                  })()}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
