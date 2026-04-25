import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod/v4";
import { useQueryClient, useMutation } from "@tanstack/react-query";
import { Plus, BrainCircuit, Settings2 } from "lucide-react";
import { usePageTitle } from "@/hooks/use-page-title";

import {
  useListProvidersApiAiProvidersGet,
  useCreateProviderApiAiProvidersPost,
  useUpdateProviderApiAiProvidersProviderIdPut,
  useDeleteProviderApiAiProvidersProviderIdDelete,
  useTestProviderApiAiProvidersProviderIdTestPost,
  getListProvidersApiAiProvidersGetQueryKey,
  useListPluginsApiAiProvidersPluginsGet,
} from "@/services/api/ai-providers/ai-providers";
import {
  useGetSettingsApiSettingsGet,
  useUpdateSettingsApiSettingsPut,
  getGetSettingsApiSettingsGetQueryKey,
} from "@/services/api/settings/settings";
import type {
  AIProviderResponse,
  AIProviderTestResult,
} from "@/types/api";
import { customInstance } from "@/services/client";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import { DeleteConfirmDialog } from "@/components/delete-confirm-dialog";
import { AppButton } from "@/components/app-button";
import { InlineSettingsRow } from "@/components/inline-settings-row";
import { useToast } from "@/components/ui/toast";

import { unwrapResponse } from "@/lib/utils";
import type { AIProviderFormValues } from "./ai-settings-schemas";
import { providerTypeLabel } from "./ai-settings-schemas";
import { AIProviderRow } from "./ai-provider-row";
import { AIProviderFormDialog } from "./ai-provider-form-dialog";

// ---------------------------------------------------------------------------
// AI Settings Page
// ---------------------------------------------------------------------------

