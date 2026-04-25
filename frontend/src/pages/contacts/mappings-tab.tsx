import { useState, useEffect, useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useDebounce } from "@/hooks/use-debounce";
import {
  useListContactsApiContactsGet,
  useListAllSendersApiContactsSendersGet,
  useAssignEmailToContactApiContactsContactIdEmailsPost,
  useRemoveEmailFromContactEndpointApiContactsContactIdEmailsDelete,
} from "@/services/api/contacts/contacts";
import type {
  ContactResponse,
  ContactListResponse,
  AssignEmailResponse,
  RemoveEmailResponse,
  SenderResponse,
} from "@/types/api";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { unwrapResponse } from "@/lib/utils";

import { DEBOUNCE_MS } from "./contacts-schemas";
import { ContactListColumn } from "./contact-list-column";
import { SenderListColumn } from "./sender-list-column";
import { CreateContactDialog } from "./create-contact-dialog";

const CONTACTS_PER_PAGE = 20;

// ---------------------------------------------------------------------------
// Mappings Tab — Two-Column Matching UI
// ---------------------------------------------------------------------------

export function MappingsTab({ onContactSelect }: { onContactSelect?: (contact: ContactResponse | null) => void }) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // --- State: either a contact OR a sender can be selected, never both ---
  const [selectedContact, setSelectedContact] = useState<ContactResponse | null>(null);
  const [selectedSender, setSelectedSender] = useState<SenderResponse | null>(null);
  const [contactSearch, setContactSearch] = useState("");
  const [senderSearch, setSenderSearch] = useState("");
  const [contactPage, setContactPage] = useState(1);

  // Dialog state lifted here so the dialog survives sender deselection
  const [createContactEmail, setCreateContactEmail] = useState<string | null>(null);

  const debouncedContactSearch = useDebounce(contactSearch, DEBOUNCE_MS);
  const debouncedSenderSearch = useDebounce(senderSearch, DEBOUNCE_MS);

  // Notify parent of contact selection changes
  useEffect(() => {
    onContactSelect?.(selectedContact);
  }, [selectedContact, onContactSelect]);

  // Reset to page 1 when search changes
  useEffect(() => {
    setContactPage(1);
  }, [debouncedContactSearch]);

  // --- Queries ---
  const contactsQuery = useListContactsApiContactsGet({
    search: debouncedContactSearch || undefined,
    page: contactPage,
    per_page: CONTACTS_PER_PAGE,
  });
  const contactsData = unwrapResponse<ContactListResponse>(contactsQuery.data);
  const allContacts: ContactResponse[] = contactsData?.items ?? [];
  const contactsTotalPages = contactsData?.pages ?? 1;
  const contactsTotal = contactsData?.total ?? 0;

  const sendersQuery = useListAllSendersApiContactsSendersGet({
    search: debouncedSenderSearch || undefined,
  });
  const allSenders: SenderResponse[] =
    unwrapResponse<SenderResponse[]>(sendersQuery.data) ?? [];

  // --- Filtered contacts (server-side search) ---
  const filteredContacts = allContacts;

  // --- Lookup: find which contact already owns a sender email ---
  const contactForSender = useMemo(() => {
    if (!selectedSender) return null;
    const email = selectedSender.email_address.toLowerCase();
    return allContacts.find((c) =>
      c.emails.some((e) => e.toLowerCase() === email),
    ) ?? null;
  }, [selectedSender, allContacts]);

  // --- Mutations ---
  const assignMutation = useAssignEmailToContactApiContactsContactIdEmailsPost();
  const removeMutation = useRemoveEmailFromContactEndpointApiContactsContactIdEmailsDelete();

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["/api/contacts/senders"] });
    queryClient.invalidateQueries({ queryKey: ["/api/contacts"] });
  }, [queryClient]);

  // Assign: add email to contact
  const handleAssign = useCallback(
    (contactId: string, contactName: string, emailAddress: string) => {
      assignMutation.mutate(
        { contactId, data: { email_address: emailAddress } },
        {
          onSuccess: (res) => {
            const result = unwrapResponse<AssignEmailResponse>(res);
            const wb = result?.writeback_triggered ? " (CardDAV write-back)" : "";
            toast({
              title: "Email assigned",
              description: `${emailAddress} → ${contactName}${wb}`,
            });
            setSelectedContact(null);
            setSelectedSender(null);
            invalidateAll();
          },
          onError: () => {
            toast({
              title: "Assignment failed",
              description: "Could not assign the email to this contact.",
              variant: "destructive",
            });
          },
        },
      );
    },
    [assignMutation, toast, invalidateAll],
  );

  // Remove: remove email from contact
  const handleRemove = useCallback(
    (contactId: string, contactName: string, emailAddress: string) => {
      removeMutation.mutate(
        { contactId, data: { email_address: emailAddress } },
        {
          onSuccess: (res: unknown) => {
            const result = unwrapResponse<RemoveEmailResponse>(res);
            const wb = result?.writeback_triggered ? " (CardDAV write-back)" : "";
            toast({
              title: "Email removed",
              description: `${emailAddress} removed from ${contactName}${wb}`,
            });
            setSelectedContact(null);
            setSelectedSender(null);
            invalidateAll();
          },
          onError: () => {
            toast({
              title: "Removal failed",
              description: "Could not remove the email from this contact.",
              variant: "destructive",
            });
          },
        },
      );
    },
    [removeMutation, toast, invalidateAll],
  );

  // --- Click handlers ---

  // Click on contact in left column
  const handleContactClick = useCallback(
    (contact: ContactResponse) => {
      if (selectedSender) {
        // A sender is already selected → assign that sender to this contact
        handleAssign(contact.id, contact.display_name, selectedSender.email_address);
      } else if (selectedContact?.id === contact.id) {
        // Deselect
        setSelectedContact(null);
      } else {
        // Select this contact (deselect any sender)
        setSelectedContact(contact);
        setSelectedSender(null);
      }
    },
    [selectedContact, selectedSender, handleAssign],
  );

  // Click on a sender in right column
  const handleSenderClick = useCallback(
    (sender: SenderResponse) => {
      if (selectedContact) {
        // A contact is already selected
        const isAssigned = selectedContact.emails.some(
          (e) => e.toLowerCase() === sender.email_address.toLowerCase(),
        );
        if (isAssigned) {
          // Already assigned → remove it
          handleRemove(selectedContact.id, selectedContact.display_name, sender.email_address);
        } else {
          // Not assigned → assign it
          handleAssign(selectedContact.id, selectedContact.display_name, sender.email_address);
        }
      } else if (selectedSender?.email_address === sender.email_address) {
        // Deselect
        setSelectedSender(null);
      } else {
        // Select this sender (deselect any contact)
        setSelectedSender(sender);
        setSelectedContact(null);
      }
    },
    [selectedContact, selectedSender, handleAssign, handleRemove],
  );

  const isMutating = assignMutation.isPending || removeMutation.isPending;

  // --- Build the sender list: when a contact is selected, put its assigned emails at top ---
  const orderedSenders = useMemo(() => {
    if (!selectedContact) return allSenders;

    const assignedEmails = new Set(
      selectedContact.emails.map((e) => e.toLowerCase()),
    );

    // Partition: assigned first, then the rest
    const assigned: SenderResponse[] = [];
    const rest: SenderResponse[] = [];

    for (const sender of allSenders) {
      if (assignedEmails.has(sender.email_address.toLowerCase())) {
        assigned.push(sender);
      } else {
        rest.push(sender);
      }
    }

    return [...assigned, ...rest];
  }, [selectedContact, allSenders]);

  return (
    <>
    <Card>
      <CardHeader>
        <CardTitle>Match Emails and Contacts</CardTitle>
        <CardDescription>
          Select a contact or a sender to start matching. Assigned emails
          are written back to the CardDAV address book.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 md:grid-cols-2">
          <ContactListColumn
            contacts={filteredContacts}
            contactForSender={contactForSender}
            selectedContact={selectedContact}
            search={contactSearch}
            onSearchChange={setContactSearch}
            debouncedSearch={debouncedContactSearch}
            isLoading={contactsQuery.isLoading}
            isError={contactsQuery.isError}
            onRetry={() => contactsQuery.refetch()}
            isMutating={isMutating}
            onContactClick={handleContactClick}
            page={contactPage}
            totalPages={contactsTotalPages}
            totalItems={contactsTotal}
            onPageChange={setContactPage}
          />
          <SenderListColumn
            senders={orderedSenders}
            selectedContact={selectedContact}
            selectedSender={selectedSender}
            search={senderSearch}
            onSearchChange={setSenderSearch}
            debouncedSearch={debouncedSenderSearch}
            isLoading={sendersQuery.isLoading}
            isError={sendersQuery.isError}
            onRetry={() => sendersQuery.refetch()}
            isMutating={isMutating}
            onSenderClick={handleSenderClick}
            onCreateContact={setCreateContactEmail}
          />
        </div>
      </CardContent>
    </Card>

    {/* Dialog rendered at MappingsTab level so it survives sender deselection */}
    <CreateContactDialog
      senderEmail={createContactEmail}
      onClose={() => setCreateContactEmail(null)}
    />
    </>
  );
}
