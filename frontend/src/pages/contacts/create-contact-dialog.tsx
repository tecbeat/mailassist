import { useState, useEffect, useCallback } from "react";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import {
  X,
  Save,
  Sparkles,
  Loader2,
} from "lucide-react";

import {
  extractContactFromSenderApiContactsExtractFromSenderPost,
  createContactApiContactsPost,
  getListContactsApiContactsGetQueryKey,
} from "@/services/api/contacts/contacts";

import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { unwrapResponse } from "@/lib/utils";

import type { ContactFormData } from "./contacts-schemas";
import { contactFormSchema } from "./contacts-schemas";

// ---------------------------------------------------------------------------
// Create-contact dialog — rendered at MappingsTab level so it survives
// sender deselection.  The inline button only sets the email; the dialog
// lives independently.
// ---------------------------------------------------------------------------

export function CreateContactDialog({
  senderEmail,
  onClose,
}: {
  senderEmail: string | null;
  onClose: () => void;
}) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const open = senderEmail !== null;

  const defaultForm = useCallback(
    (): ContactFormData => ({
      display_name: "",
      first_name: "",
      last_name: "",
      emails: senderEmail ? [senderEmail] : [],
      phones: [],
      organization: "",
      title: "",
    }),
    [senderEmail],
  );

  const [form, setForm] = useState<ContactFormData>(defaultForm);
  const [touched, setTouched] = useState<Set<keyof ContactFormData>>(new Set());
  const [errors, setErrors] = useState<Partial<Record<keyof ContactFormData, string>>>({});

  // Reset form whenever the dialog opens for a (new) sender
  useEffect(() => {
    if (open) {
      setForm(defaultForm());
      setTouched(new Set());
      setErrors({});
      extractMutation.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, defaultForm]);

  const extractMutation = useMutation({
    mutationFn: () =>
      extractContactFromSenderApiContactsExtractFromSenderPost({ sender_email: senderEmail! }),
    onSuccess: (res) => {
      const data = unwrapResponse<ContactFormData>(res);
      if (!data) return;
      setForm((prev) => {
        const next = { ...prev };
        const fields: (keyof ContactFormData)[] = [
          "display_name", "first_name", "last_name", "emails", "phones", "organization", "title",
        ];
        for (const f of fields) {
          if (touched.has(f)) continue;
          const val = data[f];
          if (val == null) continue;
          if (Array.isArray(val)) {
            if (val.length > 0) (next as Record<string, unknown>)[f] = val;
          } else if (typeof val === "string" && val.trim()) {
            (next as Record<string, unknown>)[f] = val;
          }
        }
        return next;
      });
    },
    onError: () => {
      toast({ title: "Extraction failed", description: "Could not extract contact data from emails.", variant: "destructive" });
    },
  });

  const createMutation = useMutation({
    mutationFn: (payload: ContactFormData) =>
      createContactApiContactsPost(payload),
    onSuccess: () => {
      toast({ title: "Contact created", description: `Contact for ${senderEmail} has been created.` });
      onClose();
      queryClient.invalidateQueries({ queryKey: getListContactsApiContactsGetQueryKey() });
    },
    onError: () => {
      toast({ title: "Creation failed", description: "Could not create contact.", variant: "destructive" });
    },
  });

  function updateField(field: keyof ContactFormData, value: string) {
    setTouched((prev) => new Set(prev).add(field));
    if (field === "emails" || field === "phones") {
      setForm({ ...form, [field]: value.split(",").map((s) => s.trim()).filter(Boolean) });
    } else {
      setForm({ ...form, [field]: value });
    }
    setErrors((prev) => ({ ...prev, [field]: undefined }));
  }

  function handleSave() {
    const result = contactFormSchema.safeParse(form);
    if (!result.success) {
      const fieldErrors: Partial<Record<keyof ContactFormData, string>> = {};
      for (const issue of result.error.issues) {
        const key = issue.path[0] as keyof ContactFormData;
        if (!fieldErrors[key]) fieldErrors[key] = issue.message;
      }
      setErrors(fieldErrors);
      return;
    }
    createMutation.mutate(result.data);
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent
        className="max-h-[90vh] overflow-y-auto sm:max-w-lg"
        onPointerDownOutside={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Create Contact</DialogTitle>
          <DialogDescription>
            Create a new contact for {senderEmail}.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* AI fill hint */}
          {extractMutation.isIdle && (
            <button
              type="button"
              className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary"
              onClick={() => extractMutation.mutate()}
            >
              <Sparkles className="h-3 w-3" />
              Fill from emails with AI
            </button>
          )}
          {extractMutation.isPending && (
            <div className="flex items-center justify-center gap-1.5 py-1.5 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              Extracting contact data...
            </div>
          )}
          {extractMutation.isSuccess && (
            <p className="text-center text-xs text-green-600">
              AI data merged into empty fields.
            </p>
          )}
          {extractMutation.isError && (
            <p className="text-center text-xs text-destructive">
              AI extraction failed — fill in manually.
            </p>
          )}

          {/* Name row */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label className="text-xs">First Name</Label>
              <Input
                value={form.first_name}
                onChange={(e) => updateField("first_name", e.target.value)}
                placeholder="John"
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Last Name</Label>
              <Input
                value={form.last_name}
                onChange={(e) => updateField("last_name", e.target.value)}
                placeholder="Doe"
              />
            </div>
          </div>

          {/* Display name */}
          <div className="space-y-1.5">
            <Label className="text-xs">Display Name</Label>
              <Input
                value={form.display_name}
                onChange={(e) => updateField("display_name", e.target.value)}
                placeholder="John Doe"
              />
              {errors.display_name && <p className="text-xs text-destructive">{errors.display_name}</p>}
          </div>

          <Separator />

          {/* Organization + Title row */}
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label className="text-xs">Organization</Label>
              <Input
                value={form.organization}
                onChange={(e) => updateField("organization", e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Title</Label>
              <Input
                value={form.title}
                onChange={(e) => updateField("title", e.target.value)}
              />
            </div>
          </div>

          {/* Emails */}
          <div className="space-y-1.5">
            <Label className="text-xs">Emails</Label>
            <Input
              value={form.emails.join(", ")}
              onChange={(e) => updateField("emails", e.target.value)}
            />
            {errors.emails && <p className="text-xs text-destructive">{errors.emails}</p>}
            <p className="text-[10px] text-muted-foreground">Comma-separated</p>
          </div>

          {/* Phones */}
          <div className="space-y-1.5">
            <Label className="text-xs">Phones</Label>
            <Input
              value={form.phones.join(", ")}
              onChange={(e) => updateField("phones", e.target.value)}
            />
            <p className="text-[10px] text-muted-foreground">Comma-separated</p>
          </div>
        </div>

        <DialogFooter>
          <AppButton
            icon={<X />}
            label="Cancel"
            onClick={onClose}
          >
            Cancel
          </AppButton>
          <AppButton
            icon={<Save />}
            label="Save Contact"
            variant="primary"
            onClick={handleSave}
            loading={createMutation.isPending}
            disabled={createMutation.isPending}
          >
            Save Contact
          </AppButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
