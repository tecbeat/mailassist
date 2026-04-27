import { useState, useMemo } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { Mail } from "lucide-react";

import {
  useGetFolderSummaryApiFoldersSummaryGet,
} from "@/services/api/folders/folders";
import {
  useListMailAccountsApiMailAccountsGet,
  useListFoldersApiMailAccountsAccountIdFoldersGet,
} from "@/services/api/mail-accounts/mail-accounts";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { cn, unwrapResponse } from "@/lib/utils";
import type {
  FolderSummaryListResponse,
  MailAccountResponse,
  ImapFolderListResponse,
} from "@/types/api";

import { FolderTreePanel } from "./folder-tree-panel";

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function SmartFoldersPage() {
  usePageTitle("Smart Folders");
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null);

  const accountsQuery = useListMailAccountsApiMailAccountsGet();
  const mailAccounts = unwrapResponse<MailAccountResponse[]>(accountsQuery.data);

  const summaryQuery = useGetFolderSummaryApiFoldersSummaryGet();
  const summaryData = unwrapResponse<FolderSummaryListResponse>(summaryQuery.data);
  const summaryItems = summaryData?.items ?? [];

  const smartFolderNames = useMemo(
    () => new Set(summaryItems.map((s) => s.folder)),
    [summaryItems],
  );

  // Auto-select first account when data loads
  const effectiveAccountId = selectedAccountId ?? mailAccounts?.[0]?.id ?? null;

  const selectedAccount = mailAccounts?.find((a) => a.id === effectiveAccountId);

  const foldersQuery = useListFoldersApiMailAccountsAccountIdFoldersGet(
    effectiveAccountId ?? "",
    { counts: true },
    { query: { enabled: !!effectiveAccountId, staleTime: 30_000 } },
  );
  const foldersData = unwrapResponse<ImapFolderListResponse>(foldersQuery.data);
  const excludedCount = foldersData?.excluded_folders?.length ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Smart Folders"
        description="Manage your IMAP folder structure. Drag folders to reorganize, exclude folders from AI processing, or delete unused folders."
      />

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* ---------------------------------------------------------------- */}
        {/* Left sidebar - mail accounts                                     */}
        {/* ---------------------------------------------------------------- */}
        <div className="w-full shrink-0 lg:w-64">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Accounts</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {accountsQuery.isLoading ? (
                <div className="space-y-2 px-4 pb-4">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-8 w-full" />
                  ))}
                </div>
              ) : !mailAccounts || mailAccounts.length === 0 ? (
                <p className="px-4 pb-4 text-sm text-muted-foreground">
                  No mail accounts configured.
                </p>
              ) : (
                <nav className="flex flex-col">
                  {mailAccounts.map((account) => {
                    const isSelected = account.id === effectiveAccountId;
                    return (
                      <button
                        key={account.id}
                        onClick={() => setSelectedAccountId(account.id)}
                        aria-current={isSelected ? "page" : undefined}
                        className={cn(
                          "flex items-center gap-2 px-4 py-2.5 text-left text-sm transition-colors hover:bg-accent",
                          isSelected && "bg-accent font-medium",
                        )}
                      >
                        <Mail className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <div className="min-w-0 flex-1">
                          <span className="block truncate">{account.name}</span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {account.email_address}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </nav>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Right panel - folder tree                                        */}
        {/* ---------------------------------------------------------------- */}
        <div className="min-w-0 flex-1 space-y-4">
          {/* Header */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold">
                  {selectedAccount?.name ?? "Folder Structure"}
                </h2>
                {excludedCount > 0 && (
                  <Badge variant="secondary">
                    {excludedCount} folder{excludedCount !== 1 ? "s" : ""} excluded
                  </Badge>
                )}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                Drag folders to reorganize, exclude from AI processing, or delete unused folders. System folders cannot be modified.
              </p>
            </div>
          </div>

          {/* Folder tree area */}
          {effectiveAccountId ? (
            <div className="space-y-2">
              <label className="text-sm font-medium">Folder Structure</label>
              <div className="overflow-auto rounded-md border border-input bg-background px-3 py-2 text-sm min-h-[200px] md:min-h-[300px]">
                <FolderTreePanel
                  key={effectiveAccountId}
                  accountId={effectiveAccountId}
                  smartFolderNames={smartFolderNames}
                />
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-md border border-input bg-background py-12 text-center">
              <Mail className="mb-3 h-10 w-10 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Select a mail account to view its folder structure.
              </p>
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
