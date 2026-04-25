import { z } from "zod/v4";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const DEBOUNCE_MS = 400;

// ---------------------------------------------------------------------------
// CardDAV config schema
// ---------------------------------------------------------------------------

export const carddavConfigSchema = z.object({
  carddav_url: z
    .string()
    .min(1, "URL is required")
    .url("Must be a valid URL")
    .refine((v) => v.startsWith("https://"), "Must use HTTPS"),
  address_book: z.string(),
  username: z.string(),
  password: z.string(),
  sync_interval: z.number().int().min(5).max(1440),
});

export type CardDAVConfigFormValues = z.infer<typeof carddavConfigSchema>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function getInitials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

// ---------------------------------------------------------------------------
// Create Contact form data type
// ---------------------------------------------------------------------------

export const contactFormSchema = z.object({
  display_name: z.string().min(1, "Display name is required"),
  first_name: z.string(),
  last_name: z.string(),
  emails: z.array(z.string().email("Invalid email address")).min(1, "At least one email is required"),
  phones: z.array(z.string()),
  organization: z.string(),
  title: z.string(),
});

export type ContactFormData = z.infer<typeof contactFormSchema>;
