import type React from "react";
import {
  Tag,
  FolderInput,
  Mail,
  Calendar,
  MessageSquare,
  BrainCircuit,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const STATUS_TABS = [
  { value: "pending", label: "Pending" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "expired", label: "Expired" },
  { value: "all", label: "All" },
] as const;

export type StatusFilter = (typeof STATUS_TABS)[number]["value"];

export const AUTO_REFRESH_MS = 30_000;

// ---------------------------------------------------------------------------
// Badge variant type
// ---------------------------------------------------------------------------

export type BadgeVariant =
  | "default"
  | "secondary"
  | "destructive"
  | "success"
  | "warning";

// ---------------------------------------------------------------------------
// Action type config
// ---------------------------------------------------------------------------

const ACTION_TYPE_CONFIG: Record<
  string,
  { icon: React.ReactNode; variant: BadgeVariant; label: string }
> = {
  labeling: { icon: <Tag />, variant: "secondary", label: "Label" },
  smart_folder: { icon: <FolderInput />, variant: "warning", label: "Smart Folders" },
  auto_reply: { icon: <MessageSquare />, variant: "secondary", label: "Auto Reply" },
  spam_detection: { icon: <Mail />, variant: "destructive", label: "Spam Detection" },
  newsletter_detection: { icon: <Mail />, variant: "secondary", label: "Newsletter" },
  coupon_extraction: { icon: <Tag />, variant: "secondary", label: "Coupon" },
  calendar_extraction: { icon: <Calendar />, variant: "secondary", label: "Calendar" },
  email_summary: { icon: <Mail />, variant: "secondary", label: "Summary" },
  contacts: { icon: <Mail />, variant: "secondary", label: "Contacts" },
  notifications: { icon: <MessageSquare />, variant: "warning", label: "Notify" },
};

export function getActionConfig(type: string) {
  return (
    ACTION_TYPE_CONFIG[type] ?? {
      icon: <BrainCircuit />,
      variant: "secondary" as BadgeVariant,
      label: type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    }
  );
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

export function formatProposedAction(
  action: Record<string, unknown>,
  functionType: string,
): string {
  switch (functionType) {
    case "labeling":
      return `Apply label: ${action.label_name ?? action.label ?? ""}`;
    case "smart_folder":
      return `Move to: ${action.folder ?? action.destination ?? ""}`;
    case "auto_reply":
      return action.body
        ? String(action.body).slice(0, 120) +
            (String(action.body).length > 120 ? "..." : "")
        : "Draft content available";
    case "calendar_extraction":
      return `Event: ${action.summary ?? action.title ?? ""}`;
    case "notifications":
      return `Notification: ${action.message ?? action.body ?? ""}`;
    case "spam_detection":
      if (action.is_spam === undefined) {
        return action.reason ? String(action.reason) : "Spam check result";
      }
      return `Spam: ${action.is_spam ? "Yes" : "No"}${action.reason ? ` — ${action.reason}` : ""}`;
    case "newsletter_detection":
      return `Newsletter: ${action.is_newsletter ? "Yes" : "No"}`;
    case "coupon_extraction":
      return `Coupon: ${action.code ?? action.description ?? ""}`;
    case "email_summary":
      return action.summary
        ? String(action.summary).slice(0, 120) +
            (String(action.summary).length > 120 ? "..." : "")
        : "Summary available";
    case "contacts": {
      const cName = action.contact_name ?? action.name ?? "";
      const cConf = action.confidence != null ? ` (${Math.round(Number(action.confidence) * 100)}%)` : "";
      const cNew = action.is_new_contact_suggestion ? " [new]" : "";
      return `Contact: ${cName}${cConf}${cNew}`;
    }
    default: {
      const entries = Object.entries(action).filter(
        ([k]) => k !== "type" && k !== "action_type",
      );
      if (entries.length === 0) return "No additional details";
      return entries
        .map(([k, v]) => `${k}: ${String(v)}`)
        .join(", ")
        .slice(0, 150);
    }
  }
}

export function formatTimeRemaining(expiresAt: string): string {
  const now = new Date();
  const expires = new Date(expiresAt);
  const diffMs = expires.getTime() - now.getTime();

  if (diffMs <= 0) return "Expired";

  const diffMin = Math.floor(diffMs / 60_000);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffDay > 0) return `${diffDay}d ${diffHour % 24}h left`;
  if (diffHour > 0) return `${diffHour}h ${diffMin % 60}m left`;
  return `${diffMin}m left`;
}

export function isExpiringSoon(expiresAt: string): boolean {
  const diffMs = new Date(expiresAt).getTime() - Date.now();
  return diffMs > 0 && diffMs < 3_600_000;
}
