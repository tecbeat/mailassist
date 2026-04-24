import { useState, useRef, useEffect } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  Reply,
  Trash2,
  Pencil,
  Save,
  X,
  Copy,
  Check,
  RotateCcw,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useListAutoRepliesApiAutoRepliesGet,
  useUpdateAutoReplyApiAutoRepliesReplyIdPatch,
  useDeleteAutoReplyApiAutoRepliesReplyIdDelete,
  getListAutoRepliesApiAutoRepliesGetQueryKey,
} from "@/services/api/auto-replies/auto-replies";

import { SpamButton } from "@/components/spam-button";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/layout/page-header";
import { SortToggle } from "@/components/sort-toggle";
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
import { Textarea } from "@/components/ui/textarea";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { formatDate, unwrapResponse } from "@/lib/utils";
import type {
  AutoReplyRecordResponse,
  AutoReplyRecordListResponse,
  ListAutoRepliesApiAutoRepliesGetSort,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function AutoReplyPage() {
  usePageTitle("Auto Reply");
  const list = useSearchableList();
  const [sortOrder, setSortOrder] = useState<string>("newest");
  const [deleteTarget, setDeleteTarget] = useState<AutoReplyRecordResponse | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraftBody, setEditDraftBody] = useState("");
  const [editTone, setEditTone] = useState("");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    };
  }, []);

  const params = {
    page: list.page,
    per_page: list.perPage,
    sort: sortOrder as ListAutoRepliesApiAutoRepliesGetSort,
    ...(list.searchFilter ? { search: list.searchFilter } : {}),
  };

  const repliesQuery = useListAutoRepliesApiAutoRepliesGet(params);
  const listData = unwrapResponse<AutoReplyRecordListResponse>(repliesQuery.data);

  const items = listData?.items ?? [];
  const totalPages = listData?.pages ?? 1;

  const updateMutation = useUpdateAutoReplyApiAutoRepliesReplyIdPatch();
  const deleteMutation = useDeleteAutoReplyApiAutoRepliesReplyIdDelete();

  const hasActiveFilters = sortOrder !== "newest";

  async function handleDelete(id: string) {
    try {
      await deleteMutation.mutateAsync({ replyId: id });
      queryClient.invalidateQueries({
        queryKey: getListAutoRepliesApiAutoRepliesGetQueryKey(params),
      });
      setDeleteTarget(null);
      toast({ title: "Auto-reply record removed", description: "The auto-reply entry has been deleted." });
    } catch {
      toast({ title: "Failed to remove auto-reply record", description: "Could not delete the auto-reply record. Please try again.", variant: "destructive" });
    }
  }

  function handleStartEdit(item: AutoReplyRecordResponse) {
    setEditingId(item.id);
    setEditDraftBody(item.draft_body);
    setEditTone(item.tone ?? "");
    // Expand the card if it isn't already
    setExpandedIds((prev) => new Set(prev).add(item.id));
  }

  function handleCancelEdit() {
    setEditingId(null);
    setEditDraftBody("");
    setEditTone("");
  }

  async function handleSaveEdit(id: string) {
    try {
      await updateMutation.mutateAsync({
        replyId: id,
        data: {
          draft_body: editDraftBody,
          ...(editTone ? { tone: editTone } : {}),
        },
      });
      queryClient.invalidateQueries({
        queryKey: getListAutoRepliesApiAutoRepliesGetQueryKey(params),
      });
      setEditingId(null);
      toast({ title: "Draft updated", description: "The auto-reply draft has been saved." });
    } catch {
      toast({ title: "Failed to update draft", description: "Could not save the draft changes. Please try again.", variant: "destructive" });
    }
  }

  function toggleExpanded(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
        // If we collapse while editing, cancel edit
        if (editingId === id) {
          setEditingId(null);
        }
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function handleCopyDraft(id: string, body: string) {
    try {
      await navigator.clipboard.writeText(body);
      setCopiedId(id);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedId(null), 2000);
      toast({ title: "Copied to clipboard", description: "The reply draft has been copied." });
    } catch {
      toast({ title: "Failed to copy", description: "Could not copy the draft to clipboard.", variant: "destructive" });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Auto-Reply Draft"
        description="Reply drafts generated by the AI auto-reply plugin."
        actions={
          <div className="flex items-center gap-2">
            <PluginSettingsButton onClick={() => setSettingsOpen(true)} />
          </div>
        }
      />

      {/* Drafts List */}
      <Card>
        <CardHeader>
          <CardTitle>Reply Drafts</CardTitle>
          <CardDescription>
            Drafts will appear here as the AI generates replies for your incoming
            emails. Drafts are never sent automatically.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList
            list={list}
            items={items}
            totalPages={totalPages}
            totalCount={listData?.total ?? 0}
            isError={repliesQuery.isError}
            isLoading={repliesQuery.isLoading}
            isFetching={repliesQuery.isFetching}
            errorMessage="Failed to load auto-replies."
            onRetry={() => repliesQuery.refetch()}
            searchPlaceholder="Search by subject or sender..."
            hasActiveFilters={hasActiveFilters}
            filterContent={
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Sort Order</Label>
                  <SortToggle
                    sortOrder={sortOrder}
                    onToggle={(o) => { setSortOrder(o); list.setPage(1); }}
                    isFetching={repliesQuery.isFetching}
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
            emptyIcon={<Reply className="mb-3 h-10 w-10 text-muted-foreground" />}
            emptyMessage="No auto-reply drafts yet. Drafts will appear here as emails that warrant a response are processed."
            renderItem={(item: AutoReplyRecordResponse) => {
              const isExpanded = expandedIds.has(item.id);
              const isEditing = editingId === item.id;

              return (
                <FilterListItem
                  key={item.id}
                  icon={<Reply />}
                  title={item.mail_subject ?? "Untitled email"}
                  badges={
                    item.tone ? (
                      <Badge variant="secondary" className="shrink-0">
                        {item.tone}
                      </Badge>
                    ) : undefined
                  }
                  subtitle={
                    item.mail_from ? (
                      <p className="truncate text-xs text-muted-foreground">
                        {item.mail_from}
                      </p>
                    ) : undefined
                  }
                  preview={
                    isEditing ? (
                      <div className="space-y-3">
                        <div className="space-y-1.5">
                          <Label className="text-xs">Draft Body</Label>
                          <Textarea
                            value={editDraftBody}
                            onChange={(e) => setEditDraftBody(e.target.value)}
                            rows={6}
                            className="text-sm"
                          />
                        </div>
                        <div className="space-y-1.5">
                          <Label className="text-xs">Tone</Label>
                          <Input
                            value={editTone}
                            onChange={(e) => setEditTone(e.target.value)}
                            placeholder="e.g. professional, friendly, brief"
                            className="text-sm"
                          />
                        </div>
                        <div className="flex gap-2">
                          <AppButton
                            icon={<Save />}
                            label="Save"
                            variant="primary"
                            onClick={() => handleSaveEdit(item.id)}
                            disabled={updateMutation.isPending}
                            loading={updateMutation.isPending}
                          >
                            Save
                          </AppButton>
                          <AppButton
                            icon={<X />}
                            label="Cancel"
                            variant="outline"
                            onClick={handleCancelEdit}
                          >
                            Cancel
                          </AppButton>
                        </div>
                      </div>
                    ) : (
                      item.draft_body
                    )
                  }
                  expandable={!isEditing}
                  expanded={isExpanded}
                  onToggleExpand={() => toggleExpanded(item.id)}
                  expandedContent={
                    item.reasoning && !isEditing ? (
                      <div className="rounded-md border border-border bg-muted/50 px-3 py-2">
                        <p className="text-xs font-medium text-muted-foreground">
                          Reasoning
                        </p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {item.reasoning}
                        </p>
                      </div>
                    ) : undefined
                  }
                  date={formatDate(item.created_at)}
                  actions={
                    <>
                      <AppButton
                        icon={copiedId === item.id ? <Check /> : <Copy />}
                        label="Copy draft"
                        variant="ghost"
                        onClick={() => handleCopyDraft(item.id, item.draft_body)}
                      />
                      <AppButton
                        icon={<Pencil />}
                        label="Edit"
                        variant="ghost"
                        onClick={() => handleStartEdit(item)}
                        disabled={isEditing}
                      />
                      <SpamButton
                        variant="mail"
                        mailId={item.mail_uid}
                        mailAccountId={item.mail_account_id}
                        senderEmail={item.mail_from ?? ""}
                        subject={item.mail_subject}
                        onSuccess={() =>
                          queryClient.invalidateQueries({
                            queryKey: getListAutoRepliesApiAutoRepliesGetQueryKey(),
                          })
                        }
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
              );
            }}
          />
        </CardContent>
      </Card>

      {/* Settings Dialog */}
      <PluginSettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        title="Auto-Reply Settings"
        description="Configure auto-reply behavior."
      >
        <div className="py-4 text-center text-sm text-muted-foreground">
          No additional settings available for this plugin yet.
        </div>
      </PluginSettingsDialog>

      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete Auto-Reply Draft"
        description={
          <>
            Are you sure you want to remove the reply draft
            {deleteTarget?.mail_subject ? ` for "${deleteTarget.mail_subject}"` : ""}?
            This action cannot be undone.
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
