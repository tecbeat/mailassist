import { useState } from "react";
import { Bell, Eye, EyeOff, Plus, Send, Trash2 } from "lucide-react";
import { z } from "zod/v4";
import { useQueryClient } from "@tanstack/react-query";

import {
  addUrlApiNotificationsConfigUrlsPost,
  removeUrlApiNotificationsConfigUrlsIndexDelete,
  getGetConfigApiNotificationsConfigGetQueryKey,
  useTestNotificationApiNotificationsTestPost,
} from "@/services/api/notifications/notifications";
import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/components/ui/toast";
import { unwrapResponse } from "@/lib/utils";

interface NotificationUrlManagerProps {
  /** Current Apprise URLs from the server config. */
  urls: string[];
}

const webhookUrlSchema = z
  .string()
  .min(1, "URL is required")
  .url("Must be a valid URL");

/** Manages the list of Apprise notification URLs: add, remove, reveal, test. */
export function NotificationUrlManager({ urls }: NotificationUrlManagerProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const testMutation = useTestNotificationApiNotificationsTestPost();

  const [showUrls, setShowUrls] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [isAddingUrl, setIsAddingUrl] = useState(false);
  const [removingUrlIndex, setRemovingUrlIndex] = useState<number | null>(null);
  const [testingUrl, setTestingUrl] = useState<string | null>(null);

  function invalidateConfig() {
    queryClient.invalidateQueries({
      queryKey: getGetConfigApiNotificationsConfigGetQueryKey(),
    });
  }

  async function onAddUrl(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const formData = new FormData(form);
    const url = formData.get("url") as string;
    const parsed = webhookUrlSchema.safeParse(url?.trim());
    if (!parsed.success) {
      setUrlError(parsed.error.issues[0]?.message ?? "Invalid URL");
      return;
    }
    setUrlError(null);
    setIsAddingUrl(true);
    try {
      await addUrlApiNotificationsConfigUrlsPost({ url: parsed.data });
      invalidateConfig();
      toast({
        title: "URL added",
        description: "The webhook URL has been added to the notification list.",
      });
      form.reset();
    } catch {
      toast({
        title: "Failed to add URL",
        description: "Could not add the webhook URL. Please try again.",
        variant: "destructive",
      });
    } finally {
      setIsAddingUrl(false);
    }
  }

  async function onRemoveUrl(index: number) {
    setRemovingUrlIndex(index);
    try {
      await removeUrlApiNotificationsConfigUrlsIndexDelete(index);
      invalidateConfig();
      toast({ title: "URL removed", description: "The webhook URL has been removed." });
    } catch {
      toast({
        title: "Failed to remove URL",
        description: "Could not remove the webhook URL. Please try again.",
        variant: "destructive",
      });
    } finally {
      setRemovingUrlIndex(null);
    }
  }

  async function onTestUrl(url: string) {
    setTestingUrl(url);
    try {
      const res = await testMutation.mutateAsync({
        data: { message: "Test notification from mailassist" },
      });
      const result = unwrapResponse<{ success: boolean; message: string }>(res);
      if (result?.success) {
        toast({ title: "Test sent", description: result.message });
      } else {
        toast({
          title: "Test failed",
          description: result?.message ?? "Unknown error",
          variant: "destructive",
        });
      }
    } catch {
      toast({
        title: "Test failed",
        description: "Could not reach the webhook endpoint.",
        variant: "destructive",
      });
    } finally {
      setTestingUrl(null);
    }
  }

  return (
    <div className="space-y-3">
      <div>
        <h4 className="flex items-center gap-2 text-sm font-medium">
          <Bell className="h-4 w-4" />
          Notification URLs
        </h4>
        <p className="mt-1 text-sm text-muted-foreground">
          Add Apprise-compatible notification URLs (max 10). Each URL represents a
          notification channel (e.g. Telegram, Discord, email).
        </p>
      </div>

      {urls.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No notification URLs configured yet.
        </p>
      )}

      {urls.length > 0 && (
        <div className="flex justify-end">
          <AppButton
            icon={showUrls ? <EyeOff /> : <Eye />}
            label={showUrls ? "Hide URLs" : "Reveal URLs"}
            variant="ghost"
            onClick={() => setShowUrls((v) => !v)}
          >
            {showUrls ? "Hide" : "Reveal"}
          </AppButton>
        </div>
      )}

      {urls.map((url, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input
            type={showUrls ? "text" : "password"}
            value={url}
            readOnly
            className="flex-1 font-mono text-sm"
          />
          <AppButton
            icon={<Send />}
            label="Test notification URL"
            variant="ghost"
            loading={testingUrl === url}
            onClick={() => onTestUrl(url)}
            disabled={testingUrl === url}
          />
          <AppButton
            icon={<Trash2 />}
            label="Remove notification URL"
            variant="ghost"
            color="destructive"
            onClick={() => onRemoveUrl(index)}
            disabled={removingUrlIndex !== null}
            loading={removingUrlIndex === index}
          />
        </div>
      ))}

      {urls.length < 10 && (
        <>
          <Separator />
          <form onSubmit={onAddUrl} className="flex items-start gap-2">
            <div className="flex-1">
              <Input
                name="url"
                placeholder="apprise://service/token..."
                className="font-mono text-sm"
                onChange={() => setUrlError(null)}
              />
              {urlError && (
                <p className="mt-1 text-xs text-destructive">{urlError}</p>
              )}
            </div>
            <AppButton
              icon={<Plus />}
              label="Add URL"
              type="submit"
              variant="primary"
              disabled={isAddingUrl}
              loading={isAddingUrl}
            >
              Add
            </AppButton>
          </form>
        </>
      )}
    </div>
  );
}
