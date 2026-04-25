import { useState, useEffect } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod/v4";
import {
  Info,
  Save,
  FlaskConical,
  CalendarDays,
  Trash2,
  MapPin,
  Clock,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useGetConfigApiCalendarConfigGet,
  useUpdateConfigApiCalendarConfigPut,
  useTestConfigApiCalendarConfigTestPost,
  getGetConfigApiCalendarConfigGetQueryKey,
} from "@/services/api/calendar/calendar";

import {
  useListCalendarEventsApiCalendarEventsGet,
  useDeleteCalendarEventApiCalendarEventsEventIdDelete,
  useSyncCalendarEventApiCalendarEventsEventIdSyncPost,
  getListCalendarEventsApiCalendarEventsGetQueryKey,
} from "@/services/api/calendar-events/calendar-events";

import { SpamButton } from "@/components/spam-button";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/layout/page-header";
import { SortToggle } from "@/components/sort-toggle";
import { QueryError } from "@/components/query-error";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import {
  PluginSettingsDialog,
  PluginSettingsButton,
} from "@/components/plugin-settings-dialog";
import { SearchableCardList } from "@/components/searchable-card-list";
import { FilterListItem } from "@/components/filter-list-item";
import { useSearchableList } from "@/hooks/use-searchable-list";
import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { formatDate, unwrapResponse } from "@/lib/utils";
import type {
  CalDAVConfigResponse,
  CalDAVTestResponse,
  CalendarEventResponse,
  CalendarEventListResponse,
  ListCalendarEventsApiCalendarEventsGetSort,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const calendarSchema = z.object({
  caldav_url: z.string().min(1, "CalDAV URL is required").max(500),
  default_calendar: z.string().min(1, "Calendar name is required").max(255),
  username: z.string().max(200),
  password: z.string().max(500),
});

type CalendarFormValues = z.infer<typeof calendarSchema>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatEventDate(dateStr: string | null | undefined): string | null {
  if (!dateStr) return null;
  try {
    const d = new Date(dateStr);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

function formatEventDateShort(dateStr: string | null | undefined): string | null {
  if (!dateStr) return null;
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CalendarPage() {
  usePageTitle("Calendar");
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [settingsOpen, setSettingsOpen] = useState(false);

  // --- CalDAV config ---
  const configQuery = useGetConfigApiCalendarConfigGet();
  const config = unwrapResponse<CalDAVConfigResponse | null>(configQuery.data);

  const updateMutation = useUpdateConfigApiCalendarConfigPut();
  const testMutation = useTestConfigApiCalendarConfigTestPost();

  const form = useForm<CalendarFormValues>({
    resolver: zodResolver(calendarSchema),
    defaultValues: {
      caldav_url: "",
      default_calendar: "",
      username: "",
      password: "",
    },
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = form;

  useEffect(() => {
    if (config) {
      reset({
        caldav_url: config.caldav_url ?? "",
        default_calendar: config.default_calendar ?? "",
        username: "",
        password: "",
      });
    }
  }, [config, reset]);

  async function onSave(data: CalendarFormValues) {
    try {
      await updateMutation.mutateAsync({
        data: {
          caldav_url: data.caldav_url,
          default_calendar: data.default_calendar,
          username: data.username,
          password: data.password,
        },
      });
      queryClient.invalidateQueries({
        queryKey: getGetConfigApiCalendarConfigGetQueryKey(),
      });
      toast({ title: "Calendar configuration saved", description: "Your CalDAV settings have been updated." });
      setSettingsOpen(false);
    } catch {
      toast({
        title: "Failed to save configuration",
        description: "Could not save the calendar settings. Please try again.",
        variant: "destructive",
      });
    }
  }

  async function onTest() {
    const values = form.getValues();

    // Need either all credentials (for pre-save test) or a saved config
    const hasCredentials = values.caldav_url && values.username && values.password;
    if (!hasCredentials && !config) {
      toast({
        title: "Validation error",
        description: "URL, username, and password are required for testing.",
        variant: "destructive",
      });
      return;
    }

    try {
      const res = await testMutation.mutateAsync({
        data: {
          caldav_url: values.caldav_url || undefined,
          username: values.username || undefined,
          password: values.password || undefined,
          default_calendar: values.default_calendar || "",
        },
      });
      const result = unwrapResponse<CalDAVTestResponse>(res);
      if (result?.success) {
        const details = result.details ?? {};

        // Auto-fill discovered CalDAV URL if different
        const discoveredUrl = details.caldav_url as string | undefined;
        if (discoveredUrl && discoveredUrl !== values.caldav_url) {
          form.setValue("caldav_url", discoveredUrl);
        }

        // Auto-fill first calendar if field is empty (skip birthday calendars)
        const calSlugs = (details.calendar_slugs as string[]) ?? [];
        const calNames = result.calendars ?? [];
        if (!values.default_calendar && calNames.length > 0) {
          // Prefer a non-birthday calendar
          const idx = calSlugs.findIndex((s) => !s.includes("birthday") && !s.includes("geburtstag"));
          const pick = (idx >= 0 ? calNames[idx] : calNames[0]) ?? "";
          form.setValue("default_calendar", pick);
        }

        const calList = calNames.length > 0
          ? calNames.map((name, i) => `${name} (${calSlugs[i] ?? name})`).join(", ")
          : "";
        toast({
          title: "Connection successful",
          description: calList
            ? `${result.message}\n\nCalendars: ${calList}`
            : result.message,
        });
      } else {
        toast({
          title: "Connection failed",
          description: result?.message ?? "Unknown error",
          variant: "destructive",
        });
      }
    } catch {
      toast({
        title: "Connection test failed",
        description: "Could not reach the CalDAV server. Please check your credentials.",
        variant: "destructive",
      });
    }
  }

  // --- Events list ---
  const list = useSearchableList();
  const [sortOrder, setSortOrder] = useState<string>("newest");
  const [deleteTarget, setDeleteTarget] = useState<CalendarEventResponse | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);

  const eventsParams = {
    page: list.page,
    per_page: list.perPage,
    sort: sortOrder as ListCalendarEventsApiCalendarEventsGetSort,
    ...(list.searchFilter ? { search: list.searchFilter } : {}),
  };

  const eventsQuery = useListCalendarEventsApiCalendarEventsGet(eventsParams);
  const eventsData = unwrapResponse<CalendarEventListResponse>(eventsQuery.data);
  const eventItems = eventsData?.items ?? [];
  const totalPages = eventsData?.pages ?? 1;

  const deleteMutation = useDeleteCalendarEventApiCalendarEventsEventIdDelete();
  const syncMutation = useSyncCalendarEventApiCalendarEventsEventIdSyncPost();

  const hasActiveFilters = sortOrder !== "newest";

  async function handleDeleteEvent(id: string) {
    try {
      await deleteMutation.mutateAsync({ eventId: id });
      queryClient.invalidateQueries({
        queryKey: getListCalendarEventsApiCalendarEventsGetQueryKey(eventsParams),
      });
      setDeleteTarget(null);
      toast({ title: "Calendar event removed", description: "The event has been deleted from the list." });
    } catch {
      toast({ title: "Failed to remove calendar event", description: "Could not delete the event. Please try again.", variant: "destructive" });
    }
  }

  async function handleSyncEvent(id: string) {
    setSyncingId(id);
    try {
      await syncMutation.mutateAsync({ eventId: id });
      queryClient.invalidateQueries({
        queryKey: getListCalendarEventsApiCalendarEventsGetQueryKey(eventsParams),
      });
      toast({ title: "Event synced to calendar", description: "The event has been pushed to your CalDAV calendar." });
    } catch {
      toast({ title: "Failed to sync event", description: "Could not sync the event to the calendar. Please try again.", variant: "destructive" });
    } finally {
      setSyncingId(null);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Calendar Extraction"
        description="Events extracted from emails by the AI calendar plugin."
        actions={
          <div className="flex items-center gap-2">
            <PluginSettingsButton onClick={() => setSettingsOpen(true)} />
          </div>
        }
      />

      {/* Events List */}
      <Card>
        <CardHeader>
          <CardTitle>Extracted Events</CardTitle>
          <CardDescription>
            Calendar events will appear here as they are extracted from your
            incoming emails.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList
            list={list}
            items={eventItems}
            totalPages={totalPages}
            totalCount={eventsData?.total ?? 0}
            isError={eventsQuery.isError}
            isLoading={eventsQuery.isLoading}
            isFetching={eventsQuery.isFetching}
            errorMessage="Failed to load events."
            onRetry={() => eventsQuery.refetch()}
            searchPlaceholder="Search by title or subject..."
            hasActiveFilters={hasActiveFilters}
            filterContent={
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Sort Order</Label>
                  <SortToggle
                    sortOrder={sortOrder}
                    onToggle={(o) => { setSortOrder(o); list.setPage(1); }}
                    isFetching={eventsQuery.isFetching}
                    variant="inline"
                  />
                </div>
                {hasActiveFilters && (
                  <AppButton
                    icon={<RotateCcw />}
                    label="Clear filters"
                    variant="ghost"
                    className="h-7 w-full text-xs"
                    onClick={() => {
                      setSortOrder("newest");
                      list.setPage(1);
                    }}
                  >
                    Clear filters
                  </AppButton>
                )}
              </div>
            }
            emptyIcon={<CalendarDays className="mb-3 h-10 w-10 text-muted-foreground" />}
            emptyMessage="No calendar events extracted yet. Events will appear here as emails with date/time references are processed."
            renderItem={(item: CalendarEventResponse) => (
              <FilterListItem
                key={item.id}
                icon={<CalendarDays />}
                title={item.title}
                badges={
                  <>
                    {item.is_all_day && (
                      <Badge variant="secondary" className="shrink-0">
                        All day
                      </Badge>
                    )}
                    {item.caldav_synced && (
                      <Badge variant="success" className="shrink-0">
                        Synced
                      </Badge>
                    )}
                    {!item.caldav_synced && item.caldav_error && (
                      <Badge variant="destructive" className="shrink-0">
                        Sync failed
                      </Badge>
                    )}
                  </>
                }
                subtitle={
                  <>
                    {/* Date/time row */}
                    <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                      {item.start && (
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {item.is_all_day
                            ? formatEventDateShort(item.start)
                            : formatEventDate(item.start)}
                          {item.end && (
                            <>
                              {" - "}
                              {item.is_all_day
                                ? formatEventDateShort(item.end)
                                : formatEventDate(item.end)}
                            </>
                          )}
                        </span>
                      )}
                      {item.location && (
                        <span className="flex items-center gap-1">
                          <MapPin className="h-3 w-3" />
                          {item.location}
                        </span>
                      )}
                    </div>
                    {item.description && (
                      <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
                        {item.description}
                      </p>
                    )}
                    {item.mail_subject && (
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {item.mail_subject}
                      </p>
                    )}
                    {item.mail_from && (
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {item.mail_from}
                      </p>
                    )}
                  </>
                }
                date={formatDate(item.created_at)}
                actions={
                  <>
                    <SpamButton
                      variant="mail"
                      mailId={item.mail_uid}
                      mailAccountId={item.mail_account_id}
                      senderEmail={item.mail_from ?? ""}
                      subject={item.mail_subject}
                      onSuccess={() =>
                        queryClient.invalidateQueries({
                          queryKey: getListCalendarEventsApiCalendarEventsGetQueryKey(),
                        })
                      }
                    />
                    <AppButton
                      icon={<RefreshCw />}
                      label={item.caldav_synced ? "Re-sync to calendar" : item.caldav_error ? `Sync failed: ${item.caldav_error}` : "Push to calendar"}
                      variant="ghost"
                      disabled={syncingId === item.id}
                      onClick={() => handleSyncEvent(item.id)}
                      loading={syncingId === item.id}
                    />
                    <AppButton
                      icon={<Trash2 />}
                      label="Delete"
                      variant="ghost"
                      color="destructive"
                      onClick={() => setDeleteTarget(item)}
                    />
                  </>
                }
              />
            )}
          />
        </CardContent>
      </Card>

      {/* Info card */}
      <Card>
        <CardContent className="flex items-start gap-3 pt-6">
          <Info className="mt-0.5 h-5 w-5 shrink-0 text-blue-500" />
          <div className="text-sm text-muted-foreground">
            <p className="font-medium text-foreground">
              How calendar integration works
            </p>
            <p className="mt-1">
              When the AI processes incoming emails, it automatically detects
              date/time references and event-like content. Relevant events are
              created in your configured CalDAV calendar. Configure your CalDAV
              connection in the{" "}
              <button
                type="button"
                className="font-medium text-foreground underline-offset-4 hover:underline"
                onClick={() => setSettingsOpen(true)}
              >
                Settings
              </button>{" "}
              dialog.
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Status footer */}
      {config?.updated_at && (
        <p className="text-xs text-muted-foreground">
          CalDAV last configured:{" "}
          {new Date(config.updated_at).toLocaleString()}
        </p>
      )}

      {/* CalDAV Settings Dialog */}
      <PluginSettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        title="CalDAV Configuration"
        description="Enter your CalDAV server credentials to enable calendar event creation from emails."
      >
        {configQuery.isError ? (
          <QueryError
            message="Failed to load calendar configuration."
            onRetry={() => configQuery.refetch()}
          />
        ) : configQuery.isLoading ? (
          <div className="space-y-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-10 w-full" />
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            <form onSubmit={handleSubmit(onSave)} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="caldav_url">CalDAV URL</Label>
                <Input
                  id="caldav_url"
                  placeholder="https://nextcloud.example.com"
                  {...register("caldav_url")}
                />
                {errors.caldav_url ? (
                  <p className="text-xs text-destructive">
                    {errors.caldav_url.message}
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Just the server URL is enough — the full DAV path is auto-detected.
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="default_calendar">Calendar Name</Label>
                <Input
                  id="default_calendar"
                  placeholder="Personal"
                  {...register("default_calendar")}
                />
                {errors.default_calendar ? (
                  <p className="text-xs text-destructive">
                    {errors.default_calendar.message}
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Auto-filled by &quot;Test Connection&quot;. Leave empty to discover available calendars.
                  </p>
                )}
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="cal-username">Username</Label>
                  <Input
                    id="cal-username"
                    placeholder="user@example.com"
                    {...register("username")}
                    autoComplete="off"
                  />
                  {errors.username && (
                    <p className="text-xs text-destructive">
                      {errors.username.message}
                    </p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cal-password">Password</Label>
                  <Input
                    id="cal-password"
                    type="password"
                    placeholder={config ? "Enter new password to change" : "Password"}
                    {...register("password")}
                    autoComplete="off"
                  />
                  {errors.password && (
                    <p className="text-xs text-destructive">
                      {errors.password.message}
                    </p>
                  )}
                  {config && (
                    <p className="text-xs text-muted-foreground">
                      Leave blank to keep the existing password.
                    </p>
                  )}
                </div>
              </div>

              <Separator />

              <div className="flex flex-wrap gap-2">
                <AppButton
                  type="submit"
                  icon={<Save />}
                  label="Save Configuration"
                  variant="primary"
                  disabled={updateMutation.isPending}
                  loading={updateMutation.isPending}
                >
                  Save Configuration
                </AppButton>
                <AppButton
                  type="button"
                  icon={<FlaskConical />}
                  label="Test Connection"
                  onClick={onTest}
                  disabled={testMutation.isPending}
                  loading={testMutation.isPending}
                >
                  Test Connection
                </AppButton>
              </div>
            </form>
          </div>
        )}
      </PluginSettingsDialog>

      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete Calendar Event"
        description={
          <>
            Are you sure you want to remove the event{" "}
            <span className="font-medium">{deleteTarget?.title}</span>
            {deleteTarget?.mail_subject ? ` extracted from "${deleteTarget.mail_subject}"` : ""}?
            This action cannot be undone.
          </>
        }
        onConfirm={() => {
          if (deleteTarget) handleDeleteEvent(deleteTarget.id);
        }}
        isPending={deleteMutation.isPending}
      />
    </div>
  );
}
