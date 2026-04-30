import { useCallback, useSyncExternalStore } from "react";
import { customInstance } from "@/services/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type PollJobStatus = "queued" | "in_progress" | "complete" | "failed" | "not_found";

interface PollJobStatusResponse {
  data: { status: PollJobStatus; error?: string | null };
}

interface ActiveOperation {
  type: "test" | "poll";
  accountId: string;
  jobId?: string;
}

type OperationCallbacks = {
  onPollComplete?: (accountId: string) => void;
  onPollFailed?: (accountId: string, error?: string | null) => void;
  onTestComplete?: (accountId: string) => void;
  onTestFailed?: (accountId: string) => void;
};

// ---------------------------------------------------------------------------
// Module-level store (survives component unmounts)
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 2_000;

let operations: Map<string, ActiveOperation> = new Map();
let listeners: Set<() => void> = new Set();
let pollTimer: ReturnType<typeof setInterval> | null = null;
let callbacksRef: OperationCallbacks = {};

function getSnapshot(): Map<string, ActiveOperation> {
  return operations;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

function notify(): void {
  for (const listener of listeners) {
    listener();
  }
}

function startPolling(): void {
  if (pollTimer !== null) return;
  pollTimer = setInterval(async () => {
    const pollOps = Array.from(operations.values()).filter(
      (op) => op.type === "poll" && op.jobId,
    );
    for (const op of pollOps) {
      try {
        const res = await customInstance<PollJobStatusResponse>(
          `/api/mail-accounts/${op.accountId}/poll-status?job_id=${encodeURIComponent(op.jobId!)}`,
        );
        const status = res.data.status;
        if (status === "complete") {
          operations = new Map(operations);
          operations.delete(makeKey("poll", op.accountId));
          notify();
          stopPollingIfIdle();
          callbacksRef.onPollComplete?.(op.accountId);
        } else if (status === "failed" || status === "not_found") {
          const error = res.data.error;
          operations = new Map(operations);
          operations.delete(makeKey("poll", op.accountId));
          notify();
          stopPollingIfIdle();
          callbacksRef.onPollFailed?.(op.accountId, error);
        }
        // queued / in_progress → keep polling
      } catch {
        // Network error — keep polling, don't remove the job
      }
    }
  }, POLL_INTERVAL_MS);
}

function stopPollingIfIdle(): void {
  const hasPollJobs = Array.from(operations.values()).some(
    (op) => op.type === "poll" && op.jobId,
  );
  if (!hasPollJobs && pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function makeKey(type: "test" | "poll", accountId: string): string {
  return `${type}:${accountId}`;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

function startTestOperation(accountId: string): void {
  operations = new Map(operations);
  operations.set(makeKey("test", accountId), { type: "test", accountId });
  notify();
}

function completeTestOperation(accountId: string): void {
  operations = new Map(operations);
  operations.delete(makeKey("test", accountId));
  notify();
  callbacksRef.onTestComplete?.(accountId);
}

function failTestOperation(accountId: string): void {
  operations = new Map(operations);
  operations.delete(makeKey("test", accountId));
  notify();
  callbacksRef.onTestFailed?.(accountId);
}

function startPollOperationPending(accountId: string): void {
  operations = new Map(operations);
  operations.set(makeKey("poll", accountId), { type: "poll", accountId });
  notify();
}

function completePollMutation(accountId: string, jobId: string): void {
  // Mutation completed — upgrade to job tracking
  operations = new Map(operations);
  operations.set(makeKey("poll", accountId), { type: "poll", accountId, jobId });
  notify();
  startPolling();
}

function failPollMutation(accountId: string): void {
  operations = new Map(operations);
  operations.delete(makeKey("poll", accountId));
  notify();
  stopPollingIfIdle();
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UseAccountOperationsReturn {
  isTestLoading: (accountId: string) => boolean;
  isPollLoading: (accountId: string) => boolean;
  startTest: (accountId: string) => void;
  completeTest: (accountId: string) => void;
  failTest: (accountId: string) => void;
  startPollPending: (accountId: string) => void;
  completePollWithJob: (accountId: string, jobId: string) => void;
  failPoll: (accountId: string) => void;
  setCallbacks: (callbacks: OperationCallbacks) => void;
}

export function useAccountOperations(): UseAccountOperationsReturn {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  const isTestLoading = useCallback(
    (accountId: string) => snapshot.has(makeKey("test", accountId)),
    [snapshot],
  );

  const isPollLoading = useCallback(
    (accountId: string) => snapshot.has(makeKey("poll", accountId)),
    [snapshot],
  );

  const setCallbacks = useCallback((callbacks: OperationCallbacks) => {
    callbacksRef = callbacks;
  }, []);

  return {
    isTestLoading,
    isPollLoading,
    startTest: startTestOperation,
    completeTest: completeTestOperation,
    failTest: failTestOperation,
    startPollPending: startPollOperationPending,
    completePollWithJob: completePollMutation,
    failPoll: failPollMutation,
    setCallbacks,
  };
}
