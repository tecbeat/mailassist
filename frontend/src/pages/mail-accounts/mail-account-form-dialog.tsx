import { UseFormReturn } from "react-hook-form";
import { X, Save } from "lucide-react";

import type { MailAccountResponse } from "@/types/api";

import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { MailAccountFormValues } from "./mail-account-schemas";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface MailAccountFormDialogProps {
  open: boolean;
  onClose: () => void;
  form: UseFormReturn<MailAccountFormValues>;
  editingAccount: MailAccountResponse | null;
  onSubmit: (values: MailAccountFormValues) => void;
  isMutating: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MailAccountFormDialog({
  open,
  onClose,
  form,
  editingAccount,
  onSubmit,
  isMutating,
}: MailAccountFormDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editingAccount ? "Edit Mail Account" : "Add Mail Account"}
          </DialogTitle>
          <DialogDescription>
            {editingAccount
              ? "Update the account settings. Leave credentials empty to keep existing ones."
              : "Enter the details for your email account."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              placeholder="e.g. Work, Personal"
              {...form.register("name")}
            />
            {form.formState.errors.name && (
              <p className="text-xs text-destructive">
                {form.formState.errors.name.message}
              </p>
            )}
          </div>

          {/* Email */}
          <div className="space-y-2">
            <Label htmlFor="email_address">Email Address</Label>
            <Input
              id="email_address"
              type="email"
              placeholder="user@example.com"
              {...form.register("email_address")}
            />
            {form.formState.errors.email_address && (
              <p className="text-xs text-destructive">
                {form.formState.errors.email_address.message}
              </p>
            )}
          </div>

          <Separator />

          {/* IMAP Settings */}
          <div className="space-y-3">
            <h4 className="text-sm font-medium">IMAP Settings</h4>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2 space-y-2">
                <Label htmlFor="imap_host">Host</Label>
                <Input
                  id="imap_host"
                  placeholder="imap.example.com"
                  {...form.register("imap_host")}
                />
                {form.formState.errors.imap_host && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.imap_host.message}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                <Label htmlFor="imap_port">Port</Label>
                <Input
                  id="imap_port"
                  type="number"
                  {...form.register("imap_port", { valueAsNumber: true })}
                />
                {form.formState.errors.imap_port && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.imap_port.message}
                  </p>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="imap_use_ssl"
                checked={form.watch("imap_use_ssl")}
                onCheckedChange={(checked) =>
                  form.setValue("imap_use_ssl", checked)
                }
              />
              <Label htmlFor="imap_use_ssl">Use SSL/TLS</Label>
            </div>
          </div>

          <Separator />

          {/* Credentials */}
          <div className="space-y-3">
            <h4 className="text-sm font-medium">Credentials</h4>
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                placeholder={
                  editingAccount
                    ? "Leave empty to keep existing"
                    : "IMAP username"
                }
                {...form.register("username")}
              />
              {form.formState.errors.username && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.username.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder={
                  editingAccount
                    ? "Leave empty to keep existing"
                    : "IMAP password"
                }
                {...form.register("password")}
              />
              {form.formState.errors.password && (
                <p className="text-xs text-destructive">
                  {form.formState.errors.password.message}
                </p>
              )}
            </div>
          </div>

          <Separator />

          {/* Scan Existing Emails -- only shown during account creation */}
          {!editingAccount && (
            <>
              <div className="flex items-center space-x-2">
                <Switch
                  id="scan_existing_emails"
                  checked={form.watch("scan_existing_emails")}
                  onCheckedChange={(checked) =>
                    form.setValue("scan_existing_emails", checked)
                  }
                />
                <Label htmlFor="scan_existing_emails">
                  Scan existing emails
                </Label>
              </div>
              <p className="text-[10px] text-muted-foreground">
                If enabled, all existing emails from all folders will be indexed
                on first sync. Otherwise only new incoming mail is processed.
              </p>

              <Separator />
            </>
          )}

          {/* Excluded Folders */}
          <div className="space-y-2">
            <Label htmlFor="excluded_folders">
              Excluded Folders{" "}
              <span className="text-xs text-muted-foreground">(optional)</span>
            </Label>
            <Input
              id="excluded_folders"
              placeholder="e.g. Trash, Spam, Drafts"
              {...form.register("excluded_folders")}
            />
            <p className="text-[10px] text-muted-foreground">
              Comma-separated list of IMAP folders to skip during analysis.
            </p>
          </div>

          <DialogFooter>
            <AppButton
              icon={<X />}
              label="Cancel"
              type="button"
              onClick={onClose}
              disabled={isMutating}
            >
              Cancel
            </AppButton>
            <AppButton
              icon={<Save />}
              label={editingAccount ? "Save Changes" : "Create Account"}
              type="submit"
              variant="primary"
              loading={isMutating}
            >
              {editingAccount ? "Save Changes" : "Create Account"}
            </AppButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
