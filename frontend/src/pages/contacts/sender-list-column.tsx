import { Search, Mail, X, UserPlus } from "lucide-react";

import type { ContactResponse, SenderResponse } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryError } from "@/components/query-error";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MatchListItem } from "@/components/match-list-item";
import { SpamButton } from "@/components/spam-button";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface SenderListColumnProps {
  senders: SenderResponse[];
  selectedContact: ContactResponse | null;
  selectedSender: SenderResponse | null;
  search: string;
  onSearchChange: (value: string) => void;
  debouncedSearch: string;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  isMutating: boolean;
  onSenderClick: (sender: SenderResponse) => void;
  onCreateContact: (email: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SenderListColumn({
  senders,
  selectedContact,
  selectedSender,
  search,
  onSearchChange,
  debouncedSearch,
  isLoading,
  isError,
  onRetry,
  isMutating,
  onSenderClick,
  onCreateContact,
}: SenderListColumnProps) {
  return (
    <div className="min-w-0 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Senders</h3>
        <Badge variant="secondary">{senders.length}</Badge>
      </div>

      {/* Search senders */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search senders..."
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9"
        />
        {search && (
          <AppButton
            icon={<X />}
            label="Clear search"
            variant="ghost"
            className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2"
            onClick={() => onSearchChange("")}
          />
        )}
      </div>

      {/* Sender list */}
      <ScrollArea className="h-[400px] rounded-md border">
        {isLoading ? (
          <div className="space-y-2 p-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full rounded-md" />
            ))}
          </div>
        ) : isError ? (
          <div className="p-4">
            <QueryError message="Failed to load senders." onRetry={onRetry} />
          </div>
        ) : senders.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {debouncedSearch
              ? "No senders match your search."
              : "No emails in the database yet."}
          </p>
        ) : (
          <div className="space-y-1 p-1">
            {senders.map((sender) => {
              const isSelected = selectedSender?.email_address === sender.email_address;
              const isAssignedToSelected = selectedContact
                ? selectedContact.emails.some(
                    (e) => e.toLowerCase() === sender.email_address.toLowerCase(),
                  )
                : false;
              const isAssignedToAny = sender.matched_contact_id !== null;

              return (
                <MatchListItem
                  key={sender.email_address}
                  as={isSelected ? "div" : "button"}
                  disabled={isMutating}
                  marked={isSelected || (isAssignedToSelected && !isSelected)}
                  onClick={() => onSenderClick(sender)}
                  avatar={<Mail className="h-4 w-4 text-muted-foreground" />}
                  title={sender.email_address}
                  badges={
                    <>
                      {sender.mail_count > 0 && (
                        <Badge variant="secondary">
                          {sender.mail_count} {sender.mail_count === 1 ? "mail" : "mails"}
                        </Badge>
                      )}
                      {(isAssignedToSelected || isAssignedToAny) && (
                        <Badge variant="default" className="shrink-0">
                          assigned
                        </Badge>
                      )}
                    </>
                  }
                  action={
                    isSelected && !isAssignedToAny ? (
                      <AppButton
                        icon={<UserPlus />}
                        label="Create Contact"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          onCreateContact(sender.email_address);
                        }}
                      />
                    ) : !isSelected && !isAssignedToSelected ? (
                      <SpamButton
                        variant="email"
                        emailAddress={sender.email_address}
                      />
                    ) : undefined
                  }
                />
              );
            })}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