export default function AISettingsPage() {
  usePageTitle("AI Settings");
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Dialog state
  const [formOpen, setFormOpen] = useState(false);
  const [editingProvider, setEditingProvider] =
    useState<AIProviderResponse | null>(null);
  const [deleteTarget, setDeleteTarget] =
    useState<AIProviderResponse | null>(null);

  // ---------------------------------------------------------------------------
  // Pause / unpause / reset-health mutations
  // ---------------------------------------------------------------------------

  const unpauseMutation = useMutation({
    mutationFn: (providerId: string) =>
      customInstance<{ data: AIProviderResponse }>(
        `/api/ai-providers/${providerId}/pause`,
        { method: "PATCH", body: JSON.stringify({ paused: false, pause_reason: "manual" }) },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: getListProvidersApiAiProvidersGetQueryKey() });
      toast({ title: "Provider unpaused", description: "AI provider has been resumed." });
    },
    onError: () => {
      toast({ title: "Unpause failed", description: "Could not unpause the provider.", variant: "destructive" });
    },
  });

  const pauseMutation = useMutation({
    mutationFn: (providerId: string) =>
      customInstance<{ data: AIProviderResponse }>(
        `/api/ai-providers/${providerId}/pause`,
        { method: "PATCH", body: JSON.stringify({ paused: true, pause_reason: "manual" }) },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: getListProvidersApiAiProvidersGetQueryKey() });
      toast({ title: "Provider paused", description: "AI provider has been paused." });
    },
    onError: () => {
      toast({ title: "Pause failed", description: "Could not pause the provider.", variant: "destructive" });
    },
  });

  const resetHealthMutation = useMutation({
    mutationFn: (providerId: string) =>
      customInstance<{ data: AIProviderResponse }>(
        `/api/ai-providers/${providerId}/reset-health`,
        { method: "POST" },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: getListProvidersApiAiProvidersGetQueryKey() });
      toast({ title: "Health reset", description: "Provider errors cleared and re-activated." });
    },
    onError: () => {
      toast({ title: "Reset failed", description: "Could not reset provider health.", variant: "destructive" });
    },
  });

  // ---------------------------------------------------------------------------
  // Data fetching
  // ---------------------------------------------------------------------------

  const providersQuery = useListProvidersApiAiProvidersGet();
  const providers = unwrapResponse<AIProviderResponse[]>(providersQuery.data);

  const pluginsQuery = useListPluginsApiAiProvidersPluginsGet();
  const pipelinePlugins = (unwrapResponse<{ name: string; display_name: string; runs_in_pipeline?: boolean }[]>(pluginsQuery.data) ?? [])
    .filter((p) => p.runs_in_pipeline !== false);

  const settingsQuery = useGetSettingsApiSettingsGet();
  const settings = unwrapResponse<{ plugin_provider_map?: Record<string, string> | null }>(settingsQuery.data);
  const pluginProviderMap: Record<string, string> = settings?.plugin_provider_map ?? {};
  const updateSettingsMutation = useUpdateSettingsApiSettingsPut();

  // ---------------------------------------------------------------------------
  // AI Processing settings form (Concurrent Processing Slots)
  // ---------------------------------------------------------------------------

  const aiSettingsSchema = z.object({
    max_concurrent_processing: z.number().int().min(1).max(20),
    ai_timeout_seconds: z.number().int().min(10).max(600),
  });

  type AISettingsFormValues = z.infer<typeof aiSettingsSchema>;

  const aiSettingsForm = useForm<AISettingsFormValues>({
    resolver: zodResolver(aiSettingsSchema),
    defaultValues: { max_concurrent_processing: 5, ai_timeout_seconds: 120 },
  });

  useEffect(() => {
    if (settings && "max_concurrent_processing" in settings) {
      aiSettingsForm.reset({
        max_concurrent_processing:
          (settings as Record<string, unknown>).max_concurrent_processing as number ?? 5,
        ai_timeout_seconds:
          (settings as Record<string, unknown>).ai_timeout_seconds as number ?? 120,
      });
    }
  }, [settings, aiSettingsForm]);

  async function saveAISettings(values: AISettingsFormValues) {
    try {
      await updateSettingsMutation.mutateAsync({ data: values });
      queryClient.invalidateQueries({
        queryKey: getGetSettingsApiSettingsGetQueryKey(),
      });
      aiSettingsForm.reset(values);
      toast({ title: "Settings saved", description: "AI settings have been updated successfully." });
    } catch {
      toast({ title: "Failed to save settings", description: "Could not save the AI settings. Please try again.", variant: "destructive" });
    }
  }

  // ---------------------------------------------------------------------------
  // Plugin assignment
  // ---------------------------------------------------------------------------

  async function togglePluginAssignment(pluginName: string, providerId: string) {
    const current = { ...pluginProviderMap };
    if (current[pluginName] === providerId) {
      toast({
        title: "Cannot unassign",
        description: `"${pluginName}" must be assigned to at least one provider. Assign it to another provider first.`,
        variant: "destructive",
      });
      return;
    } else {
      current[pluginName] = providerId;
    }
    try {
      await updateSettingsMutation.mutateAsync({
        data: { plugin_provider_map: current },
      });
      queryClient.invalidateQueries({
        queryKey: getGetSettingsApiSettingsGetQueryKey(),
      });
    } catch {
      toast({
        title: "Failed to update plugin assignment",
        description: "Could not change the provider assignment. Please try again.",
        variant: "destructive",
      });
    }
  }

  // ---------------------------------------------------------------------------
  // CRUD mutations
  // ---------------------------------------------------------------------------

  const createMutation = useCreateProviderApiAiProvidersPost({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListProvidersApiAiProvidersGetQueryKey() });
        queryClient.invalidateQueries({ queryKey: getGetSettingsApiSettingsGetQueryKey() });
        toast({ title: "Provider created", description: "AI provider has been added successfully." });
        closeForm();
      },
      onError: () => {
        toast({ title: "Failed to create provider", description: "Please check the form and try again.", variant: "destructive" });
      },
    },
  });

  const updateMutation = useUpdateProviderApiAiProvidersProviderIdPut({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListProvidersApiAiProvidersGetQueryKey() });
        toast({ title: "Provider updated", description: "AI provider has been updated successfully." });
        closeForm();
      },
      onError: () => {
        toast({ title: "Failed to update provider", description: "Please check the form and try again.", variant: "destructive" });
      },
    },
  });

  const deleteMutation = useDeleteProviderApiAiProvidersProviderIdDelete({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getListProvidersApiAiProvidersGetQueryKey() });
        toast({ title: "Provider deleted", description: "AI provider has been removed." });
        setDeleteTarget(null);
      },
      onError: () => {
        toast({ title: "Failed to delete provider", description: "An error occurred while deleting the provider.", variant: "destructive" });
      },
    },
  });

  const testMutation = useTestProviderApiAiProvidersProviderIdTestPost({
    mutation: {
      onSuccess: (response) => {
        const result = unwrapResponse<AIProviderTestResult>(response);
        if (result) {
          toast({
            title: result.success ? "Connection successful" : "Connection failed",
            description: `${result.message} (model: ${result.model})`,
            variant: result.success ? "default" : "destructive",
          });
        }
      },
      onError: () => {
        toast({ title: "Connection test failed", description: "Could not reach the AI provider.", variant: "destructive" });
      },
    },
  });

  // ---------------------------------------------------------------------------
  // Form helpers
  // ---------------------------------------------------------------------------

  function openCreateForm() {
    setEditingProvider(null);
    setFormOpen(true);
  }

  function openEditForm(provider: AIProviderResponse) {
    setEditingProvider(provider);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
    setEditingProvider(null);
  }

  function onSubmit(values: AIProviderFormValues) {
    const nameValue = values.name?.trim() || undefined;
    if (editingProvider) {
      updateMutation.mutate({
        providerId: editingProvider.id,
        data: {
          name: nameValue ?? null,
          provider_type: values.provider_type,
          base_url: values.base_url,
          model_name: values.model_name,
          temperature: values.temperature,
          max_tokens: values.max_tokens,
          timeout_seconds: values.timeout_seconds ?? null,
          ...(values.api_key ? { api_key: values.api_key } : {}),
        },
      });
    } else {
      createMutation.mutate({
        data: {
          name: nameValue ?? null,
          provider_type: values.provider_type,
          base_url: values.base_url,
          model_name: values.model_name,
          temperature: values.temperature,
          max_tokens: values.max_tokens,
          timeout_seconds: values.timeout_seconds ?? null,
          ...(values.api_key ? { api_key: values.api_key } : {}),
        },
      });
    }
  }

  const isMutating = createMutation.isPending || updateMutation.isPending;

  // ---------------------------------------------------------------------------
  // Inline settings row config (shared between empty and populated states)
  // ---------------------------------------------------------------------------

  const settingsRow = (
    <InlineSettingsRow
      icon={<Settings2 />}
      title="AI Processing Settings"
      onSave={aiSettingsForm.handleSubmit(saveAISettings)}
      saving={updateSettingsMutation.isPending}
      saveDisabled={!aiSettingsForm.formState.isDirty}
      fields={[
        {
          key: "max_concurrent",
          label: "Concurrent Processing Slots",
          input: (
            <Input
              type="number"
              min={1}
              max={20}
              className="w-28 h-8 text-sm"
              {...aiSettingsForm.register("max_concurrent_processing", { valueAsNumber: true })}
            />
          ),
          error: aiSettingsForm.formState.errors.max_concurrent_processing?.message,
          hint: "Max mails processed simultaneously (1-20).",
        },
        {
          key: "ai_timeout",
          label: "Default LLM Timeout (seconds)",
          input: (
            <Input
              type="number"
              min={10}
              max={600}
              className="w-28 h-8 text-sm"
              {...aiSettingsForm.register("ai_timeout_seconds", { valueAsNumber: true })}
            />
          ),
          error: aiSettingsForm.formState.errors.ai_timeout_seconds?.message,
          hint: "Global timeout for AI requests (10-600s). Per-provider overrides take precedence.",
        },
      ]}
    />
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI Providers"
        description="Configure your AI providers for mail processing."
        actions={
          <AppButton icon={<Plus />} label="Add Provider" variant="primary" onClick={openCreateForm}>
            Add Provider
          </AppButton>
        }
      />

      {/* Providers list */}
      {providersQuery.isError ? (
        <QueryError message="Failed to load AI providers." onRetry={() => providersQuery.refetch()} />
      ) : providersQuery.isLoading ? (
        <Card>
          <CardContent className="p-0">
            <div className="divide-y divide-border">
              {Array.from({ length: 2 }).map((_, i) => (
                <div key={i} className="flex items-center gap-4 px-6 py-3">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-5 w-14 ml-auto" />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      ) : !providers?.length ? (
        <Card>
          <CardContent className="p-0">
            <div className="divide-y divide-border">{settingsRow}</div>
            <div className="flex flex-col items-center justify-center py-12">
              <BrainCircuit className="mb-4 h-12 w-12 text-muted-foreground" />
              <p className="text-lg font-medium">No AI providers</p>
              <p className="mb-4 text-sm text-muted-foreground">
                Add an AI provider to enable intelligent mail processing.
              </p>
              <AppButton icon={<Plus />} label="Add Provider" variant="primary" onClick={openCreateForm}>
                Add Provider
              </AppButton>
            </div>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <div className="divide-y divide-border">
              {settingsRow}
              {providers.map((provider) => (
                <AIProviderRow
                  key={provider.id}
                  provider={provider}
                  pipelinePlugins={pipelinePlugins}
                  pluginProviderMap={pluginProviderMap}
                  onEdit={openEditForm}
                  onDelete={setDeleteTarget}
                  onTest={(id) => testMutation.mutate({ providerId: id })}
                  onPause={(id) => pauseMutation.mutate(id)}
                  onUnpause={(id) => unpauseMutation.mutate(id)}
                  onResetHealth={(id) => resetHealthMutation.mutate(id)}
                  onTogglePlugin={togglePluginAssignment}
                  pauseLoading={pauseMutation.isPending && pauseMutation.variables === provider.id}
                  unpauseLoading={unpauseMutation.isPending && unpauseMutation.variables === provider.id}
                  testLoading={testMutation.isPending && testMutation.variables?.providerId === provider.id}
                  resetHealthLoading={resetHealthMutation.isPending}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Create / Edit dialog */}
      <AIProviderFormDialog
        open={formOpen}
        editingProvider={editingProvider}
        isMutating={isMutating}
        onClose={closeForm}
        onSubmit={onSubmit}
      />

      {/* Delete confirmation dialog */}
      <DeleteConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Delete AI Provider"
        description={
          <>
            Are you sure you want to delete{" "}
            <span className="font-medium">
              {deleteTarget
                ? (deleteTarget.name || providerTypeLabel(deleteTarget.provider_type))
                : ""}
            </span>{" "}
            ({deleteTarget?.model_name})? This action cannot be undone.
          </>
        }
        onConfirm={() => {
          if (deleteTarget) {
            deleteMutation.mutate({ providerId: deleteTarget.id });
          }
        }}
        isPending={deleteMutation.isPending}
      />
    </div>
  );
}
