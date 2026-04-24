import { ShieldBan } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import { AppButton } from "@/components/app-button";
import { useToast } from "@/components/ui/toast";
import {
  useCreateBlocklistEntryApiSpamBlocklistPost,
  useReportContactSpamApiSpamReportContactPost,
  useReportSpamApiSpamReportPost,
} from "@/services/api/spam/spam";

interface SpamButtonMailProps {
  /** IMAP UID of the mail to report. */
  mailId: string;
  /** Mail account ID the message belongs to. */
  mailAccountId: string;
  /** Sender email address. */
  senderEmail: string;
  /** Email subject (optional, for pattern extraction). */
  subject?: string | null;
  /** Called after successful spam report. */
  onSuccess?: () => void;
}

interface SpamButtonContactProps {
  /** Contact ID to block. */
  contactId: string;
  /** Contact display name (shown in confirmation). */
  contactName?: string;
  /** Called after successful spam report. */
  onSuccess?: () => void;
}

interface SpamButtonEmailProps {
  /** Email address to add to the blocklist. */
  emailAddress: string;
  /** Called after successful blocklist entry creation. */
  onSuccess?: () => void;
}

type SpamButtonProps =
  | ({ variant: "mail" } & SpamButtonMailProps)
  | ({ variant: "contact" } & SpamButtonContactProps)
  | ({ variant: "email" } & SpamButtonEmailProps);

export function SpamButton(props: SpamButtonProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { toast } = useToast();

  const reportMail = useReportSpamApiSpamReportPost();
  const reportContact = useReportContactSpamApiSpamReportContactPost();
  const createBlocklist = useCreateBlocklistEntryApiSpamBlocklistPost();

  const isPending =
    reportMail.isPending || reportContact.isPending || createBlocklist.isPending;

  // Keep a stable ref to props so handleConfirm doesn't depend on the
  // props object identity (which changes every render).
  const propsRef = useRef(props);
  propsRef.current = props;

  const handleConfirm = useCallback(() => {
    const p = propsRef.current;
    if (p.variant === "mail") {
      reportMail.mutate(
        {
          data: {
            mail_id: p.mailId,
            mail_account_id: p.mailAccountId,
            sender_email: p.senderEmail,
            subject: p.subject,
          },
        },
        {
          onSuccess: (res) => {
            const msg =
              res.status === 200 ? res.data.message : "Sender reported as spam.";
            toast({ title: "Marked as spam", description: msg });
            setConfirmOpen(false);
            p.onSuccess?.();
          },
          onError: () => {
            toast({
              title: "Failed to report spam",
              description: "An unexpected error occurred.",
              variant: "destructive",
            });
          },
        },
      );
    } else if (p.variant === "contact") {
      reportContact.mutate(
        { data: { contact_id: p.contactId } },
        {
          onSuccess: (res) => {
            const msg =
              res.status === 200 ? res.data.message : "Contact has been blocked.";
            toast({ title: "Contact blocked", description: msg });
            setConfirmOpen(false);
            p.onSuccess?.();
          },
          onError: () => {
            toast({
              title: "Failed to block contact",
              description: "An unexpected error occurred.",
              variant: "destructive",
            });
          },
        },
      );
    } else {
      createBlocklist.mutate(
        { data: { entry_type: "email", value: p.emailAddress } },
        {
          onSuccess: () => {
            toast({
              title: "Email blocked",
              description: `"${p.emailAddress}" added to blocklist.`,
            });
            setConfirmOpen(false);
            p.onSuccess?.();
          },
          onError: () => {
            toast({
              title: "Failed to block email",
              description: "An unexpected error occurred.",
              variant: "destructive",
            });
          },
        },
      );
    }
  }, [reportMail, reportContact, createBlocklist, toast]);

  const description =
    props.variant === "mail" ? (
      <>
        Mark sender{" "}
        <span className="font-medium">{props.senderEmail}</span> as spam?
        The email will be moved to the spam folder and the sender will be
        added to the blocklist.
      </>
    ) : props.variant === "contact" ? (
      <>
        Block contact{" "}
        <span className="font-medium">
          {props.contactName ?? "this contact"}
        </span>
        ? All their email addresses will be added to the blocklist and the
        contact will be deleted.
      </>
    ) : (
      <>
        Block{" "}
        <span className="font-medium">{props.emailAddress}</span>?
        This email address will be added to the blocklist.
      </>
    );

  return (
    <>
      <AppButton
        icon={<ShieldBan />}
        label="Mark as Spam"
        variant="ghost"
        color="destructive"
        onClick={(e) => {
          e.stopPropagation();
          setConfirmOpen(true);
        }}
      />

      <DeleteConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={
          props.variant === "mail"
            ? "Report as Spam"
            : props.variant === "contact"
              ? "Block Contact"
              : "Block Email"
        }
        description={description}
        onConfirm={handleConfirm}
        isPending={isPending}
      />
    </>
  );
}
