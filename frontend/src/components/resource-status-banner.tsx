/**
 * Unified status banner for mail accounts and AI providers.
 *
 * Shows pause info, circuit-breaker state, and error details with
 * action buttons (Unpause / Reset & Reactivate / Clear errors).
 */

import { useState } from "react";
import {
  PauseCircle,
  ShieldAlert,
  RotateCcw,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { AppButton } from "@/components/app-button";
import { formatRelativeTime } from "@/lib/utils";

export interface ResourceStatusProps {
  /** Whether the resource is paused. */
  isPaused: boolean;
  pausedReason?: string | null;
  pausedAt?: string | null;

  /** Consecutive error count. */
  consecutiveErrors: number;
  lastError?: string | null;
  lastErrorAt?: string | null;
  onResetHealth?: () => void;
  resetHealthLoading?: boolean;
}

/** Max characters shown before truncation. */
const ERROR_TRUNCATE_LENGTH = 200;

function CollapsibleError({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const needsTruncation = text.length > ERROR_TRUNCATE_LENGTH;

  return (
    <div className="space-y-1">
      <div className="rounded-md bg-muted px-3 py-2 font-mono whitespace-pre-wrap break-all text-foreground/70">
        {needsTruncation && !expanded
          ? `${text.slice(0, ERROR_TRUNCATE_LENGTH)}…`
          : text}
      </div>
      {needsTruncation && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          {expanded ? (
            <>
              <ChevronUp className="h-3 w-3" /> Show less
            </>
          ) : (
            <>
              <ChevronDown className="h-3 w-3" /> Show more
            </>
          )}
        </button>
      )}
    </div>
  );
}

export function ResourceStatusBanner({
  isPaused,
  pausedReason,
  pausedAt,
  consecutiveErrors,
  lastError,
  onResetHealth,
  resetHealthLoading,
}: ResourceStatusProps) {
  const isCircuitBroken = isPaused && pausedReason === "circuit_breaker";
  const hasErrors = consecutiveErrors > 0;

  // Only show banner when paused
  if (!isPaused) return null;

  return (
    <div className="space-y-2">
      {/* Circuit breaker banner */}
      {isCircuitBroken && (
        <div className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive space-y-1.5">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
            <span className="flex-1">
              Deactivated by circuit breaker ({consecutiveErrors} consecutive
              errors). Reset health to re-activate.
            </span>
            {onResetHealth && (
              <AppButton
                icon={<RotateCcw />}
                label="Reset & Reactivate"
                size="sm"
                loading={resetHealthLoading}
                disabled={resetHealthLoading}
                className="ml-auto h-6 gap-1 text-xs shrink-0"
                onClick={onResetHealth}
              >
                Reset &amp; Reactivate
              </AppButton>
            )}
          </div>
          {lastError && <CollapsibleError text={lastError} />}
        </div>
      )}

      {/* Pause banner (non-circuit-breaker) — red when errors present */}
      {isPaused && !isCircuitBroken && (
        <div
          className={`rounded-md px-3 py-2 text-xs space-y-1.5 ${
            hasErrors
              ? "bg-destructive/10 text-destructive"
              : "bg-amber-500/10 text-amber-700 dark:text-amber-400"
          }`}
        >
          <div className="flex items-start gap-2">
            <PauseCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <span className="font-medium">Paused</span>
              {pausedReason && <span> &mdash; {pausedReason}</span>}
              {pausedAt && (
                <span className="text-muted-foreground ml-1">
                  (since {formatRelativeTime(pausedAt)})
                </span>
              )}
              {hasErrors && (
                <span className="text-muted-foreground ml-1">
                  &middot; {consecutiveErrors} error(s)
                </span>
              )}
            </div>
          </div>
          {lastError && <CollapsibleError text={lastError} />}
        </div>
      )}
    </div>
  );
}
