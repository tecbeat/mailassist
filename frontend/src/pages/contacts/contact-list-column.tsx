import { ChevronLeft, ChevronRight, Search, X } from "lucide-react";

import type { ContactResponse } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryError } from "@/components/query-error";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MatchListItem } from "@/components/match-list-item";

import { getInitials } from "./contacts-schemas";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ContactListColumnProps {
  contacts: ContactResponse[];
  contactForSender: ContactResponse | null;
  selectedContact: ContactResponse | null;
  search: string;
  onSearchChange: (value: string) => void;
  debouncedSearch: string;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  isMutating: boolean;
  onContactClick: (contact: ContactResponse) => void;
  page: number;
  totalPages: number;
  totalItems: number;
  onPageChange: (page: number) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ContactListColumn({
  contacts,
  contactForSender,
  selectedContact,
  search,
  onSearchChange,
  debouncedSearch,
  isLoading,
  isError,
  onRetry,
  isMutating,
  onContactClick,
  page,
  totalPages,
  totalItems,
  onPageChange,
}: ContactListColumnProps) {
  return (
    <div className="min-w-0 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Contacts</h3>
        <Badge variant="secondary">{totalItems}</Badge>
      </div>

      {/* Search contacts */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="Search contacts..."
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

      {/* Contact list */}
      <ScrollArea className="h-[400px] rounded-md border">
        {isLoading ? (
          <div className="space-y-2 p-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full rounded-md" />
            ))}
          </div>
        ) : isError ? (
          <div className="p-4">
            <QueryError message="Failed to load contacts." onRetry={onRetry} />
          </div>
        ) : contacts.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            {debouncedSearch
              ? "No contacts match your search."
              : "No contacts synced yet."}
          </p>
        ) : (
          <div className="space-y-1 p-1">
            {(() => {
              const matchedContact = contactForSender;
              const otherContacts = matchedContact
                ? contacts.filter((c) => c.id !== matchedContact.id)
                : contacts;
              const contactsOrdered = matchedContact
                ? [matchedContact, ...otherContacts]
                : otherContacts;

              return contactsOrdered.map((contact) => {
                const isSelected = selectedContact?.id === contact.id;
                const isMatchedToSender = matchedContact?.id === contact.id;
                return (
                  <MatchListItem
                    key={contact.id}
                    disabled={isMutating}
                    marked={isSelected || isMatchedToSender}
                    onClick={() => onContactClick(contact)}
                    avatar={
                      contact.photo_url ? (
                        <img
                          src={contact.photo_url}
                          alt={contact.display_name}
                          className="h-8 w-8 rounded-full object-cover"
                        />
                      ) : (
                        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                          {getInitials(contact.display_name)}
                        </div>
                      )
                    }
                    title={contact.display_name}
                    subtitle={
                      contact.emails.length > 0
                        ? contact.emails.join(", ")
                        : undefined
                    }
                    badges={
                      isMatchedToSender ? (
                        <Badge variant="default">assigned</Badge>
                      ) : undefined
                    }
                  />
                );
              });
            })()}
          </div>
        )}
      </ScrollArea>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-1">
          <span className="text-xs text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <div className="flex items-center gap-1">
            <AppButton
              icon={<ChevronLeft />}
              label="Previous page"
              variant="ghost"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            />
            <AppButton
              icon={<ChevronRight />}
              label="Next page"
              variant="ghost"
              disabled={page >= totalPages}
              onClick={() => onPageChange(page + 1)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
