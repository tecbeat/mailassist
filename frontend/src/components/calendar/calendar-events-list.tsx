import { useState } from "react";
import { CalendarDays, Clock, MapPin, RefreshCw, Trash2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useListCalendarEventsApiCalendarEventsGet,
  useDeleteCalendarEventApiCalendarEventsEventIdDelete,
  useSyncCalendarEventApiCalendarEventsEventIdSyncPost,
  getListCalendarEventsApiCalendarEventsGetQueryKey,
} from "@/services/api/calendar-events/calendar-events";

import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import { FilterListItem } from "@/components/filter-list-item";
import { SearchableCardList } from "@/components/searchable-card-list";
import { SortFilterContent } from "@/components/sort-filter-content";
import { SpamButton } from "@/components/spam-button";
import { useToast } from "@/components/ui/toast";
import { useSearchableList } from "@/hooks/use-searchable-list";
import { formatDate, unwrapResponse } from "@/lib/utils";
import type {
  CalendarEventListResponse,
  CalendarEventResponse,
  ListCalendarEventsApiCalendarEventsGetSort,
} from "@/types/api";

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

/** Paginated, searchable list of calendar events with delete and sync actions. */
export function CalendarEventsList() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const list = useSearchableList();
  const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");
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

  function invalidateEvents() {
    queryClient.invalidateQueries({
      queryKey: getListCalendarEventsApiCalendarEventsGetQueryKey(),
    });
  }

  async function handleDeleteEvent(id: string) {
    try {
      await deleteMutation.mutateAsync({ eventId: id });
      invalidateEvents();
      setDeleteTarget(null);
      toast({
        title: "Calendar event removed",
        description: "The event has been deleted from the list.",
      });
    } catch {
      toast({
        title: "Failed to remove calendar event",
        description: "Could not delete the event. Please try again.",
        variant: "destructive",
      });
    }
  }

  async function handleSyncEvent(id: string) {
    setSyncingId(id);
    try {
      await syncMutation.mutateAsync({ eventId: id });
      invalidateEvents();
      toast({
        title: "Event synced to calendar",
        description: "The event has been pushed to your CalDAV calendar.",
      });
    } catch {
      toast({
        title: "Failed to sync event",
        description: "Could not sync the event to the calendar. Please try again.",
        variant: "destructive",
      });
    } finally {
      setSyncingId(null);
    }
  }

  return (
    <>
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
          <SortFilterContent
            sortOrder={sortOrder}
            onSortChange={(o) => {
              setSortOrder(o);
              list.setPage(1);
            }}
            isFetching={eventsQuery.isFetching}
            hasActiveFilters={hasActiveFilters}
            onClearFilters={() => {
              setSortOrder("newest");
              list.setPage(1);
            }}
          />
        }
        emptyIcon={
          <CalendarDays className="mb-3 h-10 w-10 text-muted-foreground" />
        }
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
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
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
                  onSuccess={invalidateEvents}
                />
                <AppButton
                  icon={<RefreshCw />}
                  label={
                    item.caldav_synced
                      ? "Re-sync to calendar"
                      : item.caldav_error
                        ? `Sync failed: ${item.caldav_error}`
                        : "Push to calendar"
                  }
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

      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title="Delete Calendar Event"
        description={
          <>
            Are you sure you want to remove the event{" "}
            <span className="font-medium">{deleteTarget?.title}</span>
            {deleteTarget?.mail_subject
              ? ` extracted from "${deleteTarget.mail_subject}"`
              : ""}
            ? This action cannot be undone.
          </>
        }
        onConfirm={() => {
          if (deleteTarget) handleDeleteEvent(deleteTarget.id);
        }}
        isPending={deleteMutation.isPending}
      />
    </>
  );
}
