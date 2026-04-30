import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, Mail, Settings2 } from "lucide-react";
import { usePageTitle } from "@/hooks/use-page-title";

import {
  useListMailAccountsApiMailAccountsGet,
  useCreateMailAccountApiMailAccountsPost,
  useUpdateMailAccountApiMailAccountsAccountIdPut,
  useDeleteMailAccountApiMailAccountsAccountIdDelete,
  useTestConnectionApiMailAccountsAccountIdTestPost,
  usePollAccountNowApiMailAccountsAccountIdPollPost,
  useUpdatePauseStateApiMailAccountsAccountIdPausePatch,
  useResetAccountHealthApiMailAccountsAccountIdResetHealthPost,
  getListMailAccountsApiMailAccountsGetQueryKey,
} from "@/services/api/mail-accounts/mail-accounts";
import {
  useGetSettingsApiSettingsGet,
  useUpdateSettingsApiSettingsPut,
  getGetSettingsApiSettingsGetQueryKey,
} from "@/services/api/settings/settings";
import type {
  MailAccountResponse,
  MailAccountUpdate,
  ConnectionTestResult,
  JobEnqueuedResponse,
  SettingsResponse,
} from "@/types/api";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import { InlineSettingsRow } from "@/components/inline-settings-row";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import { AppButton } from "@/components/app-button";
import { useToast } from "@/components/ui/toast";
import { unwrapResponse } from "@/lib/utils";
import { useAccountOperations } from "@/hooks/use-account-operations";

import {
  mailAccountBaseSchema,
  mailSettingsSchema,
  defaultFormValues,
  type MailAccountFormValues,
  type MailSettingsFormValues,
} from "./mail-account-schemas";
import { MailAccountRow } from "./mail-account-row";
import { MailAccountFormDialog } from "./mail-account-form-dialog";

// ---------------------------------------------------------------------------
// Mail Accounts Page
// ---------------------------------------------------------------------------

