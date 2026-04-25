import { useState, useRef, useEffect } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  Ticket,
  Trash2,
  Check,
  Copy,
  Undo2,
  Store,
  Clock,
  RotateCcw,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { SpamButton } from "@/components/spam-button";

import {
  useListCouponsApiCouponsGet,
  useUpdateCouponApiCouponsCouponIdPatch,
  useDeleteCouponApiCouponsCouponIdDelete,
  getListCouponsApiCouponsGetQueryKey,
} from "@/services/api/coupons/coupons";

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
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { formatDate, unwrapResponse } from "@/lib/utils";
import type {
  ExtractedCouponResponse,
  ExtractedCouponListResponse,
  ListCouponsApiCouponsGetSort,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isExpired(expiresAt: string | null | undefined): boolean {
  if (!expiresAt) return false;
  return new Date(expiresAt) < new Date();
}

function formatExpiry(expiresAt: string | null | undefined): string | null {
  if (!expiresAt) return null;
  return new Date(expiresAt).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function CouponsPage() {
  usePageTitle("Coupons");
  const list = useSearchableList();
  const [activeOnly, setActiveOnly] = useState(false);
  const [sortOrder, setSortOrder] = useState<string>("newest");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
    };
  }, []);
  const [deleteTarget, setDeleteTarget] = useState<ExtractedCouponResponse | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const params = {
    page: list.page,
    per_page: list.perPage,
    sort: sortOrder as ListCouponsApiCouponsGetSort,
    ...(list.searchFilter ? { store: list.searchFilter } : {}),
    ...(activeOnly ? { active_only: true } : {}),
  };

  const couponsQuery = useListCouponsApiCouponsGet(params, {
    query: { refetchInterval: 60_000 },
  });
  const listData = unwrapResponse<ExtractedCouponListResponse>(couponsQuery.data);

  const items = listData?.items ?? [];
  const totalPages = listData?.pages ?? 1;

  const updateMutation = useUpdateCouponApiCouponsCouponIdPatch();
  const deleteMutation = useDeleteCouponApiCouponsCouponIdDelete();

  const hasActiveFilters = activeOnly || sortOrder !== "newest";

  function invalidateList() {
    queryClient.invalidateQueries({
      queryKey: getListCouponsApiCouponsGetQueryKey(params),
    });
  }

  async function handleToggleUsed(coupon: ExtractedCouponResponse) {
    try {
      await updateMutation.mutateAsync({
        couponId: coupon.id,
        data: { is_used: !coupon.is_used },
      });
      invalidateList();
      toast({ title: coupon.is_used ? "Coupon marked as unused" : "Coupon marked as used", description: `The coupon status has been updated.` });
    } catch {
      toast({ title: "Failed to update coupon", description: "Could not change the coupon status. Please try again.", variant: "destructive" });
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteMutation.mutateAsync({ couponId: id });
      invalidateList();
      setDeleteTarget(null);
      toast({ title: "Coupon removed", description: "The coupon has been permanently deleted." });
    } catch {
      toast({ title: "Failed to remove coupon", description: "Could not delete the coupon. Please try again.", variant: "destructive" });
    }
  }

  async function handleCopyCode(id: string, code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedId(id);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedId(null), 2000);
    } catch {
      toast({ title: "Failed to copy", description: "Could not copy the coupon code to clipboard.", variant: "destructive" });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Coupons"
        description="Coupons and promotional offers extracted from your emails."
        actions={
          <div className="flex items-center gap-2">
            <PluginSettingsButton onClick={() => setSettingsOpen(true)} />
          </div>
        }
      />

      {/* Coupon List Card */}
      <Card>
        <CardHeader>
          <CardTitle>Extracted Coupons</CardTitle>
          <CardDescription>
            Coupons will appear here as they are extracted from your emails.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList
            list={list}
            items={items}
            totalPages={totalPages}
            totalCount={listData?.total ?? 0}
            isError={couponsQuery.isError}
            isLoading={couponsQuery.isLoading}
            isFetching={couponsQuery.isFetching}
            errorMessage="Failed to load coupons."
            onRetry={() => couponsQuery.refetch()}
            searchPlaceholder="Search by store..."
            hasActiveFilters={hasActiveFilters}
            filterContent={
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label htmlFor="active-only-switch" className="text-xs">Active only</Label>
                  <Switch
                    id="active-only-switch"
                    checked={activeOnly}
                    onCheckedChange={(checked) => {
                      setActiveOnly(checked);
                      list.setPage(1);
                    }}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Sort Order</Label>
                   <SortToggle
                    sortOrder={sortOrder}
                    onToggle={(o) => { setSortOrder(o); list.setPage(1); }}
                    isFetching={couponsQuery.isFetching}
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
                      setActiveOnly(false);
                      setSortOrder("newest");
                      list.setPage(1);
                    }}
                  >
                    Clear filters
                  </AppButton>
                )}
              </div>
            }
            emptyIcon={<Ticket className="mb-3 h-10 w-10 text-muted-foreground" />}
            emptyMessage="No coupons found. Coupons will appear here as they are extracted from your emails."
            renderItem={(coupon: ExtractedCouponResponse) => {
              const expired = isExpired(coupon.expires_at);
              const expiryLabel = formatExpiry(coupon.expires_at);

              return (
                <FilterListItem
                  key={coupon.id}
                  className={coupon.is_used ? "opacity-60" : undefined}
                  icon={<Ticket />}
                  title={
                    coupon.code ? (
                      <code className="rounded bg-muted px-2 py-0.5 text-sm font-mono font-semibold">
                        {coupon.code}
                      </code>
                    ) : (
                      <span className="text-sm font-semibold">
                        {coupon.description || "Promotion"}
                      </span>
                    )
                  }
                  badges={
                    coupon.is_used ? (
                      <Badge variant="secondary">Used</Badge>
                    ) : expired ? (
                      <Badge variant="destructive">Expired</Badge>
                    ) : (
                      <Badge variant="default">Active</Badge>
                    )
                  }
                  subtitle={
                    <>
                      {coupon.code && coupon.description && (
                        <p className="mt-1 text-sm text-muted-foreground">
                          {coupon.description}
                        </p>
                      )}
                      <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                        {coupon.store && (
                          <span className="flex items-center gap-1">
                            <Store className="h-3 w-3" />
                            {coupon.store}
                          </span>
                        )}
                        {(coupon.valid_from || expiryLabel) && (
                          <span className="flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {coupon.valid_from && expiryLabel
                              ? `${formatExpiry(coupon.valid_from)} – ${expiryLabel}`
                              : coupon.valid_from
                                ? `From ${formatExpiry(coupon.valid_from)}`
                                : `Expires ${expiryLabel}`}
                          </span>
                        )}
                      </div>
                    </>
                  }
                  date={formatDate(coupon.created_at)}
                  actions={
                    <>
                      {coupon.sender_email && (
                        <SpamButton
                          variant="mail"
                          mailId={coupon.mail_uid}
                          mailAccountId={coupon.mail_account_id}
                          senderEmail={coupon.sender_email}
                          subject={coupon.mail_subject}
                          onSuccess={invalidateList}
                        />
                      )}
                      {coupon.code && (
                        <AppButton
                          icon={copiedId === coupon.id ? <Check /> : <Copy />}
                          label="Copy code"
                          variant="ghost"
                          onClick={() => handleCopyCode(coupon.id, coupon.code!)}
                        />
                      )}
                      <AppButton
                        icon={coupon.is_used ? <Undo2 /> : <Check />}
                        label={coupon.is_used ? "Mark as unused" : "Mark as used"}
                        variant="ghost"
                        onClick={() => handleToggleUsed(coupon)}
                        disabled={updateMutation.isPending}
                      />
                      <AppButton
                        icon={<Trash2 />}
                        label="Delete"
                        variant="ghost"
                        color="destructive"
                        onClick={() => setDeleteTarget(coupon)}
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
        title="Coupon Extraction Settings"
        description="Configure coupon extraction behavior."
      >
        <div className="py-4 text-center text-sm text-muted-foreground">
          No additional settings available for this plugin yet.
        </div>
      </PluginSettingsDialog>

      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete Coupon"
        description={
          <>
            Are you sure you want to delete the coupon{" "}
            <span className="font-medium font-mono">{deleteTarget?.code || deleteTarget?.description || "this promotion"}</span>
            {deleteTarget?.store ? ` from ${deleteTarget.store}` : ""}? This
            action cannot be undone.
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
