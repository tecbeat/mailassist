import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { Bell, ChevronDown, ChevronRight, Plus, Send, Trash2 } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import { AppButton } from "@/components/app-button";
import { AppDialog } from "@/components/app-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/components/ui/toast";

import { useListMailAccountsApiMailAccountsGet } from "@/services/api/mail-accounts/mail-accounts";
import { unwrapResponse } from "@/lib/utils";
import type { MailAccountResponse } from "@/types/api";

import { TemplateEditor } from "@/components/notifications/template-editor";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NotificationChannel {
  id: string;
  url: string;
  mail_account_ids: string[] | null;
  event_types: string[] | null;
  created_at: string;
  updated_at: string;
}

interface NotificationEventInfo {
  event_type: string;
  plugin_name: string;
  display_name: string;
  execution_order: number;
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const API_BASE = "/api/notifications";

/** Read CSRF token from cookie. */
function getCsrfToken(): string | undefined {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrf_token="));
  return match?.split("=")[1];
}

/** Fetch wrapper that includes credentials and CSRF token. */
async function apiFetch(url: string, options?: RequestInit): Promise<Response> {
  const method = (options?.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    ...(options?.headers as Record<string, string> | undefined),
  };
  if (options?.body && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrf = getCsrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  return fetch(url, { ...options, headers, credentials: "include" });
}

async function fetchChannels(): Promise<NotificationChannel[]> {
  const res = await apiFetch(`${API_BASE}/channels`);
  if (!res.ok) throw new Error("Failed to load channels");
  return res.json();
}

async function createChannel(data: {
  url: string;
  mail_account_ids: string[] | null;
  event_types: string[] | null;
}): Promise<NotificationChannel> {
  const res = await apiFetch(`${API_BASE}/channels`, {
    method: "POST",
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create channel");
  return res.json();
}

async function updateChannel(
  id: string,
  data: { mail_account_ids: string[] | null; event_types: string[] | null },
): Promise<NotificationChannel> {
  const res = await apiFetch(`${API_BASE}/channels/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(body || `Failed to update channel (${res.status})`);
  }
  return res.json();
}

async function deleteChannel(id: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/channels/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete channel");
}

async function testChannel(id: string): Promise<{ success: boolean; message: string }> {
  const res = await apiFetch(`${API_BASE}/channels/${id}/test`, {
    method: "POST",
    body: JSON.stringify({ message: "Test notification from mailassist" }),
  });
  if (!res.ok) throw new Error("Failed to send test");
  return res.json();
}

async function fetchEvents(): Promise<NotificationEventInfo[]> {
  const res = await apiFetch(`${API_BASE}/events`);
  if (!res.ok) throw new Error("Failed to load events");
  return res.json();
}

// ---------------------------------------------------------------------------
// Channel Item (expandable, autosave on toggle)
// ---------------------------------------------------------------------------

interface ChannelItemProps {
  channel: NotificationChannel;
  accounts: MailAccountResponse[];
  events: NotificationEventInfo[];
}

function ChannelItem({ channel, accounts, events }: ChannelItemProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [testing, setTesting] = useState(false);

  const allAccountIds = accounts.map((a) => a.id);
  const allEventTypes = events.map((e) => e.event_type);

  const currentAccountIds = channel.mail_account_ids ?? allAccountIds;
  const currentEventTypes = channel.event_types ?? allEventTypes;

  const deleteMutation = useMutation({
    mutationFn: () => deleteChannel(channel.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-channels"] });
      toast({ title: "Channel deleted", description: "Notification channel has been removed." });
    },
    onError: () => {
      toast({ title: "Failed to delete", description: "Could not delete the channel.", variant: "destructive" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (data: { mail_account_ids: string[] | null; event_types: string[] | null }) =>
      updateChannel(channel.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-channels"] });
    },
    onError: (err: Error) => {
      toast({ title: "Failed to save", description: err.message || "Could not save channel settings.", variant: "destructive" });
    },
  });

  function saveAccountIds(newIds: string[]) {
    const apiIds = newIds.length === allAccountIds.length && allAccountIds.every((id) => newIds.includes(id)) ? null : newIds;
    const apiEvents = currentEventTypes.length === allEventTypes.length && allEventTypes.every((t) => currentEventTypes.includes(t)) ? null : currentEventTypes;
    updateMutation.mutate({ mail_account_ids: apiIds, event_types: apiEvents });
  }

  function saveEventTypes(newTypes: string[]) {
    const apiIds = currentAccountIds.length === allAccountIds.length && allAccountIds.every((id) => currentAccountIds.includes(id)) ? null : currentAccountIds;
    const apiEvents = newTypes.length === allEventTypes.length && allEventTypes.every((t) => newTypes.includes(t)) ? null : newTypes;
    updateMutation.mutate({ mail_account_ids: apiIds, event_types: apiEvents });
  }

  function toggleAccount(id: string, checked: boolean) {
    const newIds = checked
      ? [...currentAccountIds, id]
      : currentAccountIds.filter((a) => a !== id);
    saveAccountIds(newIds);
  }

  function toggleEvent(type: string, checked: boolean) {
    const newTypes = checked
      ? [...currentEventTypes, type]
      : currentEventTypes.filter((e) => e !== type);
    saveEventTypes(newTypes);
  }

  async function onTest() {
    setTesting(true);
    try {
      const result = await testChannel(channel.id);
      if (result.success) {
        toast({ title: "Test sent", description: result.message });
      } else {
        toast({ title: "Test failed", description: result.message, variant: "destructive" });
      }
    } catch {
      toast({ title: "Test failed", description: "Could not reach the endpoint.", variant: "destructive" });
    } finally {
      setTesting(false);
    }
  }

  return (
    <div className="rounded-lg border">
      <div className="flex items-center gap-2 p-3">
        <button
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-2 flex-1 text-left"
        >
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          <code className="text-sm font-mono truncate flex-1">{channel.url}</code>
        </button>
        <AppButton
          icon={<Send />}
          label="Test"
          variant="ghost"
          loading={testing}
          disabled={testing}
          onClick={onTest}
        />
        <AppButton
          icon={<Trash2 />}
          label="Delete"
          variant="ghost"
          color="destructive"
          onClick={() => deleteMutation.mutate()}
          disabled={deleteMutation.isPending}
          loading={deleteMutation.isPending}
        />
      </div>

      {expanded && (
        <div className="border-t px-4 pb-4 pt-4 space-y-4">
          {/* Mail Accounts */}
          <div className="space-y-3">
            <h4 className="text-sm font-medium">Mail Accounts</h4>
            {accounts.map((acc) => (
              <div key={acc.id} className="flex items-center justify-between">
                <Label htmlFor={`account-${channel.id}-${acc.id}`} className="cursor-pointer text-sm">
                  {acc.name} ({acc.email_address})
                </Label>
                <Switch
                  id={`account-${channel.id}-${acc.id}`}
                  checked={currentAccountIds.includes(acc.id)}
                  onCheckedChange={(checked) => toggleAccount(acc.id, checked)}
                  disabled={updateMutation.isPending}
                />
              </div>
            ))}
          </div>

          <Separator />

          {/* Event Types */}
          <div className="space-y-3">
            <h4 className="text-sm font-medium">Notification Events</h4>
            {events.map((evt) => (
              <div key={evt.event_type} className="flex items-center justify-between">
                <Label htmlFor={`event-${channel.id}-${evt.event_type}`} className="cursor-pointer text-sm">
                  {evt.display_name}
                </Label>
                <Switch
                  id={`event-${channel.id}-${evt.event_type}`}
                  checked={currentEventTypes.includes(evt.event_type)}
                  onCheckedChange={(checked) => toggleEvent(evt.event_type, checked)}
                  disabled={updateMutation.isPending}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Channels Dialog Content
// ---------------------------------------------------------------------------

interface ChannelsDialogContentProps {
  channels: NotificationChannel[];
  accounts: MailAccountResponse[];
  events: NotificationEventInfo[];
}

function ChannelsDialogContent({ channels, accounts, events }: ChannelsDialogContentProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [newUrl, setNewUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (url: string) =>
      createChannel({ url, mail_account_ids: null, event_types: null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-channels"] });
      setNewUrl("");
      toast({ title: "Channel added", description: "New notification channel created." });
    },
    onError: () => {
      toast({ title: "Failed to add channel", description: "Could not create the channel.", variant: "destructive" });
    },
  });

  function onAddChannel(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmed = newUrl.trim();
    if (!trimmed) {
      setUrlError("URL is required");
      return;
    }
    try {
      new URL(trimmed);
    } catch {
      setUrlError("Must be a valid URL");
      return;
    }
    setUrlError(null);
    createMutation.mutate(trimmed);
  }

  return (
    <div className="space-y-4">
      {channels.length === 0 && (
        <p className="text-sm text-muted-foreground py-4 text-center">
          No notification channels configured yet.
        </p>
      )}

      {channels.map((channel) => (
        <ChannelItem
          key={channel.id}
          channel={channel}
          accounts={accounts}
          events={events}
        />
      ))}

      {channels.length < 10 && (
        <>
          <Separator />
          <form onSubmit={onAddChannel} className="flex items-start gap-2">
            <div className="flex-1">
              <Input
                value={newUrl}
                onChange={(e) => { setNewUrl(e.target.value); setUrlError(null); }}
                placeholder="apprise://service/token..."
                className="font-mono text-sm"
              />
              {urlError && <p className="mt-1 text-xs text-destructive">{urlError}</p>}
            </div>
            <AppButton
              icon={<Plus />}
              label="Add"
              type="submit"
              variant="primary"
              disabled={createMutation.isPending}
              loading={createMutation.isPending}
            >
              Add
            </AppButton>
          </form>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function NotificationsPage() {
  usePageTitle("Notifications");
  const [channelsOpen, setChannelsOpen] = useState(false);

  const channelsQuery = useQuery({
    queryKey: ["notification-channels"],
    queryFn: fetchChannels,
    refetchInterval: 60_000,
  });

  const eventsQuery = useQuery({
    queryKey: ["notification-events"],
    queryFn: fetchEvents,
    staleTime: 5 * 60_000,
  });

  const accountsQuery = useListMailAccountsApiMailAccountsGet();
  const accounts = (unwrapResponse<MailAccountResponse[]>(accountsQuery.data) ?? []) as MailAccountResponse[];

  const channels = channelsQuery.data ?? [];
  const events = eventsQuery.data ?? [];

  if (channelsQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Notifications"
          description="Configure notification channels and event triggers."
          actions={
            <AppButton icon={<Bell />} label="Channels" variant="primary" disabled>
              Channels
            </AppButton>
          }
        />
        <QueryError
          message="Failed to load notification settings."
          onRetry={() => channelsQuery.refetch()}
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
          <AppButton
            icon={<Bell />}
            label="Channels"
            variant="primary"
            onClick={() => setChannelsOpen(true)}
          >
            Channels
          </AppButton>
        }
      />

      <TemplateEditor />

      <AppDialog
        open={channelsOpen}
        onOpenChange={setChannelsOpen}
        title="Notification Channels"
        description="Manage Apprise-compatible notification URLs. Expand a channel to configure which accounts and events it receives."
        preventClose
        contentClassName="max-h-[85vh]"
      >
        <ChannelsDialogContent
          channels={channels}
          accounts={accounts}
          events={events}
        />
      </AppDialog>
    </div>
  );
}
