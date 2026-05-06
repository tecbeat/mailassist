import { useState } from "react";
import {
  Newspaper,
  ExternalLink,
  Trash2,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useListNewslettersApiNewslettersGet,
  useDeleteNewsletterApiNewslettersNewsletterIdDelete,
  getListNewslettersApiNewslettersGetQueryKey,
} from "@/services/api/newsletters/newsletters";

import { SpamButton } from "@/components/spam-button";
import { PluginListPage } from "@/components/plugin-list-page";
import { SortFilterContent } from "@/components/sort-filter-content";
import { FilterListItem } from "@/components/filter-list-item";
import { useSearchableList } from "@/hooks/use-searchable-list";
import { useDeleteHandler } from "@/hooks/use-delete-handler";
import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

import { formatDate, unwrapResponse } from "@/lib/utils";
import type {
  DetectedNewsletterResponse,
  DetectedNewsletterListResponse,
  ListNewslettersApiNewslettersGetSort,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function NewslettersPage() {
  const list = useSearchableList();
  const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");
  const queryClient = useQueryClient();

  const params = {
    page: list.page,
    per_page: list.perPage,
    sort: sortOrder as ListNewslettersApiNewslettersGetSort,
    ...(list.searchFilter ? { sender: list.searchFilter } : {}),
  };

  const newslettersQuery = useListNewslettersApiNewslettersGet(params);
  const listData = unwrapResponse<DetectedNewsletterListResponse>(newslettersQuery.data);
  const items = listData?.items ?? [];
  const totalPages = listData?.pages ?? 1;

  const deleteMutation = useDeleteNewsletterApiNewslettersNewsletterIdDelete();
  const { deleteTarget, setDeleteTarget, handleDelete, isPending } =
    useDeleteHandler<DetectedNewsletterResponse>({
      onDelete: (item) => deleteMutation.mutateAsync({ newsletterId: item.id }),
      queryKeys: [getListNewslettersApiNewslettersGetQueryKey(params)],
      isPending: deleteMutation.isPending,
      successTitle: "Newsletter removed",
      successDescription: "The newsletter entry has been deleted.",
      errorTitle: "Failed to remove newsletter",
      errorDescription: "Could not delete the newsletter record. Please try again.",
    });

  const hasActiveFilters = sortOrder !== "newest";

  return (
    <PluginListPage<DetectedNewsletterResponse>
      pageTitle="Newsletters"
      header={{
        title: "Newsletters",
        description: "Detected newsletters and marketing emails. Use the unsubscribe link to opt out.",
      }}
      card={{
        title: "Detected Newsletters",
        description: "Newsletters will appear here as they are processed from your incoming emails.",
      }}
      list={list}
      items={items}
      totalPages={totalPages}
      totalCount={listData?.total ?? 0}
      isError={newslettersQuery.isError}
      isLoading={newslettersQuery.isLoading}
      isFetching={newslettersQuery.isFetching}
      errorMessage="Failed to load newsletters."
      onRetry={() => newslettersQuery.refetch()}
      searchPlaceholder="Search by sender..."
      hasActiveFilters={hasActiveFilters}
      filterContent={
        <SortFilterContent
          sortOrder={sortOrder}
          onSortChange={(o) => { setSortOrder(o); list.setPage(1); }}
          isFetching={newslettersQuery.isFetching}
          hasActiveFilters={hasActiveFilters}
          onClearFilters={() => { setSortOrder("newest"); list.setPage(1); }}
        />
      }
      emptyIcon={<Newspaper className="mb-3 h-10 w-10 text-muted-foreground" />}
      emptyMessage="No newsletters detected yet. Newsletters will appear here as they are processed."
      renderItem={(nl) => (
        <FilterListItem
          key={nl.id}
          icon={<Newspaper />}
          title={nl.newsletter_name}
          badges={
            nl.has_unsubscribe ? (
              <Badge variant="default" className="shrink-0">Unsubscribe available</Badge>
            ) : (
              <Badge variant="secondary" className="shrink-0">No unsubscribe</Badge>
            )
          }
          subtitle={
            <>
              <p className="truncate text-xs text-muted-foreground">{nl.sender_address}</p>
              {nl.mail_subject && (
                <p className="mt-1 truncate text-sm text-muted-foreground">{nl.mail_subject}</p>
              )}
            </>
          }
          date={formatDate(nl.created_at)}
          actions={
            <>
              {nl.has_unsubscribe && nl.unsubscribe_url && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <a
                      href={nl.unsubscribe_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                      aria-label="Open unsubscribe page"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  </TooltipTrigger>
                  <TooltipContent>Open unsubscribe page</TooltipContent>
                </Tooltip>
              )}
              <SpamButton
                variant="mail"
                mailId={nl.mail_uid}
                mailAccountId={nl.mail_account_id}
                senderEmail={nl.sender_address}
                subject={nl.mail_subject}
                onSuccess={() =>
                  queryClient.invalidateQueries({
                    queryKey: getListNewslettersApiNewslettersGetQueryKey(),
                  })
                }
              />
              <AppButton
                icon={<Trash2 />}
                label="Delete newsletter"
                variant="ghost"
                color="destructive"
                onClick={() => setDeleteTarget(nl)}
              />
            </>
          }
        />
      )}
      deleteDialog={{
        open: !!deleteTarget,
        onOpenChange: (open) => { if (!open) setDeleteTarget(null); },
        title: "Delete Newsletter",
        description: (
          <>
            Are you sure you want to remove{" "}
            <span className="font-medium">{deleteTarget?.newsletter_name}</span>
            {deleteTarget?.sender_address ? ` (${deleteTarget.sender_address})` : ""}{" "}
            from the list? This action cannot be undone.
          </>
        ),
        onConfirm: handleDelete,
        isPending,
      }}
    />
  );
}