export default function MailAccountsPage() {
  usePageTitle("Mail Accounts");
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Dialog state
  const [formOpen, setFormOpen] = useState(false);
  const [editingAccount, setEditingAccount] =
    useState<MailAccountResponse | null>(null);
  const [deleteTarget, setDeleteTarget] =
    useState<MailAccountResponse | null>(null);

  // Data fetching
  const accountsQuery = useListMailAccountsApiMailAccountsGet();
  const accounts = unwrapResponse<MailAccountResponse[]>(accountsQuery.data);

  // Mutations
  const createMutation = useCreateMailAccountApiMailAccountsPost({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({
          queryKey: getListMailAccountsApiMailAccountsGetQueryKey(),
        });
        toast({ title: "Account created", description: "Mail account has been added successfully." });
        closeForm();
      },
      onError: () => {
        toast({
          title: "Failed to create account",
          description: "Please check the form and try again.",
          variant: "destructive",
        });
      },
    },
  });

  const updateMutation = useUpdateMailAccountApiMailAccountsAccountIdPut({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({
          queryKey: getListMailAccountsApiMailAccountsGetQueryKey(),
        });
        toast({ title: "Account updated", description: "Mail account has been updated successfully." });
        closeForm();
      },
      onError: () => {
        toast({
          title: "Failed to update account",
          description: "Please check the form and try again.",
          variant: "destructive",
        });
      },
    },
  });

  const deleteMutation = useDeleteMailAccountApiMailAccountsAccountIdDelete({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({
          queryKey: getListMailAccountsApiMailAccountsGetQueryKey(),
        });
        toast({ title: "Account deleted", description: "Mail account has been removed." });
        setDeleteTarget(null);
      },
      onError: () => {
        toast({
          title: "Failed to delete account",
          description: "An error occurred while deleting the account.",
          variant: "destructive",
        });
      },
    },
  });

  // Persistent operation tracking (survives component unmounts / tab switches)
  const accountOps = useAccountOperations();

  useEffect(() => {
    accountOps.setCallbacks({
      onPollComplete: () => {
        queryClient.invalidateQueries({ queryKey: getListMailAccountsApiMailAccountsGetQueryKey() });
        toast({ title: "Poll complete", description: "Mailbox check finished successfully." });
      },
      onPollFailed: (_accountId, error) => {
        queryClient.invalidateQueries({ queryKey: getListMailAccountsApiMailAccountsGetQueryKey() });
        toast({
          title: "Poll failed",
          description: error || "The background poll job failed.",
          variant: "destructive",
        });
      },
    });
  }, [accountOps, queryClient, toast]);

  const testMutation = useTestConnectionApiMailAccountsAccountIdTestPost({
    mutation: {
      onMutate: (variables) => {
        accountOps.startTest(variables.accountId);
      },
      onSuccess: (response, variables) => {
        accountOps.completeTest(variables.accountId);
        const result = unwrapResponse<ConnectionTestResult>(response);
        if (result) {
          const imapOk = result.imap_success;
          const emailInfo = result.email_count != null
            ? ` | Emails in INBOX: ${result.email_count.toLocaleString()}`
            : "";
          toast({
            title: imapOk ? "Connection successful" : "Connection issues",
            description: `IMAP: ${result.imap_message}${emailInfo}`,
            variant: imapOk ? "default" : "destructive",
          });
        }
      },
      onError: (_error, variables) => {
        accountOps.failTest(variables.accountId);
        toast({
          title: "Connection test failed",
          description: "Could not reach the server.",
          variant: "destructive",
        });
      },
    },
  });

  const pollMutation = usePollAccountNowApiMailAccountsAccountIdPollPost({
    mutation: {
      onMutate: (variables) => {
        accountOps.startPollPending(variables.accountId);
      },
      onSuccess: (response, variables) => {
        const result = unwrapResponse<JobEnqueuedResponse>(response);
        if (result?.job_id) {
          accountOps.completePollWithJob(variables.accountId, result.job_id);
        } else {
          accountOps.failPoll(variables.accountId);
        }
      },
      onError: (_error, variables) => {
        accountOps.failPoll(variables.accountId);
        toast({ title: "Poll failed", description: "Could not start polling for new messages.", variant: "destructive" });
      },
    },
  });

  const unpauseMutation = useUpdatePauseStateApiMailAccountsAccountIdPausePatch({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListMailAccountsApiMailAccountsGetQueryKey() });
        toast({ title: "Account unpaused", description: "Mail account has been resumed." });
      },
      onError: () => {
        toast({ title: "Unpause failed", description: "Could not unpause the account.", variant: "destructive" });
      },
    },
  });

  const pauseMutation = useUpdatePauseStateApiMailAccountsAccountIdPausePatch({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListMailAccountsApiMailAccountsGetQueryKey() });
        toast({ title: "Account paused", description: "Mail account has been paused." });
      },
      onError: () => {
        toast({ title: "Pause failed", description: "Could not pause the account.", variant: "destructive" });
      },
    },
  });

  const resetHealthMutation = useResetAccountHealthApiMailAccountsAccountIdResetHealthPost({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListMailAccountsApiMailAccountsGetQueryKey() });
        toast({ title: "Health reset", description: "Account errors cleared and re-activated." });
      },
      onError: () => {
        toast({ title: "Reset failed", description: "Could not reset account health.", variant: "destructive" });
      },
    },
  });

  // Form setup
  const form = useForm<MailAccountFormValues>({
    resolver: zodResolver(mailAccountBaseSchema),
    defaultValues: defaultFormValues,
  });

  function openCreateForm() {
    setEditingAccount(null);
    form.reset({ ...defaultFormValues });
    setFormOpen(true);
  }

  function openEditForm(account: MailAccountResponse) {
    setEditingAccount(account);
    form.reset({
      name: account.name,
      email_address: account.email_address,
      imap_host: account.imap_host,
      imap_port: account.imap_port,
      imap_use_ssl: account.imap_use_ssl,
      username: "",
      password: "",
      scan_existing_emails: account.scan_existing_emails ?? false,
      excluded_folders: account.excluded_folders?.join(", ") ?? "",
    });
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
    setEditingAccount(null);
    form.reset(defaultFormValues);
  }

  function onSubmit(values: MailAccountFormValues) {
    const parsedFolders = values.excluded_folders
      ? values.excluded_folders.split(",").map((f) => f.trim()).filter(Boolean)
      : [];
    const excludedFolders = parsedFolders.length > 0 ? parsedFolders : null;

    if (editingAccount) {
      const updateData: MailAccountUpdate = {
        name: values.name,
        email_address: values.email_address,
        imap_host: values.imap_host,
        imap_port: values.imap_port,
        imap_use_ssl: values.imap_use_ssl,
        excluded_folders: excludedFolders,
      };
      if (values.username) updateData.username = values.username;
      if (values.password) updateData.password = values.password;
      updateMutation.mutate({ accountId: editingAccount.id, data: updateData });
    } else {
      if (!values.username) {
        form.setError("username", { message: "Username is required" });
        return;
      }
      if (!values.password) {
        form.setError("password", { message: "Password is required" });
        return;
      }
      createMutation.mutate({
        data: { ...(values as MailAccountFormValues), excluded_folders: excludedFolders },
      });
    }
  }

  const isMutating = createMutation.isPending || updateMutation.isPending;

  // ---------------------------------------------------------------------------
  // Polling & Draft settings
  // ---------------------------------------------------------------------------

  const settingsQuery = useGetSettingsApiSettingsGet();
  const globalSettings = unwrapResponse<SettingsResponse>(settingsQuery.data);

  const updateSettingsMutation = useUpdateSettingsApiSettingsPut();

  const settingsForm = useForm<MailSettingsFormValues>({
    resolver: zodResolver(mailSettingsSchema),
    defaultValues: { default_polling_interval_minutes: 5, draft_expiry_hours: 168 },
  });

  useEffect(() => {
    if (globalSettings) {
      settingsForm.reset({
        default_polling_interval_minutes: globalSettings.default_polling_interval_minutes ?? 5,
        draft_expiry_hours: globalSettings.draft_expiry_hours ?? 168,
      });
    }
  }, [globalSettings, settingsForm]);

  async function saveMailSettings(values: MailSettingsFormValues) {
    try {
      await updateSettingsMutation.mutateAsync({ data: values });
      queryClient.invalidateQueries({ queryKey: getGetSettingsApiSettingsGetQueryKey() });
      settingsForm.reset(values);
      toast({ title: "Settings saved", description: "Mail account settings have been updated." });
    } catch {
      toast({ title: "Failed to save settings", description: "Could not save the mail settings. Please try again.", variant: "destructive" });
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const settingsRowElement = (
    <InlineSettingsRow
      icon={<Settings2 />}
      title="Mail Processing Settings"
      onSave={settingsForm.handleSubmit(saveMailSettings)}
      saving={updateSettingsMutation.isPending}
      saveDisabled={!settingsForm.formState.isDirty}
      fields={[
        {
          key: "polling_interval",
          label: "Poll Interval (minutes)",
          input: (
            <Input
              type="number"
              min={1}
              max={1440}
              className="w-28 h-8 text-sm"
              {...settingsForm.register("default_polling_interval_minutes", { valueAsNumber: true })}
            />
          ),
          error: settingsForm.formState.errors.default_polling_interval_minutes?.message,
        },
        {
          key: "draft_expiry",
          label: "Draft Expiry (hours)",
          input: (
            <Input
              type="number"
              min={1}
              max={8760}
              className="w-28 h-8 text-sm"
              {...settingsForm.register("draft_expiry_hours", { valueAsNumber: true })}
            />
          ),
          error: settingsForm.formState.errors.draft_expiry_hours?.message,
          hint: "Auto-reply drafts older than this are cleaned up.",
        },
      ]}
    />
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Mail Accounts"
        description="Manage your connected email accounts."
        actions={
          <AppButton icon={<Plus />} label="Add Account" variant="primary" onClick={openCreateForm}>
            Add Account
          </AppButton>
        }
      />

      {accountsQuery.isError ? (
        <QueryError message="Failed to load mail accounts." onRetry={() => accountsQuery.refetch()} />
      ) : accountsQuery.isLoading ? (
        <Card>
          <CardContent className="p-0">
            <div className="divide-y divide-border">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4 px-6 py-3">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-5 w-14 ml-auto" />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : !accounts?.length ? (
        <Card>
          <CardContent className="p-0">
            <div className="divide-y divide-border">{settingsRowElement}</div>
            <div className="flex flex-col items-center justify-center py-12">
              <Mail className="mb-4 h-12 w-12 text-muted-foreground" />
              <p className="text-lg font-medium">No mail accounts</p>
              <p className="mb-4 text-sm text-muted-foreground">
                Add your first email account to get started.
              </p>
              <AppButton icon={<Plus />} label="Add Account" variant="primary" onClick={openCreateForm}>
                Add Account
              </AppButton>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="divide-y divide-border">
              {settingsRowElement}
              {accounts.map((account) => (
                <MailAccountRow
                  key={account.id}
                  account={account}
                  onEdit={openEditForm}
                  onDelete={setDeleteTarget}
                  onTest={(id) => testMutation.mutate({ accountId: id })}
                  onPoll={(id) => pollMutation.mutate({ accountId: id })}
                  onPause={(id) => pauseMutation.mutate({ accountId: id, data: { paused: true, pause_reason: "manual" } })}
                  onUnpause={(id) => unpauseMutation.mutate({ accountId: id, data: { paused: false, pause_reason: "manual" } })}
                  onResetHealth={(id) => resetHealthMutation.mutate({ accountId: id })}
                  testLoading={accountOps.isTestLoading(account.id)}
                  pollLoading={accountOps.isPollLoading(account.id)}
                  pauseLoading={pauseMutation.isPending && pauseMutation.variables?.accountId === account.id}
                  unpauseLoading={unpauseMutation.isPending && unpauseMutation.variables?.accountId === account.id}
                  resetHealthLoading={resetHealthMutation.isPending}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <MailAccountFormDialog
        open={formOpen}
        onClose={closeForm}
        form={form}
        editingAccount={editingAccount}
        onSubmit={onSubmit}
        isMutating={isMutating}
      />

      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Delete Mail Account"
        description={
          <>
            Are you sure you want to delete{" "}
            <span className="font-medium">{deleteTarget?.name}</span> (
            {deleteTarget?.email_address})? This action cannot be undone.
          </>
        }
        onConfirm={() => {
          if (deleteTarget) deleteMutation.mutate({ accountId: deleteTarget.id });
        }}
        isPending={deleteMutation.isPending}
      />
    </div>
  );
}
