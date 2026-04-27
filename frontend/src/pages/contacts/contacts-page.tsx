import { useState, useEffect, useCallback } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  RefreshCw,
  Save,
  FlaskConical,
} from "lucide-react";

import {
  useTriggerSyncApiContactsSyncPost,
  useGetConfigApiContactsConfigGet,
  useUpsertConfigApiContactsConfigPut,
  useTestConfigApiContactsConfigTestPost,
} from "@/services/api/contacts/contacts";
import type { CardDAVConfigResponse } from "@/types/api";
import type { ContactResponse } from "@/types/api";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import {
  PluginSettingsDialog,
  PluginSettingsButton,
} from "@/components/plugin-settings-dialog";
import { AppButton } from "@/components/app-button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import { useToast } from "@/components/ui/toast";
import { unwrapResponse } from "@/lib/utils";

import { carddavConfigSchema, type CardDAVConfigFormValues } from "./contacts-schemas";
import { MappingsTab } from "./mappings-tab";
import { LinkedMailsSection } from "./linked-mails-section";

// ---------------------------------------------------------------------------
// Contacts Page (Main)
// ---------------------------------------------------------------------------

export default function ContactsPage() {
  usePageTitle("Contacts");
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [activeContact, setActiveContact] = useState<ContactResponse | null>(null);

  const handleContactSelect = useCallback((contact: ContactResponse | null) => {
    setActiveContact(contact);
  }, []);

  // -------------------------------------------------------------------------
  // Sync
  // -------------------------------------------------------------------------

  const syncMutation = useTriggerSyncApiContactsSyncPost();

  const handleSync = useCallback(() => {
    syncMutation.mutate(undefined, {
      onSuccess: (res) => {
        const result = unwrapResponse<{
          added: number;
          updated: number;
          deleted: number;
          errors: number;
        }>(res);
        toast({
          title: "Sync complete",
          description: result
            ? `Added: ${result.added}, Updated: ${result.updated}, Deleted: ${result.deleted}${
                result.errors ? `, Errors: ${result.errors}` : ""
              }`
            : "Contacts have been synced.",
        });
        queryClient.invalidateQueries({ queryKey: ["/api/contacts"] });
        queryClient.invalidateQueries({ queryKey: ["/api/contacts/config"] });
      },
      onError: () => {
        toast({
          title: "Sync failed",
          description:
            "Could not sync contacts. Check your CardDAV configuration.",
          variant: "destructive",
        });
      },
    });
  }, [syncMutation.mutate, queryClient, toast]);

  // -------------------------------------------------------------------------
  // CardDAV config form (rendered inside PluginSettingsDialog)
  // -------------------------------------------------------------------------

  const configQuery = useGetConfigApiContactsConfigGet();
  const configData = unwrapResponse<CardDAVConfigResponse | null>(configQuery.data);

  const form = useForm<CardDAVConfigFormValues>({
    resolver: zodResolver(carddavConfigSchema),
    defaultValues: {
      carddav_url: "",
      address_book: "",
      username: "",
      password: "",
      sync_interval: 60,
    },
  });

  useEffect(() => {
    if (configData) {
      form.reset({
        carddav_url: configData.carddav_url,
        address_book: configData.address_book,
        username: "",
        password: "",
        sync_interval: configData.sync_interval,
      });
    }
  }, [configData, form]);

  const upsertMutation = useUpsertConfigApiContactsConfigPut();
  const testMutation = useTestConfigApiContactsConfigTestPost();

  const handleSave = useCallback(
    (values: CardDAVConfigFormValues) => {
      upsertMutation.mutate(
        { data: values },
        {
          onSuccess: () => {
            toast({
              title: "Configuration saved",
              description: "CardDAV settings have been updated. Syncing contacts...",
            });
            setSettingsOpen(false);
            queryClient.invalidateQueries({
              queryKey: ["/api/contacts/config"],
            });
            // Automatically trigger a contact sync after saving
            handleSync();
          },
          onError: () => {
            toast({
              title: "Save failed",
              description: "Could not save CardDAV configuration.",
              variant: "destructive",
            });
          },
        },
      );
    },
    [upsertMutation, queryClient, toast, form, handleSync],
  );

  const handleTest = useCallback(() => {
    const values = form.getValues();
    if (!values.carddav_url || !values.username || !values.password) {
      toast({
        title: "Validation error",
        description: "URL, username, and password are required for testing.",
        variant: "destructive",
      });
      return;
    }

    testMutation.mutate(
      {
        data: {
          carddav_url: values.carddav_url,
          username: values.username,
          password: values.password,
          address_book: values.address_book || "",
        },
      },
      {
        onSuccess: (res) => {
          const result = unwrapResponse<{ success: boolean; message: string; details?: Record<string, unknown> | null }>(res);
          if (result?.success) {
            const details = result.details ?? {};
            const addressBooks = (details.address_books as string[]) ?? [];
            const addressBookNames = (details.address_book_names as string[]) ?? [];

            // Auto-fill discovered URL if different from current
            const discoveredUrl = details.carddav_url as string | undefined;
            if (discoveredUrl && discoveredUrl !== values.carddav_url) {
              form.setValue("carddav_url", discoveredUrl);
            }

            // Auto-fill first address book if field is empty
            if (!values.address_book && addressBooks.length > 0) {
              form.setValue("address_book", addressBooks[0] ?? "");
            }

            const bookList = addressBookNames.length > 0
              ? addressBookNames.map((name, i) => `${name} (${addressBooks[i] ?? name})`).join(", ")
              : "";
            const description = bookList
              ? `${result.message || "CardDAV server is reachable."}\n\nAddress books: ${bookList}`
              : result.message || "CardDAV server is reachable.";
            toast({
              title: "Connection successful",
              description,
            });
          } else {
            const details = result?.details ?? {};
            const addressBookNames = (details.address_book_names as string[]) ?? [];
            const description = addressBookNames.length > 0
              ? `${result?.message || "Could not connect to CardDAV server."}\n\nAvailable: ${addressBookNames.join(", ")}`
              : result?.message || "Could not connect to CardDAV server.";
            toast({
              title: "Connection failed",
              description,
              variant: "destructive",
            });
          }
        },
        onError: () => {
          toast({
            title: "Test failed",
            description: "An error occurred while testing the connection.",
            variant: "destructive",
          });
        },
      },
    );
  }, [form, testMutation, toast]);

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      <PageHeader
        title="Contacts"
        description="Browse synced contacts and match email senders."
        actions={
          <div className="flex items-center gap-2">
            <PluginSettingsButton onClick={() => setSettingsOpen(true)} />
            <AppButton
              icon={<RefreshCw />}
              label="Sync Now"
              variant="primary"
              loading={syncMutation.isPending}
              onClick={handleSync}
              disabled={syncMutation.isPending || !configData?.is_active}
              title={!configData?.is_active ? "Configure CardDAV first" : undefined}
            >
              Sync Now
            </AppButton>
          </div>
        }
      />

      {/* Email-to-Contact Matching */}
      <MappingsTab onContactSelect={handleContactSelect} />

      {/* AI-Linked Mails for selected contact */}
      {activeContact && (
        <LinkedMailsSection
          contactId={activeContact.id}
          contactName={activeContact.display_name}
        />
      )}

      {/* CardDAV Settings Dialog */}
      <PluginSettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        title="CardDAV Configuration"
        description="Connect to your CardDAV server to sync contacts automatically."
      >
        {configQuery.isError ? (
          <QueryError
            message="Failed to load CardDAV configuration."
            onRetry={() => configQuery.refetch()}
          />
        ) : configQuery.isLoading ? (
          <div className="space-y-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="space-y-2">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-9 w-full" />
              </div>
            ))}
          </div>
        ) : (
          <div className="space-y-4">
            {/* Form fields */}
            <form onSubmit={form.handleSubmit(handleSave)} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="carddav-url">CardDAV URL</Label>
                <Input
                  id="carddav-url"
                  type="url"
                  placeholder="https://nextcloud.example.com"
                  {...form.register("carddav_url")}
                />
                {form.formState.errors.carddav_url ? (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.carddav_url.message}
                  </p>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Just the server URL is enough — the full DAV path is auto-detected.
                  </p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="address-book">Address Book</Label>
                <Input
                  id="address-book"
                  placeholder="contacts"
                  {...form.register("address_book")}
                />
                <p className="text-xs text-muted-foreground">
                  Auto-filled by &quot;Test Connection&quot;. Leave empty to discover available books.
                </p>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="carddav-username">Username</Label>
                  <Input
                    id="carddav-username"
                    placeholder="user@example.com"
                    {...form.register("username")}
                    autoComplete="username"
                  />
                  {form.formState.errors.username && (
                    <p className="text-xs text-destructive">
                      {form.formState.errors.username.message}
                    </p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="carddav-password">Password</Label>
                  <Input
                    id="carddav-password"
                    type="password"
                    placeholder={configData ? "Enter new password to update" : "Password"}
                    {...form.register("password")}
                    autoComplete="new-password"
                  />
                  {form.formState.errors.password ? (
                    <p className="text-xs text-destructive">
                      {form.formState.errors.password.message}
                    </p>
                  ) : configData ? (
                    <p className="text-xs text-muted-foreground">
                      Leave blank to keep existing password.
                    </p>
                  ) : null}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="sync-interval">Sync Interval (minutes)</Label>
                <Input
                  id="sync-interval"
                  type="number"
                  min={5}
                  max={1440}
                  className="w-32"
                  {...form.register("sync_interval", { valueAsNumber: true })}
                />
                {form.formState.errors.sync_interval && (
                  <p className="text-xs text-destructive">
                    {form.formState.errors.sync_interval.message}
                  </p>
                )}
              </div>

              <Separator />

              <div className="flex flex-wrap gap-2">
                <AppButton
                  type="submit"
                  icon={<Save />}
                  label="Save Configuration"
                  variant="primary"
                  loading={upsertMutation.isPending}
                  disabled={upsertMutation.isPending}
                >
                  Save Configuration
                </AppButton>
                <AppButton
                  type="button"
                  icon={<FlaskConical />}
                  label="Test Connection"
                  loading={testMutation.isPending}
                  onClick={handleTest}
                  disabled={testMutation.isPending}
                >
                  Test Connection
                </AppButton>
              </div>
            </form>
          </div>
        )}
      </PluginSettingsDialog>
    </div>
  );
}
