import { z } from "zod/v4";

// ---------------------------------------------------------------------------
// Zod schemas
// ---------------------------------------------------------------------------

export const mailAccountBaseSchema = z.object({
  name: z.string().min(1, "Name is required").max(100),
  email_address: z.string().email("Invalid email address").max(320),
  imap_host: z.string().min(1, "IMAP host is required").max(255),
  imap_port: z.number().int().min(1).max(65535),
  imap_use_ssl: z.boolean(),
  username: z.string().max(255),
  password: z.string().max(500),
  scan_existing_emails: z.boolean(),
  excluded_folders: z.string().optional(),
});

export type MailAccountFormValues = z.infer<typeof mailAccountBaseSchema>;

export const mailSettingsSchema = z.object({
  default_polling_interval_minutes: z.number().int().min(1).max(1440),
  draft_expiry_hours: z.number().int().min(1).max(8760),
});

export type MailSettingsFormValues = z.infer<typeof mailSettingsSchema>;

export const defaultFormValues: MailAccountFormValues = {
  name: "",
  email_address: "",
  imap_host: "",
  imap_port: 993,
  imap_use_ssl: true,
  username: "",
  password: "",
  scan_existing_emails: false,
  excluded_folders: "",
};
