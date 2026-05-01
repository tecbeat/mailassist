import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { Send } from "lucide-react";

import {
  useGetConfigApiNotificationsConfigGet,
  useTestNotificationApiNotificationsTestPost,
} from "@/services/api/notifications/notifications";

import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import {
  PluginSettingsDialog,
  PluginSettingsButton,
} from "@/components/plugin-settings-dialog";
import { AppButton } from "@/components/app-button";
import { Separator } from "@/components/ui/separator";

import type { NotificationConfigResponse, NotifyOnConfig } from "@/types/api";
import { unwrapResponse } from "@/lib/utils";

import { TemplateEditor } from "@/components/notifications/template-editor";
import { NotificationUrlManager } from "@/components/notifications/notification-url-manager";
import { NotificationEventToggles } from "@/components/notifications/notification-event-toggles";

export default function NotificationsPage() {
  usePageTitle("Notifications");
  const { toast } = useToast();

  const [settingsOpen, setSettingsOpen] = useState(false);

  const configQuery = useGetConfigApiNotificationsConfigGet();
  const config = unwrapResponse<NotificationConfigResponse>(configQuery.data);
  const testMutation = useTestNotificationApiNotificationsTestPost();

  function currentUrls(): string[] {
    return config?.apprise_urls ?? [];
  }

  function currentNotifyOn(): NotifyOnConfig {
    return (config?.notify_on ?? {}) as NotifyOnConfig;
  }

  function currentTemplates(): Record<string, string> {
    return (config?.templates ?? {}) as Record<string, string>;
  }

  async function onSendTestNotification() {
    try {
      const res = await testMutation.mutateAsync({
        data: { message: "Test notification from mailassist" },
      });
      const result = unwrapResponse<{ success: boolean; message: string }>(res);
      if (result?.success) {
        toast({ title: "Test notification sent", description: result.message });
      } else {
        toast({ title: "Test failed", description: result?.message, variant: "destructive" });
      }
    } catch {
      toast({
        title: "Failed to send test notification",
        description:
          "An error occurred while sending the test. Please check your configuration.",
        variant: "destructive",
      });
    }
  }

  if (configQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Notifications"
          description="Configure notification channels and event triggers."
          actions={
            <div className="flex items-center gap-2">
              <PluginSettingsButton onClick={() => setSettingsOpen(true)} />
              <AppButton icon={<Send />} label="Send Test" variant="primary" disabled>
                Send Test
              </AppButton>
            </div>
          }
        />
        <QueryError
          message="Failed to load notification settings."
          onRetry={() => configQuery.refetch()}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notifications"
        description="Configure notification channels and event triggers."
        actions={
          <div className="flex items-center gap-2">
            <PluginSettingsButton onClick={() => setSettingsOpen(true)} />
            <AppButton
              icon={<Send />}
              label="Send Test"
              variant="primary"
              loading={testMutation.isPending}
              disabled={testMutation.isPending || !currentUrls().length}
              onClick={onSendTestNotification}
            >
              Send Test
            </AppButton>
          </div>
        }
      />

      <TemplateEditor />

      <PluginSettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        title="Notification Settings"
        description="Configure notification channels and choose which events trigger notifications."
      >
        <div className="space-y-6">
          <NotificationUrlManager urls={currentUrls()} />
          <Separator />
          <NotificationEventToggles
            notifyOn={currentNotifyOn()}
            currentTemplates={currentTemplates()}
          />
        </div>
      </PluginSettingsDialog>
    </div>
  );
}
