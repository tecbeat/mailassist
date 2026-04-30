import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatRelativeTime(date: string | Date): string {
  const now = new Date();
  const d = typeof date === "string" ? new Date(date) : date;

  // Guard: invalid date
  if (isNaN(d.getTime())) return "unknown";

  const diffMs = now.getTime() - d.getTime();
  const absDiffMs = Math.abs(diffMs);
  const isFuture = diffMs < 0;

  const diffSec = Math.floor(absDiffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  // Future dates
  if (isFuture) {
    if (diffSec < 60) return "just now";
    if (diffMin < 60) return `in ${diffMin}m`;
    if (diffHour < 24) return `in ${diffHour}h`;
    return `in ${diffDay}d`;
  }

  // Past dates
  if (diffSec < 60) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  if (diffDay < 7) return `${diffDay}d ago`;
  return d.toLocaleDateString();
}

export function formatNumber(n: number | null | undefined): string {
  if (n == null) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toString();
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Unwrap Orval's { data: T } response envelope. */
export function unwrapResponse<T>(
  response: unknown,
): T | undefined {
  return (response as { data?: T } | undefined)?.data;
}
