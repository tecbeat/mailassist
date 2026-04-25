import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  Save,
  RotateCcw,
  Eye,
  Pencil,
  ChevronRight,
  FileCode2,
  Variable,
  AlertCircle,
  Check,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useListPromptsApiPromptsGet,
  useGetPromptApiPromptsFunctionTypeGet,
  useUpdatePromptApiPromptsFunctionTypePut,
  useResetPromptApiPromptsFunctionTypeResetPost,
  usePreviewPromptApiPromptsFunctionTypePreviewPost,
  getGetPromptApiPromptsFunctionTypeGetQueryKey,
  getListPromptsApiPromptsGetQueryKey,
} from "@/services/api/prompts/prompts";
import {
  useListVariablesApiPromptsVariablesGet,
} from "@/services/api/prompts/prompts";
import {
  useListPluginsApiAiProvidersPluginsGet,
} from "@/services/api/ai-providers/ai-providers";
import {
  useGetSettingsApiSettingsGet,
} from "@/services/api/settings/settings";
import type { PromptResponse, TemplateVariable, PluginInfo, SettingsResponse } from "@/types/api";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { useToast } from "@/components/ui/toast";
import { cn, unwrapResponse } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function PromptsPage() {
  usePageTitle("Prompts");
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [selectedType, setSelectedType] = useState<string>("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [variablesOpen, setVariablesOpen] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);

  // Unsaved-changes guard state
  const [pendingSwitchType, setPendingSwitchType] = useState<string | null>(null);
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);

  // Tracks the server state we last loaded into the editor, preventing
  // React Query background refetches from overwriting in-progress edits.
  const serverStateRef = useRef<{ system: string } | null>(null);

  // --- Dynamic function type list from backend ---
  const pluginsQuery = useListPluginsApiAiProvidersPluginsGet();
  const plugins = unwrapResponse<PluginInfo[]>(pluginsQuery.data);

  // Fetch settings to determine which plugins are enabled
  const settingsQuery = useGetSettingsApiSettingsGet();
  const settings = unwrapResponse<SettingsResponse>(settingsQuery.data);

  // Map plugin names to their approval_mode key
  const PLUGIN_APPROVAL_KEY: Record<string, string> = {
    spam_detection: "spam",
    labeling: "labeling",
    smart_folder: "smart_folder",
    newsletter_detection: "newsletter",
    auto_reply: "auto_reply",
    coupon_extraction: "coupon",
    calendar_extraction: "calendar",
    email_summary: "summary",
  };

  // Sort by execution_order, then filter to only show enabled plugins with prompts
  const sortedPlugins = useMemo(() => {
    if (!plugins) return [];
    const sorted = [...plugins].sort((a, b) => a.execution_order - b.execution_order);
    if (!settings?.approval_modes) {
      return sorted.filter((p) => !!p.default_prompt_template);
    }
    const modes = settings.approval_modes as Record<string, string>;
    return sorted.filter((p) => {
      // Hide plugins without a prompt template
      if (!p.default_prompt_template) return false;
      const key = PLUGIN_APPROVAL_KEY[p.name];
      if (!key) return true;
      return modes[key] !== "disabled";
    });
  }, [plugins, settings]);

  // Auto-select the first plugin once loaded
  useEffect(() => {
    if (sortedPlugins.length > 0 && !selectedType) {
      setSelectedType(sortedPlugins[0]!.name);
    }
  }, [sortedPlugins, selectedType]);

  // --- Data fetching ---
  const promptsListQuery = useListPromptsApiPromptsGet();
  const promptsList = unwrapResponse<PromptResponse[]>(promptsListQuery.data);

  const promptQuery = useGetPromptApiPromptsFunctionTypeGet(selectedType, {
    query: { enabled: !!selectedType },
  });
  const prompt = unwrapResponse<PromptResponse>(promptQuery.data);

  const variablesQuery = useListVariablesApiPromptsVariablesGet();
  const variables = unwrapResponse<TemplateVariable[]>(variablesQuery.data);

  // --- Mutations ---
  const updateMutation = useUpdatePromptApiPromptsFunctionTypePut();
  const resetMutation = useResetPromptApiPromptsFunctionTypeResetPost();
  const previewMutation = usePreviewPromptApiPromptsFunctionTypePreviewPost();

  const previewData = unwrapResponse<{
    rendered_system: string;
    rendered_user: string | null;
    errors: string[];
  }>(previewMutation.data);

  // --- Sync editor state from fetched prompt ---
  // Only populate the editor when the fetched prompt differs from what we
  // already loaded (i.e., on initial load or after a type change / save / reset),
  // NOT on every background React Query refetch.
  useEffect(() => {
    if (!prompt) return;

    const serverSystem = prompt.system_prompt;
    const prev = serverStateRef.current;

    // Skip if server state matches what we already loaded
    if (prev && prev.system === serverSystem) {
      return;
    }

    serverStateRef.current = { system: serverSystem };
    setSystemPrompt(serverSystem);
    setHasUnsavedChanges(false);
    setPreviewVisible(false);
  }, [prompt]);

  // --- Track unsaved changes ---
  const handleSystemChange = useCallback(
    (value: string) => {
      setSystemPrompt(value);
      const ref = serverStateRef.current;
      if (ref) {
        setHasUnsavedChanges(value !== ref.system);
      }
    },
    [],
  );

  // --- Sidebar navigation with unsaved-changes guard ---
  const handleSelectType = useCallback(
    (type: string) => {
      if (type === selectedType) return;
      if (hasUnsavedChanges) {
        setPendingSwitchType(type);
        setDiscardDialogOpen(true);
      } else {
        serverStateRef.current = null;
        setSelectedType(type);
      }
    },
    [selectedType, hasUnsavedChanges],
  );

  const handleDiscardAndSwitch = useCallback(() => {
    if (pendingSwitchType) {
      serverStateRef.current = null;
      setSelectedType(pendingSwitchType);
      setHasUnsavedChanges(false);
      setPendingSwitchType(null);
    }
    setDiscardDialogOpen(false);
  }, [pendingSwitchType]);

  const handleCancelSwitch = useCallback(() => {
    setPendingSwitchType(null);
    setDiscardDialogOpen(false);
  }, []);

  // --- Get custom status from the list for the sidebar ---
  const getIsCustom = (functionType: string): boolean | undefined => {
    if (!promptsList) return undefined;
    const p = promptsList.find((item) => item.function_type === functionType);
    return p?.is_custom;
  };

  // --- Metadata for selected type ---
  const selectedPlugin = sortedPlugins.find((p) => p.name === selectedType);

  // --- Save handler ---
  const handleSave = () => {
    updateMutation.mutate(
      {
        functionType: selectedType,
        data: {
          system_prompt: systemPrompt,
          user_prompt: null,
        },
      },
      {
        onSuccess: () => {
          // Update the ref so the next refetch doesn't clobber the editor
          serverStateRef.current = { system: systemPrompt };
          toast({ title: "Prompt saved", description: `Template for ${selectedPlugin?.display_name ?? selectedType} updated successfully.` });
          setHasUnsavedChanges(false);
          queryClient.invalidateQueries({ queryKey: getGetPromptApiPromptsFunctionTypeGetQueryKey(selectedType) });
          queryClient.invalidateQueries({ queryKey: getListPromptsApiPromptsGetQueryKey() });
        },
        onError: () => {
          toast({ title: "Save failed", description: "Could not save prompt template. Please try again.", variant: "destructive" });
        },
      },
    );
  };

  // --- Reset handler ---
  const handleReset = () => {
    resetMutation.mutate(
      { functionType: selectedType },
      {
        onSuccess: () => {
          // Clear the ref so the refetch populates fresh default content
          serverStateRef.current = null;
          toast({ title: "Prompt reset", description: `Template for ${selectedPlugin?.display_name ?? selectedType} reset to default.` });
          queryClient.invalidateQueries({ queryKey: getGetPromptApiPromptsFunctionTypeGetQueryKey(selectedType) });
          queryClient.invalidateQueries({ queryKey: getListPromptsApiPromptsGetQueryKey() });
        },
        onError: () => {
          toast({ title: "Reset failed", description: "Could not reset prompt template.", variant: "destructive" });
        },
      },
    );
  };

  // --- Preview handler ---
  const handlePreview = () => {
    if (previewVisible) {
      // Toggle back to edit mode
      setPreviewVisible(false);
      return;
    }
    previewMutation.mutate(
      {
        functionType: selectedType,
        data: {
          system_prompt: systemPrompt,
          user_prompt: null,
        },
      },
      {
        onSuccess: () => {
          setPreviewVisible(true);
        },
        onError: () => {
          toast({ title: "Preview failed", description: "Could not render prompt preview.", variant: "destructive" });
        },
      },
    );
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Prompt Templates"
        description="Customize Jinja2 prompt templates used by AI functions."
      />

      {/* Discard unsaved changes dialog */}
      <AlertDialog open={discardDialogOpen} onOpenChange={setDiscardDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              You have unsaved changes to the{" "}
              <span className="font-medium">{selectedPlugin?.display_name ?? selectedType}</span>{" "}
              template. Switching will discard them.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancelSwitch}>
              Stay
            </AlertDialogCancel>
            <AlertDialogAction onClick={handleDiscardAndSwitch}>
              Discard
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* ---------------------------------------------------------------- */}
        {/* Left sidebar - function types (dynamic from backend)             */}
        {/* ---------------------------------------------------------------- */}
        <div className="w-full shrink-0 lg:w-64">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Functions</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {pluginsQuery.isError ? (
                <QueryError message="Failed to load plugins." onRetry={() => pluginsQuery.refetch()} />
              ) : pluginsQuery.isLoading ? (
                <div className="space-y-2 px-4 pb-4">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <Skeleton key={i} className="h-8 w-full" />
                  ))}
                </div>
              ) : sortedPlugins.length === 0 ? (
                <p className="px-4 pb-4 text-sm text-muted-foreground">
                  No AI plugins registered.
                </p>
              ) : (
                <nav className="flex flex-col">
                  {sortedPlugins.map((plugin) => {
                    const isCustom = getIsCustom(plugin.name);
                    const isSelected = selectedType === plugin.name;
                    return (
                      <button
                        key={plugin.name}
                        onClick={() => handleSelectType(plugin.name)}
                        aria-current={isSelected ? "page" : undefined}
                        className={cn(
                          "flex items-center gap-2 px-4 py-2.5 text-left text-sm transition-colors hover:bg-accent",
                          isSelected && "bg-accent font-medium",
                        )}
                      >
                        <FileCode2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="flex-1 truncate">{plugin.display_name}</span>
                        {isCustom === true && (
                          <Badge variant="secondary">
                            Custom
                          </Badge>
                        )}
                      </button>
                    );
                  })}
                </nav>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Right panel - editor                                             */}
        {/* ---------------------------------------------------------------- */}
        <div className="min-w-0 flex-1 space-y-4">
          {!selectedType ? (
            <Card>
              <CardContent className="py-12 text-center">
                <FileCode2 className="mx-auto mb-3 h-10 w-10 text-muted-foreground" />
                <CardTitle className="mb-1">Select a function</CardTitle>
                <CardDescription>
                  Choose an AI function from the sidebar to view or edit its prompt template.
                </CardDescription>
              </CardContent>
            </Card>
          ) : (
            <>
              {/* Header */}
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-semibold">{selectedPlugin?.display_name ?? selectedType}</h2>
                    {prompt?.is_custom && (
                      <Badge variant="secondary">Customized</Badge>
                    )}
                    {hasUnsavedChanges && (
                      <Badge variant="destructive">
                        Unsaved
                      </Badge>
                    )}
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {selectedPlugin?.description}
                  </p>
                </div>
              </div>

              {/* Editor area */}
              {promptQuery.isError ? (
                <QueryError message="Failed to load prompt." onRetry={() => promptQuery.refetch()} />
              ) : promptQuery.isLoading ? (
                <div className="space-y-3">
                  <Skeleton className="h-5 w-32" />
                  <Skeleton className="h-64 w-full" />
                </div>
              ) : (
                <div className="space-y-4">
                  {/* System prompt / Preview inline */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">
                      {previewVisible ? "Preview (with sample data)" : "System Prompt"}
                    </label>
                    {previewVisible && previewData ? (
                      <div className="relative">
                        {previewData.errors.length > 0 && (
                          <div className="absolute right-2 top-2 z-10 flex items-start gap-2 rounded-md border border-destructive bg-destructive/5 p-2 backdrop-blur-sm">
                            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                            <div className="space-y-1">
                              <p className="text-xs font-medium text-destructive">
                                Template Errors
                              </p>
                              {previewData.errors.map((err, i) => (
                                <p key={i} className="text-xs text-destructive/80">
                                  {err}
                                </p>
                              ))}
                            </div>
                          </div>
                        )}
                        {previewData.errors.length === 0 && (
                          <div className="absolute right-[18px] top-2 z-10 flex items-center gap-1.5 rounded-md border border-green-200 bg-green-50/90 px-2 py-1 text-xs text-green-600 backdrop-blur-sm dark:border-green-800 dark:bg-green-950/90">
                            <Check className="h-3.5 w-3.5" />
                            Rendered successfully
                          </div>
                        )}
                        <pre className="h-[300px] overflow-auto whitespace-pre-wrap break-words rounded-md border border-input bg-muted px-3 py-2 pr-48 font-mono text-xs leading-relaxed">
                          {previewData.rendered_system}
                        </pre>
                      </div>
                    ) : (
                      <Textarea
                        value={systemPrompt}
                        onChange={(e) => handleSystemChange(e.target.value)}
                        className="h-[300px] resize-none font-mono text-xs leading-relaxed"
                        placeholder="Enter Jinja2 system prompt template..."
                      />
                    )}
                  </div>

                  {/* Available variables header + action buttons in one row */}
                  <Collapsible open={variablesOpen} onOpenChange={setVariablesOpen}>
                    <div className="flex items-center gap-2">
                      <CollapsibleTrigger asChild>
                        <button
                          type="button"
                          className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
                        >
                          <ChevronRight
                            className={cn(
                              "h-4 w-4 transition-transform",
                              variablesOpen && "rotate-90",
                            )}
                          />
                          <Variable className="h-4 w-4" />
                          Available Template Variables
                        </button>
                      </CollapsibleTrigger>

                      {/* Buttons pushed to the right */}
                      <div className="ml-auto flex flex-wrap gap-2">
                        {prompt?.is_custom && (
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <AppButton icon={<RotateCcw />} label="Reset to Default" disabled={resetMutation.isPending}>
                                Reset to Default
                              </AppButton>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>Reset to default template?</AlertDialogTitle>
                                <AlertDialogDescription>
                                  This will discard your custom template for{" "}
                                  <span className="font-medium">{selectedPlugin?.display_name ?? selectedType}</span> and
                                  restore the built-in default. This action cannot be undone.
                                </AlertDialogDescription>
                              </AlertDialogHeader>
                              <AlertDialogFooter>
                                <AlertDialogCancel>Cancel</AlertDialogCancel>
                                <AlertDialogAction onClick={handleReset}>
                                  Reset
                                </AlertDialogAction>
                              </AlertDialogFooter>
                            </AlertDialogContent>
                          </AlertDialog>
                        )}

                        <AppButton
                          icon={previewVisible ? <Pencil /> : <Eye />}
                          label={previewVisible ? "Edit" : "Preview"}
                          onClick={handlePreview}
                          disabled={previewMutation.isPending}
                          loading={previewMutation.isPending}
                        >
                          {previewMutation.isPending
                            ? "Rendering..."
                            : previewVisible
                              ? "Edit"
                              : "Preview"}
                        </AppButton>

                        <AppButton
                          icon={<Save />}
                          label="Save"
                          variant="primary"
                          onClick={handleSave}
                          disabled={updateMutation.isPending || !hasUnsavedChanges}
                          loading={updateMutation.isPending}
                        >
                          {updateMutation.isPending ? "Saving..." : "Save"}
                        </AppButton>
                      </div>
                    </div>

                    {/* 3-column grid of variable cards (no wrapping Card) */}
                    <CollapsibleContent>
                      <div className="mt-3">
                        {variablesQuery.isError ? (
                          <QueryError message="Failed to load variables." onRetry={() => variablesQuery.refetch()} />
                        ) : variablesQuery.isLoading ? (
                          <div className="space-y-2">
                            {Array.from({ length: 4 }).map((_, i) => (
                              <Skeleton key={i} className="h-4 w-full" />
                            ))}
                          </div>
                        ) : !variables?.length ? (
                          <p className="text-sm text-muted-foreground">
                            No variables available.
                          </p>
                        ) : (
                          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                            {variables.map((v) => (
                              <div
                                key={v.name}
                                className="rounded-md border border-border p-2.5"
                              >
                                <div className="flex items-center gap-2">
                                  <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-semibold">
                                    {"{{ " + v.name + " }}"}
                                  </code>
                                  <Badge variant="secondary">
                                    {v.var_type}
                                  </Badge>
                                </div>
                                <p className="mt-1 text-xs text-muted-foreground">
                                  {v.description}
                                </p>
                                {v.example && (
                                  <p className="mt-0.5 text-xs text-muted-foreground/70">
                                    e.g. <code className="text-foreground/60">{v.example}</code>
                                  </p>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
