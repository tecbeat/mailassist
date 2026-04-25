import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardHeader,
} from "@/components/ui/card";
import { formatNumber } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TimePeriod = "24h" | "7d" | "30d";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Human-readable labels for known ARQ task function names. */
export const JOB_DISPLAY_NAMES: Record<string, string> = {
  process_mail: "Process Mail",
  poll_mail_accounts: "Poll Mail Accounts",
  poll_single_account: "Poll Account",
  sync_contacts: "Sync Contacts",
  cleanup_drafts: "Cleanup Drafts",
  execute_approved_actions: "Execute Approval",
  handle_spam_rejection: "Spam Rejection",
  worker_health_check: "Health Check",
};

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

/** Return a display label for a job queue entry. */
export function jobLabel(fn: string, mailUid?: string | null): string {
  if (fn === "process_mail" && mailUid) return `Mail UID ${mailUid}`;
  return JOB_DISPLAY_NAMES[fn] ?? fn.replace(/_/g, " ");
}

export function actionLabel(type: string): string {
  return type
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Skeleton loaders
// ---------------------------------------------------------------------------

export function StatsSkeletons() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i}>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-4 w-4 rounded-full" />
          </CardHeader>
          <CardContent>
            <Skeleton className="h-7 w-16" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="h-4 w-4 rounded-full" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// JobStat
// ---------------------------------------------------------------------------

export function JobStat({
  label,
  value,
  icon,
  suffix,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  suffix?: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-muted/30 px-3 py-2">
      {icon}
      <div>
        <p className="text-lg font-bold leading-tight">
          {formatNumber(value)}
          {suffix}
        </p>
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
    </div>
  );
}
