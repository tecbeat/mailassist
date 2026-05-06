import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { Bell, Plus, Send, Trash2, Save } from "lucide-react";
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

async function fetchChannels(): Promise<NotificationChannel[]> {
  const res = await fetch(`${API_BASE}/channels`);
  if (!res.ok) throw new Error("Failed to load channels");
  return res.json();
}

async function createChannel(data: {
  url: string;
  mail_account_ids: string[] | null;
  event_types: string[] | null;
}): Promise<NotificationChannel> {
  const res = await fetch(`${API_BASE}/channels`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
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
// Channel Item (within the settings dialog)
// ---------------------------------------------------------------------------

interface ChannelItemProps {
  channel: NotificationChannel;
  accounts: MailAccountResponse[];
  events: NotificationEventInfo[];
}

function ChannelItem({ channel, accounts, events }: ChannelItemProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const allAccountIds = accounts.map((a) => a.id);
  const allEventTypes = events.map((e) => e.event_type);

  const [localAccountIds, setLocalAccountIds] = useState<string[]>(
    channel.mail_account_ids ?? allAccountIds,
  );
  const [localEventTypes, setLocalEventTypes] = useState<string[]>(
    channel.event_types ?? allEventTypes,
  );
  const [testing, setTesting] = useState(false);

  function getAccountIdsForApi(): string[] | null {
    if (
      localAccountIds.length === allAccountIds.length &&
      allAccountIds.every((id) => localAccountIds.includes(id))
    ) {
      return null;
    }
    return localAccountIds;
  }

  function getEventTypesForApi(): string[] | null {
    if (
      localEventTypes.length === allEventTypes.length &&
      allEventTypes.every((t) => localEventTypes.includes(t))
    ) {
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
      toast({
        title: "Failed to delete",
        description: "Could not delete the channel.",
        variant: "destructive",
      });
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
      toast({
        title: "Failed to update",
        description: "Could not save channel settings.",
        variant: "destructive",
      });
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
      toast({
        title: "Test failed",
        description: "Could not reach the endpoint.",
        variant: "destructive",
      });
    } finally {
      setTesting(false);
    }
  }

  function toggleAccount(id: string, checked: boolean) {
    setLocalAccountIds(
      checked ? [...localAccountIds, id] : localAccountIds.filter((a) => a !== id),
    );
  }

  function toggleEvent(type: string, checked: boolean) {
    setLocalEventTypes(
      checked ? [...localEventTypes, type] : localEventTypes.filter((e) => e !== type),
    );
  }

  const serverAccountIds = channel.mail_account_ids ?? allAccountIds;
  const serverEventTypes = channel.event_types ?? allEventTypes;
  const hasChanges =
    JSON.stringify([...localAccountIds].sort()) !==
      JSON.stringify([...serverAccountIds].sort()) ||
    JSON.stringify([...localEventTypes].sort()) !==
      JSON.stringify([...serverEventTypes].sort());

  return (
    <div className="space-y-4 rounded-lg border p-4">
      {/* Header: URL + actions */}
      <div className="flex items-center gap-2">
        <code className="flex-1 truncate text-sm font-mono">{channel.url}</code>
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

      {/* Mail Accounts */}
      <div className="space-y-3">
        <h4 className="text-sm font-medium">Mail Accounts</h4>
        {accounts.map((acc) => (
          <div key={acc.id} className="flex items-center justify-between">
            <Label
              htmlFor={`account-${channel.id}-${acc.id}`}
              className="cursor-pointer text-sm"
            >
              {acc.name} ({acc.email_address})
            </Label>
            <Switch
              id={`account-${channel.id}-${acc.id}`}
              checked={localAccountIds.includes(acc.id)}
              onCheckedChange={(checked) => toggleAccount(acc.id, checked)}
            />
          </div>
        ))}
      </div>

      {/* Event Types */}
      <div className="space-y-3">
        <h4 className="text-sm font-medium">Notification Events</h4>
        {events.map((evt) => (
          <div key={evt.event_type} className="flex items-center justify-between">
            <Label
              htmlFor={`event-${channel.id}-${evt.event_type}`}
              className="cursor-pointer text-sm"
            >
              {evt.display_name}
            </Label>
            <Switch
              id={`event-${channel.id}-${evt.event_type}`}
              checked={localEventTypes.includes(evt.event_type)}
              onCheckedChange={(checked) => toggleEvent(evt.event_type, checked)}
            />
          </div>
        ))}
      </div>

      {/* Save */}
      <div className="flex justify-end">
        <AppButton
          icon={<Save />}
          label="Save"
          variant="primary"
          loading={updateMutation.isPending}
          disabled={!hasChanges || updateMutation.isPending}
          onClick={() => updateMutation.mutate()}
        >
          Save
        </AppButton>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add Channel Form (within dialog)
// ---------------------------------------------------------------------------

interface AddChannelFormProps {
  accounts: MailAccountResponse[];
  events: NotificationEventInfo[];
  onSuccess: () => void;
}

function AddChannelForm({ accounts, events, onSuccess }: AddChannelFormProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [url, setUrl] = useState("");
  const [urlError, setUrlError] = useState<string | null>(null);
  const allAccountIds = accounts.map((a) => a.id);
  const allEventTypes = events.map((e) => e.event_type);
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>(allAccountIds);
  const [selectedEvents, setSelectedEvents] = useState<string[]>(allEventTypes);

  const createMutation = useMutation({
    mutationFn: () => {
      const mailAccountIds =
        selectedAccounts.length === allAccountIds.length &&
        allAccountIds.every((id) => selectedAccounts.includes(id))
          ? null
          : selectedAccounts;
      const eventTypes =
        selectedEvents.length === allEventTypes.length &&
        allEventTypes.every((t) => selectedEvents.includes(t))
          ? null
          : selectedEvents;
      return createChannel({ url: url.trim(), mail_account_ids: mailAccountIds, event_types: eventTypes });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-channels"] });
      toast({ title: "Channel added", description: "New notification channel created." });
      onSuccess();
    },
    onError: () => {
      toast({
        title: "Failed to add channel",
        description: "Could not create the channel.",
        variant: "destructive",
      });
    },
  });

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmed = url.trim();
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
    createMutation.mutate();
  }

  function toggleAccount(id: string, checked: boolean) {
    setSelectedAccounts(
      checked ? [...selectedAccounts, id] : selectedAccounts.filter((a) => a !== id),
    );
  }

  function toggleEvent(type: string, checked: boolean) {
    setSelectedEvents(
      checked ? [...selectedEvents, type] : selectedEvents.filter((e) => e !== type),
    );
  }

  return (
    <form id="add-channel-form" onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="channel-url">Notification URL</Label>
        <Input
          id="channel-url"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setUrlError(null);
          }}
          placeholder="apprise://service/token..."
          className="font-mono text-sm"
          autoFocus
        />
        {urlError && <p className="text-xs text-destructive">{urlError}</p>}
      </div>

      <Separator />

      <div className="space-y-3">
        <h4 className="text-sm font-medium">Mail Accounts</h4>
        <p className="text-xs text-muted-foreground">
          Choose which accounts trigger notifications on this channel.
        </p>
        {accounts.map((acc) => (
          <div key={acc.id} className="flex items-center justify-between">
            <Label htmlFor={`add-account-${acc.id}`} className="cursor-pointer text-sm">
              {acc.name} ({acc.email_address})
            </Label>
            <Switch
              id={`add-account-${acc.id}`}
              checked={selectedAccounts.includes(acc.id)}
              onCheckedChange={(checked) => toggleAccount(acc.id, checked)}
            />
          </div>
        ))}
      </div>

      <Separator />

      <div className="space-y-3">
        <h4 className="text-sm font-medium">Notification Events</h4>
        <p className="text-xs text-muted-foreground">
          Choose which events trigger a notification on this channel.
        </p>
        {events.map((evt) => (
          <div key={evt.event_type} className="flex items-center justify-between">
            <Label htmlFor={`add-event-${evt.event_type}`} className="cursor-pointer text-sm">
              {evt.display_name}
            </Label>
            <Switch
              id={`add-event-${evt.event_type}`}
              checked={selectedEvents.includes(evt.event_type)}
              onCheckedChange={(checked) => toggleEvent(evt.event_type, checked)}
            />
          </div>
        ))}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Channels Dialog (opened via "Channels" button in header)
// ---------------------------------------------------------------------------

interface ChannelsDialogContentProps {
  channels: NotificationChannel[];
  accounts: MailAccountResponse[];
  events: NotificationEventInfo[];
}

function ChannelsDialogContent({ channels, accounts, events }: ChannelsDialogContentProps) {
  const [addOpen, setAddOpen] = useState(false);

  if (addOpen) {
    return (
      <div className="space-y-4">
        <AddChannelForm
          accounts={accounts}
          events={events}
          onSuccess={() => setAddOpen(false)}
        />
        <div className="flex justify-end gap-2">
          <AppButton icon={<Bell />} label="Back" onClick={() => setAddOpen(false)}>
            Back
          </AppButton>
          <AppButton
            icon={<Plus />}
            label="Add Channel"
            variant="primary"
            type="submit"
            form="add-channel-form"
          >
            Add Channel
          </AppButton>
        </div>
      </div>
    );
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
        <div className="flex justify-end">
          <AppButton
            icon={<Plus />}
            label="Add Channel"
            variant="primary"
            onClick={() => setAddOpen(true)}
          >
            Add Channel
          </AppButton>
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
  const accounts = (unwrapResponse<MailAccountResponse[]>(accountsQuery.data) ??
    []) as MailAccountResponse[];

  const channels = channelsQuery.data ?? [];
  const events = eventsQuery.data ?? [];

  if (channelsQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Notifications"
          description="Configure notification channels and event triggers."
          actions={
            <AppButton icon={<Bell />} label="Channels" variant="outline" disabled>
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
            variant="outline"
            onClick={() => setChannelsOpen(true)}
          >
            Channels
          </AppButton>
        }
      />

      {/* Template Editor (original design with sidebar) */}
      <TemplateEditor />

      {/* Channels management dialog */}
      <AppDialog
        open={channelsOpen}
        onOpenChange={setChannelsOpen}
        title="Notification Channels"
        description="Manage Apprise-compatible notification URLs. Each channel can be scoped to specific mail accounts and event types."
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
