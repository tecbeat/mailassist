import {
  Mail,
  Pencil,
  Trash2,
  Plug,
  RefreshCw,
  Pause,
  Play,
} from "lucide-react";

import type { MailAccountResponse } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { ResourceStatusBanner } from "@/components/resource-status-banner";

import { formatRelativeTime } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Status badge helper
// ---------------------------------------------------------------------------

function AccountStatusBadge({ account }: { account: MailAccountResponse }) {
  if (account.is_paused && account.paused_reason === "circuit_breaker") {
    return <Badge variant="destructive">Circuit Breaker</Badge>;
  }
  if (account.is_paused) {
    return <Badge variant="warning">Paused</Badge>;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MailAccountRowProps {
  account: MailAccountResponse;
  onEdit: (account: MailAccountResponse) => void;
  onDelete: (account: MailAccountResponse) => void;
  onTest: (accountId: string) => void;
  onPoll: (accountId: string) => void;
  onPause: (accountId: string) => void;
  onUnpause: (accountId: string) => void;
  onResetHealth: (accountId: string) => void;
  testLoading: boolean;
  pollLoading: boolean;
  pauseLoading: boolean;
  unpauseLoading: boolean;
  resetHealthLoading: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MailAccountRow({
  account,
  onEdit,
  onDelete,
  onTest,
  onPoll,
  onPause,
  onUnpause,
  onResetHealth,
  testLoading,
  pollLoading,
  pauseLoading,
  unpauseLoading,
  resetHealthLoading,
}: MailAccountRowProps) {
  return (
    <div className="px-6 py-4 space-y-3">
      {/* Row 1: Name, status, action buttons */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <Mail className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="font-medium text-sm truncate">{account.name}</span>
          <AccountStatusBadge account={account} />
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <AppButton
            icon={account.is_paused ? <Play /> : <Pause />}
            label={account.is_paused ? "Resume" : "Pause"}
            variant="ghost"
            loading={pauseLoading || unpauseLoading}
            disabled={pauseLoading || unpauseLoading}
            onClick={() =>
              account.is_paused ? onUnpause(account.id) : onPause(account.id)
            }
          />
          <AppButton
            icon={<Pencil />}
            label="Edit"
            variant="ghost"
            onClick={() => onEdit(account)}
          />
          <AppButton
            icon={<Plug />}
            label="Test connection"
            variant="ghost"
            loading={testLoading}
            disabled={testLoading}
            onClick={() => onTest(account.id)}
          />
          <AppButton
            icon={<RefreshCw />}
            label="Poll now"
            variant="ghost"
            loading={pollLoading}
            disabled={pollLoading || account.is_paused}
            onClick={() => onPoll(account.id)}
          />
          <AppButton
            icon={<Trash2 />}
            label="Delete"
            variant="ghost"
            color="destructive"
            onClick={() => onDelete(account)}
          />
        </div>
      </div>

      {/* Row 2: Details grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-sm pl-7">
        <div>
          <span className="text-muted-foreground text-xs">Email</span>
          <p className="truncate font-mono text-xs">{account.email_address}</p>
        </div>
        <div>
          <span className="text-muted-foreground text-xs">IMAP</span>
          <p className="truncate font-mono text-xs">
            {account.imap_host}:{account.imap_port}
            {account.imap_use_ssl ? " (SSL)" : ""}
          </p>
        </div>
        <div>
          <span className="text-muted-foreground text-xs">Last Sync</span>
          <p className="text-xs">
            {account.last_sync_at
              ? formatRelativeTime(account.last_sync_at)
              : "Never"}
          </p>
        </div>
      </div>

      {/* Row 3: Pause info + excluded folders */}
      {(account.is_paused ||
        account.consecutive_errors > 0 ||
        (account.excluded_folders && account.excluded_folders.length > 0)) && (
        <div className="pl-7 space-y-2">
          <ResourceStatusBanner
            isPaused={account.is_paused}
            pausedReason={account.paused_reason}
            pausedAt={account.paused_at}
            consecutiveErrors={account.consecutive_errors}
            lastError={account.last_error}
            lastErrorAt={account.last_error_at}
            onResetHealth={() => onResetHealth(account.id)}
            resetHealthLoading={resetHealthLoading}
          />

          {account.excluded_folders && account.excluded_folders.length > 0 && (
            <p className="text-xs text-muted-foreground">
              Excluded: {account.excluded_folders.join(", ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
