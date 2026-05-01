import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useUpdateConfigApiNotificationsConfigPut,
  getGetConfigApiNotificationsConfigGetQueryKey,
} from "@/services/api/notifications/notifications";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import type { NotifyOnConfig } from "@/types/api";

const NOTIFY_EVENT_LABELS: Record<keyof NotifyOnConfig, string> = {
  reply_needed: "Reply Needed",
  spam_detected: "Spam Detected",
  coupon_found: "Coupon Found",
  calendar_event_created: "Calendar Event Created",
  rule_executed: "Rule Executed",
  newsletter_detected: "Newsletter Detected",
  email_summary: "Email Summary",
  ai_error: "AI Error",
  contact_assigned: "Contact Assigned",
  approval_needed: "Approval Needed",
};

interface NotificationEventTogglesProps {
  /** Current event-enable flags from the server config. */
  notifyOn: NotifyOnConfig;
  /** Current custom templates (required when saving alongside notify_on). */
  currentTemplates: Record<string, string>;
}

/**
 * Debounced switches for enabling / disabling individual notification events.
 * Groups rapid toggling into a single API call after 500 ms of inactivity.
 */
export function NotificationEventToggles({
  notifyOn,
  currentTemplates,
}: NotificationEventTogglesProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const updateMutation = useUpdateConfigApiNotificationsConfigPut();

  const pendingTogglesRef = useRef<Partial<NotifyOnConfig>>({});
  const toggleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (toggleTimerRef.current) clearTimeout(toggleTimerRef.current);
    };
  }, []);

  function onToggleEvent(key: keyof NotifyOnConfig, value: boolean) {
    pendingTogglesRef.current = { ...pendingTogglesRef.current, [key]: value };
    if (toggleTimerRef.current) clearTimeout(toggleTimerRef.current);
    toggleTimerRef.current = setTimeout(async () => {
      const merged = { ...notifyOn, ...pendingTogglesRef.current };
      pendingTogglesRef.current = {};
      toggleTimerRef.current = null;
      try {
        await updateMutation.mutateAsync({
          data: { notify_on: merged, templates: currentTemplates },
        });
        queryClient.invalidateQueries({
          queryKey: getGetConfigApiNotificationsConfigGetQueryKey(),
        });
        toast({
          title: "Configuration saved",
          description: "Notification settings have been updated.",
        });
      } catch {
        toast({
          title: "Failed to save configuration",
          description:
            "Could not save the notification configuration. Please try again.",
          variant: "destructive",
        });
      }
    }, 500);
  }

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-medium">Notification Events</h4>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose which events trigger a notification.
        </p>
      </div>

      {(
        Object.entries(NOTIFY_EVENT_LABELS) as [keyof NotifyOnConfig, string][]
      ).map(([key, label]) => (
        <div key={key} className="flex items-center justify-between">
          <Label htmlFor={`event-${key}`} className="cursor-pointer">
            {label}
          </Label>
          <Switch
            id={`event-${key}`}
            checked={!!notifyOn[key]}
            onCheckedChange={(checked) => onToggleEvent(key, checked)}
            disabled={updateMutation.isPending}
          />
        </div>
      ))}
    </div>
  );
}
