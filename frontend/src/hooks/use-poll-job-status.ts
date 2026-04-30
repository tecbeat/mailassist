import { useCallback, useEffect, useRef, useState } from "react";
import { customInstance } from "@/services/client";

type PollJobStatus = "queued" | "in_progress" | "complete" | "failed" | "not_found";

interface PollJobStatusResponse {
  data: { status: PollJobStatus; error?: string | null };
}

interface PollJob {
  accountId: string;
  jobId: string;
}

interface UsePollJobStatusReturn {
  /** Account IDs currently being polled (job active). */
  pollingAccounts: Set<string>;
  /** Start tracking a poll job for an account. */
  trackJob: (accountId: string, jobId: string) => void;
  /** Whether a specific account has an active poll job. */
  isPolling: (accountId: string) => boolean;
}

const POLL_INTERVAL_MS = 2_000;

/**
 * Tracks ARQ poll job status for mail accounts.
 *
 * After a poll is triggered, call `trackJob(accountId, jobId)` to start
 * polling the backend status endpoint. Calls `onComplete`/`onFailed`
 * when the job finishes, then stops polling for that account.
 */
export function usePollJobStatus(callbacks: {
  onComplete: (accountId: string) => void;
  onFailed: (accountId: string, error?: string | null) => void;
}): UsePollJobStatusReturn {
  const [pollingAccounts, setPollingAccounts] = useState<Set<string>>(new Set());
  const jobsRef = useRef<Map<string, PollJob>>(new Map());
  const callbacksRef = useRef(callbacks);
  callbacksRef.current = callbacks;

  const trackJob = useCallback((accountId: string, jobId: string) => {
    jobsRef.current.set(accountId, { accountId, jobId });
    setPollingAccounts((prev) => new Set(prev).add(accountId));
  }, []);

  const isPolling = useCallback(
    (accountId: string) => pollingAccounts.has(accountId),
    [pollingAccounts],
  );

  useEffect(() => {
    if (pollingAccounts.size === 0) return;

    const timer = setInterval(async () => {
      const jobs = Array.from(jobsRef.current.values());
      for (const job of jobs) {
        try {
          const res = await customInstance<PollJobStatusResponse>(
            `/api/mail-accounts/${job.accountId}/poll-status?job_id=${encodeURIComponent(job.jobId)}`,
          );
          const status = res.data.status;
          if (status === "complete") {
            jobsRef.current.delete(job.accountId);
            setPollingAccounts((prev) => {
              const next = new Set(prev);
              next.delete(job.accountId);
              return next;
            });
            callbacksRef.current.onComplete(job.accountId);
          } else if (status === "failed" || status === "not_found") {
            const error = res.data.error;
            jobsRef.current.delete(job.accountId);
            setPollingAccounts((prev) => {
              const next = new Set(prev);
              next.delete(job.accountId);
              return next;
            });
            callbacksRef.current.onFailed(job.accountId, error);
          }
          // queued / in_progress → keep polling
        } catch {
          // Network error — keep polling, don't remove the job
        }
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(timer);
  }, [pollingAccounts]);

  return { pollingAccounts, trackJob, isPolling };
}
