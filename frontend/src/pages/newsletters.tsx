import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
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
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/layout/page-header";
import { SortFilterContent } from "@/components/sort-filter-content";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import { SearchableCardList } from "@/components/searchable-card-list";
import { FilterListItem } from "@/components/filter-list-item";
import { useSearchableList } from "@/hooks/use-searchable-list";
import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
  usePageTitle("Newsletters");
  const list = useSearchableList();
  const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");
  const [deleteTarget, setDeleteTarget] = useState<DetectedNewsletterResponse | null>(null);
  const { toast } = useToast();
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

  const hasActiveFilters = sortOrder !== "newest";

  async function handleDelete(id: string) {
    try {
      await deleteMutation.mutateAsync({ newsletterId: id });
      queryClient.invalidateQueries({
        queryKey: getListNewslettersApiNewslettersGetQueryKey(params),
      });
      setDeleteTarget(null);
      toast({ title: "Newsletter removed", description: "The newsletter entry has been deleted." });
    } catch {
      toast({ title: "Failed to remove newsletter", description: "Could not delete the newsletter record. Please try again.", variant: "destructive" });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Newsletters"
        description="Detected newsletters and marketing emails. Use the unsubscribe link to opt out."
      />

      {/* Newsletter List Card */}
      <Card>
        <CardHeader>
          <CardTitle>Detected Newsletters</CardTitle>
          <CardDescription>
            Newsletters will appear here as they are processed from your
            incoming emails.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList
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
            renderItem={(nl: DetectedNewsletterResponse) => (
              <FilterListItem
                key={nl.id}
                icon={<Newspaper />}
                title={nl.newsletter_name}
                badges={
                  nl.has_unsubscribe ? (
                    <Badge variant="default" className="shrink-0">
                      Unsubscribe available
                    </Badge>
                  ) : (
                    <Badge variant="secondary" className="shrink-0">
                      No unsubscribe
                    </Badge>
                  )
                }
                subtitle={
                  <>
                    <p className="truncate text-xs text-muted-foreground">
                      {nl.sender_address}
                    </p>
                    {nl.mail_subject && (
                      <p className="mt-1 truncate text-sm text-muted-foreground">
                        {nl.mail_subject}
                      </p>
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
                        <TooltipContent>
                          Open unsubscribe page
                        </TooltipContent>
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
          />
        </CardContent>
      </Card>

      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete Newsletter"
        description={
          <>
            Are you sure you want to remove{" "}
            <span className="font-medium">{deleteTarget?.newsletter_name}</span>
            {deleteTarget?.sender_address ? ` (${deleteTarget.sender_address})` : ""}{" "}
            from the list? This action cannot be undone.
          </>
        }
        onConfirm={() => {
          if (deleteTarget) handleDelete(deleteTarget.id);
        }}
        isPending={deleteMutation.isPending}
      />
    </div>
  );
}
