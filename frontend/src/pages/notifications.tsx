import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { Bell, ChevronDown, ChevronRight, Plus, Send, Trash2, Save } from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/components/ui/toast";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { useListMailAccountsApiMailAccountsGet } from "@/services/api/mail-accounts/mail-accounts";
import { unwrapResponse } from "@/lib/utils";
import type { MailAccountResponse } from "@/types/api";

import { TemplateEditor } from "@/components/notifications/template-editor";

// ---------------------------------------------------------------------------
// Types for the new channels API
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
// API helpers (custom fetchers for new endpoints)
// ---------------------------------------------------------------------------

const API_BASE = "/api/notifications";

async function fetchChannels(): Promise<NotificationChannel[]> {
  const res = await fetch(`${API_BASE}/channels`);
  if (!res.ok) throw new Error("Failed to load channels");
  return res.json();
}

async function createChannel(url: string): Promise<NotificationChannel> {
  const res = await fetch(`${API_BASE}/channels`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, mail_account_ids: null, event_types: null }),
  });
  if (!res.ok) throw new Error("Failed to create channel");
  return res.json();
}

async function updateChannel(
  id: string,
  data: { mail_account_ids: string[] | null; event_types: string[] | null },
): Promise<NotificationChannel> {
  const res = await fetch(`${API_BASE}/channels/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update channel");
  return res.json();
}

async function deleteChannel(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/channels/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete channel");
}

async function testChannel(id: string): Promise<{ success: boolean; message: string }> {
  const res = await fetch(`${API_BASE}/channels/${id}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "Test notification from mailassist" }),
  });
  if (!res.ok) throw new Error("Failed to send test");
  return res.json();
}

async function fetchEvents(): Promise<NotificationEventInfo[]> {
  const res = await fetch(`${API_BASE}/events`);
  if (!res.ok) throw new Error("Failed to load events");
  return res.json();
}

// ---------------------------------------------------------------------------
// Channel Card (expandable)
// ---------------------------------------------------------------------------

interface ChannelCardProps {
  channel: NotificationChannel;
  accounts: MailAccountResponse[];
  events: NotificationEventInfo[];
}

function ChannelCard({ channel, accounts, events }: ChannelCardProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);

  // null means "all selected" — represent as full list for UI toggles
  const allAccountIds = accounts.map((a) => a.id);
  const allEventTypes = events.map((e) => e.event_type);

  const [localAccountIds, setLocalAccountIds] = useState<string[]>(
    channel.mail_account_ids ?? allAccountIds,
  );
  const [localEventTypes, setLocalEventTypes] = useState<string[]>(
    channel.event_types ?? allEventTypes,
  );
  const [testing, setTesting] = useState(false);

  // Determine what to send to the API: if all are selected, send null
  function getAccountIdsForApi(): string[] | null {
    if (localAccountIds.length === allAccountIds.length && allAccountIds.every((id) => localAccountIds.includes(id))) {
      return null;
    }
    return localAccountIds;
  }

  function getEventTypesForApi(): string[] | null {
    if (localEventTypes.length === allEventTypes.length && allEventTypes.every((t) => localEventTypes.includes(t))) {
      return null;
    }
    return localEventTypes;
  }

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
    mutationFn: () =>
      updateChannel(channel.id, {
        mail_account_ids: getAccountIdsForApi(),
        event_types: getEventTypesForApi(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-channels"] });
      toast({ title: "Channel updated", description: "Routing configuration saved." });
    },
    onError: () => {
      toast({ title: "Failed to update", description: "Could not save channel settings.", variant: "destructive" });
    },
  });

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

  function toggleAccount(id: string, checked: boolean) {
    setLocalAccountIds(checked ? [...localAccountIds, id] : localAccountIds.filter((a) => a !== id));
  }

  function toggleEvent(type: string, checked: boolean) {
    setLocalEventTypes(checked ? [...localEventTypes, type] : localEventTypes.filter((e) => e !== type));
  }

  // Check if state differs from server
  const serverAccountIds = channel.mail_account_ids ?? allAccountIds;
  const serverEventTypes = channel.event_types ?? allEventTypes;
  const hasChanges =
    JSON.stringify([...localAccountIds].sort()) !== JSON.stringify([...serverAccountIds].sort()) ||
    JSON.stringify([...localEventTypes].sort()) !== JSON.stringify([...serverEventTypes].sort());

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
        <div className="border-t px-3 pb-3 pt-3 space-y-4">
          {/* Mail Accounts */}
          <div className="space-y-2">
            <Label className="text-xs font-medium">Mail Accounts</Label>
            {accounts.map((acc) => (
              <div key={acc.id} className="flex items-center gap-2">
                <Checkbox
                  id={`account-${channel.id}-${acc.id}`}
                  checked={localAccountIds.includes(acc.id)}
                  onCheckedChange={(checked) => toggleAccount(acc.id, !!checked)}
                />
                <Label htmlFor={`account-${channel.id}-${acc.id}`} className="text-xs">
                  {acc.name} ({acc.email_address})
                </Label>
              </div>
            ))}
          </div>

          <Separator />

          {/* Event Types */}
          <div className="space-y-2">
            <Label className="text-xs font-medium">Events</Label>
            {events.map((evt) => (
              <div key={evt.event_type} className="flex items-center gap-2">
                <Checkbox
                  id={`event-${channel.id}-${evt.event_type}`}
                  checked={localEventTypes.includes(evt.event_type)}
                  onCheckedChange={(checked) => toggleEvent(evt.event_type, !!checked)}
                />
                <Label htmlFor={`event-${channel.id}-${evt.event_type}`} className="text-xs">
                  {evt.display_name}
                </Label>
              </div>
            ))}
          </div>

          {hasChanges && (
            <>
              <Separator />
              <div className="flex justify-end">
                <AppButton
                  icon={<Save />}
                  label="Save"
                  variant="primary"
                  loading={updateMutation.isPending}
                  disabled={updateMutation.isPending}
                  onClick={() => updateMutation.mutate()}
                >
                  Save
                </AppButton>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function NotificationsPage() {
  usePageTitle("Notifications");
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [newUrl, setNewUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);

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

  const createMutation = useMutation({
    mutationFn: (url: string) => createChannel(url),
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

  const channels = channelsQuery.data ?? [];
  const events = eventsQuery.data ?? [];

  if (channelsQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Notifications"
          description="Configure notification channels and delivery routing."
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
        description="Configure notification channels and delivery routing."
      />

      <Card>
        <CardHeader>
          <CardTitle>Notification Channels</CardTitle>
          <CardDescription>
            Add Apprise-compatible notification URLs. Each channel can be configured
            to receive notifications only for specific mail accounts and event types.
            Expand a channel to configure its routing.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {channels.length === 0 && !channelsQuery.isLoading && (
            <div className="flex flex-col items-center gap-2 py-8 text-center">
              <Bell className="h-10 w-10 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                No notification channels configured yet. Add an Apprise URL below.
              </p>
            </div>
          )}

          {channels.map((channel) => (
            <ChannelCard
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
                  {urlError && (
                    <p className="mt-1 text-xs text-destructive">{urlError}</p>
                  )}
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
        </CardContent>
      </Card>

      {/* Template Editor */}
      <TemplateEditor />
    </div>
  );
}
