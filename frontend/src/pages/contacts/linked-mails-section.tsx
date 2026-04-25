import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Mail, Trash2 } from "lucide-react";

import {
  useListContactMailsApiContactsContactIdMailsGet,
  getListContactMailsApiContactsContactIdMailsGetQueryKey,
  useUnlinkContactMailApiContactsContactIdMailsAssignmentIdDelete,
} from "@/services/api/contacts/contacts";
import type { ContactMailsResponse } from "@/types/api/contactMailsResponse";
import type { ContactAssignmentResponse } from "@/types/api/contactAssignmentResponse";

import { QueryError } from "@/components/query-error";
import { Pagination } from "@/components/pagination";
import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { unwrapResponse } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Linked Mails — shows AI-assigned mails for a selected contact
// ---------------------------------------------------------------------------

export function LinkedMailsSection({ contactId, contactName }: { contactId: string; contactName: string }) {
  const [page, setPage] = useState(1);
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const mailsQuery = useListContactMailsApiContactsContactIdMailsGet(contactId, { page, per_page: 10 });
  const data = unwrapResponse<ContactMailsResponse>(mailsQuery.data as never);
  const mails = data?.items ?? [];
  const totalPages = data?.pages ?? 1;
  const totalCount = data?.total ?? 0;

  const unlinkMutation = useUnlinkContactMailApiContactsContactIdMailsAssignmentIdDelete({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({
          queryKey: getListContactMailsApiContactsContactIdMailsGetQueryKey(contactId, { page, per_page: 10 }),
        });
        toast({ title: "Mail unlinked", description: "The mail has been removed from this contact." });
      },
      onError: () => {
        toast({ title: "Failed to unlink mail", description: "Could not remove the mail from this contact. Please try again.", variant: "destructive" });
      },
    },
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          AI-Linked Mails for {contactName}
        </CardTitle>
        <CardDescription>
          Emails assigned to this contact by the AI pipeline.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {mailsQuery.isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full rounded-md" />
            ))}
          </div>
        ) : mailsQuery.isError ? (
          <QueryError
            message="Failed to load linked mails."
            onRetry={() => mailsQuery.refetch()}
          />
        ) : mails.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No AI-assigned mails yet for this contact.
          </p>
        ) : (
          <div className="space-y-3">
            <div className="space-y-1">
              {mails.map((mail: ContactAssignmentResponse) => (
                <div
                  key={mail.id}
                  className="flex items-center gap-3 rounded-md border px-3 py-2 text-sm"
                >
                  <Mail className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{mail.mail_subject || "(no subject)"}</p>
                    <p className="truncate text-xs text-muted-foreground">{mail.mail_from}</p>
                  </div>
                  <Badge variant="secondary" className="shrink-0">
                    {Math.round(mail.confidence * 100)}%
                  </Badge>
                  <AppButton
                    icon={<Trash2 />}
                    label="Unlink"
                    variant="ghost"
                    color="destructive"
                   
                    className="h-7 w-7 shrink-0"
                    loading={unlinkMutation.isPending && unlinkMutation.variables?.assignmentId === mail.id}
                    disabled={unlinkMutation.isPending}
                    onClick={() => unlinkMutation.mutate({ contactId, assignmentId: mail.id })}
                  />
                </div>
              ))}
            </div>
            <Pagination
              page={page}
              totalPages={totalPages}
              totalCount={totalCount}
              onPageChange={setPage}
              noun="mails"
              compact
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
