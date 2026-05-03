import { useState, useRef, useEffect, useCallback } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  KeyRound,
  Trash2,
  Copy,
  Check,
  Clock,
  Building2,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import { SpamButton } from "@/components/spam-button";

import {
  useListOtpCodesApiOtpCodesGet,
  useDeleteOtpCodeApiOtpCodesOtpIdDelete,
  getListOtpCodesApiOtpCodesGetQueryKey,
} from "@/services/api/otp/otp";

import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/layout/page-header";
import { SortFilterContent } from "@/components/sort-filter-content";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
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
  ExtractedOtpCodeResponse,
  ExtractedOtpCodeListResponse,
  ListOtpCodesApiOtpCodesGetSort,
} from "@/types/api/otp";

// ---------------------------------------------------------------------------
// Countdown hook
// ---------------------------------------------------------------------------

function useCountdown(expiresAt: string | null | undefined): string | null {
  const [label, setLabel] = useState<string | null>(null);

  const tick = useCallback(() => {
    if (!expiresAt) {
      setLabel(null);
      return;
    }
    const remaining = new Date(expiresAt).getTime() - Date.now();
    if (remaining <= 0) {
      setLabel("Expired");
      return;
    }
    const mins = Math.floor(remaining / 60000);
    const secs = Math.floor((remaining % 60000) / 1000);
    setLabel(`${mins}:${secs.toString().padStart(2, "0")}`);
  }, [expiresAt]);

  useEffect(() => {
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [tick]);

  return label;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isExpired(expiresAt: string | null | undefined): boolean {
  if (!expiresAt) return false;
  return new Date(expiresAt) < new Date();
}

const CODE_TYPE_COLORS: Record<string, string> = {
  otp: "bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
  "2fa": "bg-purple-50 text-purple-700 dark:bg-purple-950 dark:text-purple-300",
  verification: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  login: "bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300",
  magic_link: "bg-cyan-50 text-cyan-700 dark:bg-cyan-950 dark:text-cyan-300",
  other: "bg-muted text-muted-foreground",
};

// ---------------------------------------------------------------------------
// Countdown item
// ---------------------------------------------------------------------------

function CountdownBadge({ expiresAt }: { expiresAt: string | null }) {
  const remaining = useCountdown(expiresAt);
  const expired = expiresAt ? isExpired(expiresAt) : false;

  if (!expiresAt) {
    return <Badge variant="secondary">No expiry</Badge>;
  }

  if (expired) {
    return <Badge variant="destructive">Expired</Badge>;
  }

  if (remaining === "Expired") {
    return <Badge variant="destructive">Expired</Badge>;
  }

  return (
    <Badge variant="default" className="font-mono tabular-nums">
      <Clock className="mr-1 h-3 w-3" />
      {remaining}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function OtpCodesPage() {
  usePageTitle("OTP Codes");
  const list = useSearchableList();
  const [activeOnly, setActiveOnly] = useState(false);
  const [sortOrder, setSortOrder] = useState<"newest" | "oldest">("newest");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const copyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ExtractedOtpCodeResponse | null>(null);
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
    sort: sortOrder as ListOtpCodesApiOtpCodesGetSort,
    ...(list.searchFilter ? { service: list.searchFilter } : {}),
    ...(activeOnly ? { active_only: true } : {}),
  };

  const otpQuery = useListOtpCodesApiOtpCodesGet(params, {
    query: { refetchInterval: 10_000 },
  });
  const listData = unwrapResponse<ExtractedOtpCodeListResponse>(otpQuery.data);

  const items = listData?.items ?? [];
  const totalPages = listData?.pages ?? 1;

  const deleteMutation = useDeleteOtpCodeApiOtpCodesOtpIdDelete();

  const hasActiveFilters = activeOnly || sortOrder !== "newest";

  function invalidateList() {
    queryClient.invalidateQueries({
      queryKey: getListOtpCodesApiOtpCodesGetQueryKey(),
    });
  }

  async function handleDelete(id: string) {
    try {
      await deleteMutation.mutateAsync({ otpId: id });
      invalidateList();
      setDeleteTarget(null);
      toast({ title: "Code removed", description: "The OTP code has been permanently deleted." });
    } catch {
      toast({ title: "Failed to remove code", description: "Could not delete the OTP code. Please try again.", variant: "destructive" });
    }
  }

  async function handleCopyCode(id: string, code: string) {
    try {
      await navigator.clipboard.writeText(code);
      setCopiedId(id);
      if (copyTimerRef.current) clearTimeout(copyTimerRef.current);
      copyTimerRef.current = setTimeout(() => setCopiedId(null), 2000);
    } catch {
      toast({ title: "Failed to copy", description: "Could not copy the code to clipboard.", variant: "destructive" });
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="OTP Codes"
        description="One-time passwords and verification codes extracted from your emails."
      />

      <Card>
        <CardHeader>
          <CardTitle>Extracted OTP Codes</CardTitle>
          <CardDescription>
            Security codes will appear here as they are extracted from your emails.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <SearchableCardList
            list={list}
            items={items}
            totalPages={totalPages}
            totalCount={listData?.total ?? 0}
            isError={otpQuery.isError}
            isLoading={otpQuery.isLoading}
            isFetching={otpQuery.isFetching}
            errorMessage="Failed to load OTP codes."
            onRetry={() => otpQuery.refetch()}
            searchPlaceholder="Search by service..."
            hasActiveFilters={hasActiveFilters}
            filterContent={
              <SortFilterContent
                sortOrder={sortOrder}
                onSortChange={(o) => { setSortOrder(o); list.setPage(1); }}
                isFetching={otpQuery.isFetching}
                hasActiveFilters={hasActiveFilters}
                onClearFilters={() => { setActiveOnly(false); setSortOrder("newest"); list.setPage(1); }}
              >
                <div className="flex items-center justify-between">
                  <Label htmlFor="otp-active-only-switch" className="text-xs">Active only</Label>
                  <Switch
                    id="otp-active-only-switch"
                    checked={activeOnly}
                    onCheckedChange={(checked) => {
                      setActiveOnly(checked);
                      list.setPage(1);
                    }}
                  />
                </div>
              </SortFilterContent>
            }
            emptyIcon={<KeyRound className="mb-3 h-10 w-10 text-muted-foreground" />}
            emptyMessage="No OTP codes found. Security codes will appear here as they are extracted from your emails."
            renderItem={(otp: ExtractedOtpCodeResponse) => {
              return (
                <FilterListItem
                  key={otp.id}
                  className={otp.is_expired ? "opacity-60" : undefined}
                  icon={<KeyRound />}
                  title={
                    <code className="rounded bg-muted px-2 py-0.5 text-sm font-mono font-bold tracking-wider">
                      {otp.code}
                    </code>
                  }
                  badges={
                    <>
                      <span className={`inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium ${CODE_TYPE_COLORS[otp.code_type] ?? CODE_TYPE_COLORS.other}`}>
                        {otp.code_type.replace("_", " ")}
                      </span>
                    </>
                  }
                  subtitle={
                    <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                      {otp.service && (
                        <span className="flex items-center gap-1">
                          <Building2 className="h-3 w-3" />
                          {otp.service}
                        </span>
                      )}
                      <CountdownBadge expiresAt={otp.expires_at} />
                    </div>
                  }
                  date={formatDate(otp.created_at)}
                  actions={
                    <>
                      {otp.sender_email && (
                        <SpamButton
                          variant="mail"
                          mailId={otp.mail_uid}
                          mailAccountId={otp.mail_account_id}
                          senderEmail={otp.sender_email}
                          subject={otp.mail_subject}
                          onSuccess={invalidateList}
                        />
                      )}
                      <AppButton
                        icon={copiedId === otp.id ? <Check /> : <Copy />}
                        label="Copy code"
                        variant="ghost"
                        onClick={() => handleCopyCode(otp.id, otp.code)}
                      />
                      <AppButton
                        icon={<Trash2 />}
                        label="Delete"
                        variant="ghost"
                        color="destructive"
                        onClick={() => setDeleteTarget(otp)}
                      />
                    </>
                  }
                />
              );
            }}
          />
        </CardContent>
      </Card>

      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
        title="Delete OTP Code"
        description={
          <>
            Are you sure you want to delete the OTP code{" "}
            <span className="font-medium font-mono">{deleteTarget?.code}</span>
            {deleteTarget?.service ? ` from ${deleteTarget.service}` : ""}? This
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
