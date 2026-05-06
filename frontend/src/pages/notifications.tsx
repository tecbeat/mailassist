import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { ChevronDown, ChevronRight, Plus, Send, Trash2, Save } from "lucide-react";
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
// Types for the channels API
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
// Channel Card (expandable, with Switch toggles)
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
          <div className="space-y-3">
            <div>
              <h4 className="text-sm font-medium">Mail Accounts</h4>
              <p className="mt-1 text-xs text-muted-foreground">
                Choose which accounts trigger notifications on this channel.
              </p>
            </div>
            {accounts.map((acc) => (
              <div key={acc.id} className="flex items-center justify-between">
                <Label htmlFor={`account-${channel.id}-${acc.id}`} className="cursor-pointer text-sm">
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

          <Separator />

          {/* Event Types */}
          <div className="space-y-3">
            <div>
              <h4 className="text-sm font-medium">Notification Events</h4>
              <p className="mt-1 text-xs text-muted-foreground">
                Choose which events trigger a notification on this channel.
              </p>
            </div>
            {events.map((evt) => (
              <div key={evt.event_type} className="flex items-center justify-between">
                <Label htmlFor={`event-${channel.id}-${evt.event_type}`} className="cursor-pointer text-sm">
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
  const [addDialogOpen, setAddDialogOpen] = useState(false);
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
      setAddDialogOpen(false);
      toast({ title: "Channel added", description: "New notification channel created." });
    },
    onError: () => {
      toast({ title: "Failed to add channel", description: "Could not create the channel.", variant: "destructive" });
    },
  });

  function onSubmitAdd(e: React.FormEvent<HTMLFormElement>) {
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
          actions={
            <AppButton icon={<Plus />} label="Add Channel" variant="primary" disabled>
              Add Channel
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
        description="Configure notification channels and delivery routing."
        actions={
          <AppButton
            icon={<Plus />}
            label="Add Channel"
            variant="primary"
            onClick={() => setAddDialogOpen(true)}
          >
            Add Channel
          </AppButton>
        }
      />

      {/* Channels section */}
      <Card>
        <CardHeader>
          <CardTitle>Notification Channels</CardTitle>
          <CardDescription>
            Apprise-compatible notification URLs. Expand a channel to configure
            which mail accounts and events it receives.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {channels.length === 0 && !channelsQuery.isLoading && (
            <p className="text-sm text-muted-foreground py-4 text-center">
              No notification channels configured yet.
            </p>
          )}

          {channels.map((channel) => (
            <ChannelCard
              key={channel.id}
              channel={channel}
              accounts={accounts}
              events={events}
            />
          ))}
        </CardContent>
      </Card>

      {/* Template Editor (original design) */}
      <TemplateEditor />

      {/* Add Channel Dialog */}
      <AppDialog
        open={addDialogOpen}
        onOpenChange={(open) => {
          setAddDialogOpen(open);
          if (!open) { setNewUrl(""); setUrlError(null); }
        }}
        title="Add Notification Channel"
        description="Enter an Apprise-compatible notification URL (e.g. Telegram, Discord, email)."
        primaryLabel="Add Channel"
        primaryIcon={<Plus />}
        loading={createMutation.isPending}
        form="add-channel-form"
      >
        <form id="add-channel-form" onSubmit={onSubmitAdd} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="channel-url">Notification URL</Label>
            <Input
              id="channel-url"
              value={newUrl}
              onChange={(e) => { setNewUrl(e.target.value); setUrlError(null); }}
              placeholder="apprise://service/token..."
              className="font-mono text-sm"
              autoFocus
            />
            {urlError && (
              <p className="text-xs text-destructive">{urlError}</p>
            )}
          </div>
        </form>
      </AppDialog>
    </div>
  );
}
