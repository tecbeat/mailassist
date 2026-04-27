import { useCallback, useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { Mail, Plus, RotateCcw, ShieldAlert, Trash2, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { z } from "zod/v4";

import {
  getListBlocklistApiSpamBlocklistGetQueryKey,
  useCreateBlocklistEntryApiSpamBlocklistPost,
  useDeleteBlocklistEntryApiSpamBlocklistEntryIdDelete,
  useListBlocklistApiSpamBlocklistGet,
} from "@/services/api/spam/spam";
import {
  useListApprovalsApiApprovalsGet,
} from "@/services/api/approvals/approvals";
import type {
  ApprovalListResponse,
  ApprovalResponse,
  BlocklistEntryResponse,
  BlocklistListResponse,
  ListBlocklistApiSpamBlocklistGetParams,
} from "@/types/api";
import type { BlocklistEntryType } from "@/types/api/blocklistEntryType";

import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/layout/page-header";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import { SearchableCardList } from "@/components/searchable-card-list";
import { FilterListItem } from "@/components/filter-list-item";
import { useSearchableList } from "@/hooks/use-searchable-list";
import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { formatDate, formatRelativeTime, unwrapResponse } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

const TYPE_LABELS: Record<string, string> = {
  email: "Email",
  domain: "Domain",
  pattern: "Pattern",
};

const SOURCE_LABELS: Record<string, string> = {
  manual: "Manual",
  reported: "Reported",
};

const TYPE_BADGE_VARIANTS: Record<string, "default" | "secondary"> = {
  email: "default",
  domain: "secondary",
  pattern: "secondary",
};

const APPROVAL_STATUS_VARIANTS: Record<string, "success" | "destructive" | "warning" | "secondary"> = {
  pending: "warning",
  approved: "success",
  rejected: "destructive",
  expired: "secondary",
};

const blocklistEntrySchema = z.object({
  entry_type: z.enum(["email", "domain", "pattern"]),
  value: z.string().min(1, "Value is required"),
});

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function SpamPage() {
  usePageTitle("Spam");
  const detectedList = useSearchableList({ perPage: 10 });
  const blocklistList = useSearchableList();
  const [typeFilter, setTypeFilter] = useState<string | undefined>(undefined);
  const [deleteTarget, setDeleteTarget] = useState<BlocklistEntryResponse | null>(null);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [newType, setNewType] = useState("email");
  const [newValue, setNewValue] = useState("");
  const [addError, setAddError] = useState<string | null>(null);

  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Detected spam -- approvals with function_type=spam_detection
  const detectedQuery = useListApprovalsApiApprovalsGet(
    { function_type: "spam_detection", sort: "newest", page: detectedList.page, per_page: detectedList.perPage },
  );
  const detectedData = unwrapResponse<ApprovalListResponse>(detectedQuery.data);
  const detectedItems = detectedData?.items ?? [];
  const detectedTotalPages = detectedData?.pages ?? 1;
  const detectedTotal = detectedData?.total ?? 0;

  const params: ListBlocklistApiSpamBlocklistGetParams = {
    page: blocklistList.page,
    per_page: blocklistList.perPage,
    ...(blocklistList.searchFilter ? { search: blocklistList.searchFilter } : {}),
    ...(typeFilter ? { entry_type: typeFilter as BlocklistEntryType } : {}),
  };

  const blocklistQuery = useListBlocklistApiSpamBlocklistGet(params);
  const listData = unwrapResponse<BlocklistListResponse>(blocklistQuery.data);

  const items = listData?.items ?? [];
  const totalPages = listData?.pages ?? 1;
  const total = listData?.total ?? 0;

  const deleteMutation = useDeleteBlocklistEntryApiSpamBlocklistEntryIdDelete();
  const createMutation = useCreateBlocklistEntryApiSpamBlocklistPost();

  const hasActiveFilters = !!typeFilter;

  const handleDelete = useCallback(
    async (id: string) => {
      try {
        await deleteMutation.mutateAsync({ entryId: id });
        queryClient.invalidateQueries({
          queryKey: getListBlocklistApiSpamBlocklistGetQueryKey(params),
        });
        setDeleteTarget(null);
        toast({ title: "Blocklist entry removed", description: "The entry has been deleted from the blocklist." });
      } catch {
        toast({ title: "Failed to remove entry", description: "Could not delete the blocklist entry. Please try again.", variant: "destructive" });
      }
    },
    [deleteMutation, queryClient, toast, params],
  );

  const handleAdd = useCallback(async () => {
    const result = blocklistEntrySchema.safeParse({ entry_type: newType, value: newValue.trim() });
    if (!result.success) {
      setAddError(result.error.issues[0]?.message ?? "Invalid input");
      return;
    }
    setAddError(null);
    try {
      await createMutation.mutateAsync({
        data: result.data,
      });
      queryClient.invalidateQueries({
        queryKey: getListBlocklistApiSpamBlocklistGetQueryKey(params),
      });
      setAddDialogOpen(false);
      setNewValue("");
      setNewType("email");
      toast({ title: "Entry added to blocklist", description: "The new entry will be used for spam filtering." });
    } catch (err) {
      toast({
        title: "Failed to add entry",
        description: err instanceof Error ? err.message : "Unknown error",
        variant: "destructive",
      });
    }
  }, [newType, newValue, createMutation, queryClient, toast, params]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Spam Detection"
        description="Manage blocked senders, domains, and patterns. Blocked entries are automatically used by the spam detection plugin."
        actions={
          <div className="flex items-center gap-2">
            <AppButton icon={<Plus />} label="Add Entry" variant="primary" onClick={() => setAddDialogOpen(true)}>
              Add Entry
            </AppButton>
          </div>
        }
      />

      {/* Detected Spam -- emails flagged by AI */}
      <Card>
        <CardHeader>
          <CardTitle>Detected Spam</CardTitle>
          <CardDescription>
            Emails flagged as spam by the AI plugin. Only emails that required
            approval review are shown here.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList
            list={detectedList}
            items={detectedItems}
            totalPages={detectedTotalPages}
            totalCount={detectedTotal}
            isError={detectedQuery.isError}
            isLoading={detectedQuery.isLoading}
            isFetching={detectedQuery.isFetching}
            errorMessage="Failed to load detected spam"
            onRetry={() => detectedQuery.refetch()}
            searchMode="none"
            hideFilter
            emptyIcon={<Mail className="mb-3 h-10 w-10 text-muted-foreground" />}
            emptyMessage="No spam detections yet. Emails flagged by the AI will appear here."
            renderItem={(item: ApprovalResponse) => (
              <FilterListItem
                key={item.id}
                title={item.mail_subject || "(no subject)"}
                badges={
                  <Badge
                    variant={APPROVAL_STATUS_VARIANTS[item.status] ?? "secondary"}
                  >
                    {item.status}
                  </Badge>
                }
                subtitle={
                  <>
                    <p className="mt-1 truncate text-xs text-muted-foreground">
                      From: {item.mail_from}
                    </p>
                    {item.ai_reasoning && (
                      <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
                        {item.ai_reasoning}
                      </p>
                    )}
                  </>
                }
                date={formatRelativeTime(item.created_at)}
              />
            )}
          />
        </CardContent>
      </Card>

      {/* Blocklist Card */}
      <Card>
        <CardHeader>
          <CardTitle>Blocklist</CardTitle>
          <CardDescription>
            Blocked email addresses, domains, and subject patterns. Entries are
            created when you report spam or add them manually.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList
            list={blocklistList}
            items={items}
            totalPages={totalPages}
            totalCount={total}
            isError={blocklistQuery.isError}
            isLoading={blocklistQuery.isLoading}
            isFetching={blocklistQuery.isFetching}
            errorMessage="Failed to load blocklist"
            onRetry={() => blocklistQuery.refetch()}
            searchPlaceholder="Search blocklist..."
            hasActiveFilters={hasActiveFilters}
            filterContent={
              <div className="space-y-3">
                <div className="space-y-1.5">
                  <Label className="text-xs">Entry Type</Label>
                  <Select
                    value={typeFilter ?? "all"}
                    onValueChange={(v) => {
                      setTypeFilter(v === "all" ? undefined : v);
                      blocklistList.setPage(1);
                    }}
                  >
                    <SelectTrigger className="h-8 text-xs">
                      <SelectValue placeholder="All types" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All types</SelectItem>
                      <SelectItem value="email">Email</SelectItem>
                      <SelectItem value="domain">Domain</SelectItem>
                      <SelectItem value="pattern">Pattern</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {hasActiveFilters && (
                  <AppButton
                    icon={<RotateCcw />}
                    label="Clear filters"
                    variant="ghost"
                    className="h-7 w-full text-xs"
                    onClick={() => {
                      setTypeFilter(undefined);
                      blocklistList.setPage(1);
                    }}
                  >
                    Clear filters
                  </AppButton>
                )}
              </div>
            }
            emptyIcon={<ShieldAlert className="mb-3 h-10 w-10 text-muted-foreground" />}
            emptyMessage={
              blocklistList.searchFilter || typeFilter
                ? "No entries match your filters."
                : "No blocklist entries yet. Entries are created when you report spam or add them manually."
            }
            renderItem={(entry: BlocklistEntryResponse) => (
              <FilterListItem
                key={entry.id}
                title={
                  <span className="truncate font-mono text-sm font-medium">
                    {entry.value}
                  </span>
                }
                badges={
                  <Badge
                    variant={TYPE_BADGE_VARIANTS[entry.entry_type] ?? "secondary"}
                  >
                    {TYPE_LABELS[entry.entry_type] ?? entry.entry_type}
                  </Badge>
                }
                subtitle={
                  <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                    <span>
                      Source: {SOURCE_LABELS[entry.source] ?? entry.source}
                    </span>
                    <span>{formatDate(entry.created_at)}</span>
                    {entry.source_mail_uid && (
                      <span>Mail UID: {entry.source_mail_uid}</span>
                    )}
                  </div>
                }
                actions={
                  <AppButton
                    icon={<Trash2 />}
                    label="Delete"
                    variant="ghost"
                    color="destructive"
                    onClick={() => setDeleteTarget(entry)}
                  />
                }
              />
            )}
          />
        </CardContent>
      </Card>

      {/* Delete confirm dialog */}
      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
        title="Remove Blocklist Entry"
        description={
          <>
            Are you sure you want to remove{" "}
            <span className="font-medium font-mono">
              {deleteTarget?.value}
            </span>{" "}
            from the blocklist? Future emails from this sender/domain will
            no longer be automatically blocked.
          </>
        }
        onConfirm={() => {
          if (deleteTarget) handleDelete(deleteTarget.id);
        }}
        isPending={deleteMutation.isPending}
      />

      {/* Add entry dialog */}
      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Blocklist Entry</DialogTitle>
            <DialogDescription>
              Manually block an email address, domain, or subject pattern.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label>Type</Label>
              <Select value={newType} onValueChange={setNewType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="email">
                    Email Address
                  </SelectItem>
                  <SelectItem value="domain">Domain</SelectItem>
                  <SelectItem value="pattern">
                    Subject Pattern
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>
                {newType === "email"
                  ? "Email Address"
                  : newType === "domain"
                    ? "Domain"
                    : "Subject Pattern"}
              </Label>
              <Input
                placeholder={
                  newType === "email"
                    ? "spammer@example.com"
                    : newType === "domain"
                      ? "example.com"
                      : "Buy now cheap"
                }
                value={newValue}
                onChange={(e) => { setNewValue(e.target.value); setAddError(null); }}
                onKeyDown={(e) => e.key === "Enter" && handleAdd()}
              />
              {addError && <p className="text-xs text-destructive">{addError}</p>}
            </div>
          </div>
          <DialogFooter>
            <AppButton
              icon={<X />}
              label="Cancel"
              onClick={() => setAddDialogOpen(false)}
              disabled={createMutation.isPending}
            >
              Cancel
            </AppButton>
            <AppButton
              icon={<Plus />}
              label="Add to Blocklist"
              variant="primary"
              onClick={handleAdd}
              disabled={!newValue.trim() || createMutation.isPending}
              loading={createMutation.isPending}
            >
              Add to Blocklist
            </AppButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
