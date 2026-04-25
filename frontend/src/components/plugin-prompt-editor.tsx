import { useState, useEffect, useCallback, useRef } from "react";
import {
  Save,
  RotateCcw,
  Eye,
  ChevronRight,
  X,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";

import {
  useGetPromptApiPromptsFunctionTypeGet,
  useUpdatePromptApiPromptsFunctionTypePut,
  useResetPromptApiPromptsFunctionTypeResetPost,
  usePreviewPromptApiPromptsFunctionTypePreviewPost,
  getGetPromptApiPromptsFunctionTypeGetQueryKey,
  getListPromptsApiPromptsGetQueryKey,
  useListVariablesApiPromptsVariablesGet,
} from "@/services/api/prompts/prompts";
import type { PromptResponse, TemplateVariable } from "@/types/api";

import { useToast } from "@/components/ui/toast";
import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Label } from "@/components/ui/label";
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
import { unwrapResponse } from "@/lib/utils";
import { cn } from "@/lib/utils";

interface PluginPromptEditorProps {
  /** The plugin's function_type identifier (e.g. "spam_detection"). */
  functionType: string;
  /** Human-readable plugin name for display. */
  displayName: string;
}

/**
 * Inline prompt template editor for a single plugin.
 *
 * Renders a Card with system/user prompt text areas, save/reset/preview
 * buttons, and a collapsible variables reference panel.
 */
export function PluginPromptEditor({
  functionType,
  displayName,
}: PluginPromptEditorProps) {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [systemPrompt, setSystemPrompt] = useState("");
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [variablesOpen, setVariablesOpen] = useState(false);

  // Tracks server state to avoid refetch clobbering in-progress edits
  const serverStateRef = useRef<{ system: string } | null>(null);

  // --- Data fetching ---
  const promptQuery = useGetPromptApiPromptsFunctionTypeGet(functionType, {
    query: { enabled: !!functionType },
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

  // --- Sync editor from fetched prompt ---
  useEffect(() => {
    if (!prompt) return;
    const serverSystem = prompt.system_prompt;
    const prev = serverStateRef.current;
    if (prev && prev.system === serverSystem) return;

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
      if (ref) setHasUnsavedChanges(value !== ref.system);
    },
    [],
  );

  // --- Save ---
  const handleSave = useCallback(() => {
    updateMutation.mutate(
      {
        functionType,
        data: {
          system_prompt: systemPrompt,
          user_prompt: null,
        },
      },
      {
        onSuccess: () => {
          serverStateRef.current = { system: systemPrompt };
          toast({ title: "Prompt saved", description: `Template for ${displayName} updated.` });
          setHasUnsavedChanges(false);
          queryClient.invalidateQueries({ queryKey: getGetPromptApiPromptsFunctionTypeGetQueryKey(functionType) });
          queryClient.invalidateQueries({ queryKey: getListPromptsApiPromptsGetQueryKey() });
        },
        onError: () => {
          toast({ title: "Save failed", description: "Could not save the prompt template. Please try again.", variant: "destructive" });
        },
      },
    );
  }, [functionType, systemPrompt, displayName, updateMutation, queryClient, toast]);

  // --- Reset ---
  const handleReset = useCallback(() => {
    resetMutation.mutate(
      { functionType },
      {
        onSuccess: () => {
          serverStateRef.current = null;
          toast({ title: "Prompt reset", description: `Template for ${displayName} reset to default.` });
          queryClient.invalidateQueries({ queryKey: getGetPromptApiPromptsFunctionTypeGetQueryKey(functionType) });
          queryClient.invalidateQueries({ queryKey: getListPromptsApiPromptsGetQueryKey() });
        },
        onError: () => {
          toast({ title: "Reset failed", description: "Could not reset the prompt to default. Please try again.", variant: "destructive" });
        },
      },
    );
  }, [functionType, displayName, resetMutation, queryClient, toast]);

  // --- Preview ---
  const handlePreview = useCallback(() => {
    previewMutation.mutate(
      {
        functionType,
        data: {
          system_prompt: systemPrompt,
          user_prompt: null,
        },
      },
      {
        onSuccess: () => setPreviewVisible(true),
        onError: () => {
          toast({ title: "Preview failed", description: "Could not render the prompt preview.", variant: "destructive" });
        },
      },
    );
  }, [functionType, systemPrompt, previewMutation, toast]);

  // --- Loading / Error ---
  if (promptQuery.isLoading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-4 w-64" />
        </CardHeader>
        <CardContent className="space-y-4">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-10 w-32" />
        </CardContent>
      </Card>
    );
  }

  if (promptQuery.isError) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">Prompt Template</CardTitle>
            <CardDescription>
              Customize the AI prompt used by this plugin.
            </CardDescription>
          </div>
          {prompt?.is_custom && (
            <Badge variant="secondary">Customized</Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* System prompt */}
        <div className="space-y-2">
          <Label>System Prompt</Label>
          <Textarea
            value={systemPrompt}
            onChange={(e) => handleSystemChange(e.target.value)}
            rows={10}
            className="font-mono text-sm"
            placeholder="System prompt template (Jinja2)..."
          />
        </div>

        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          <AppButton
            icon={<Save />}
            label="Save prompt"
            variant="primary"
            loading={updateMutation.isPending}
            onClick={handleSave}
            disabled={!hasUnsavedChanges || updateMutation.isPending}
          >
            Save
          </AppButton>
          <AppButton
            icon={<Eye />}
            label="Preview rendered prompt"
            onClick={handlePreview}
            loading={previewMutation.isPending}
            disabled={previewMutation.isPending}
          >
            Preview
          </AppButton>
          {prompt?.is_custom && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <AppButton
                  icon={<RotateCcw />}
                  label="Reset to default prompt"
                  loading={resetMutation.isPending}
                  disabled={resetMutation.isPending}
                >
                  Reset to Default
                </AppButton>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Reset prompt template?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will discard your custom prompt for {displayName} and
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
        </div>

        {/* Preview output */}
        {previewVisible && previewData && (
          <div className="space-y-2 rounded-md border border-border bg-muted/50 p-4">
            <div className="flex items-center justify-between">
              <Label className="text-xs text-muted-foreground">
                Rendered Preview
              </Label>
              <AppButton
                icon={<X />}
                label="Close preview"
                variant="ghost"
                className="h-7 w-7"
                onClick={() => setPreviewVisible(false)}
              />
            </div>
            <pre className="whitespace-pre-wrap text-sm">
              {previewData.rendered_system}
            </pre>
            {previewData.errors?.length > 0 && (
              <p className="text-xs text-destructive">
                Warnings: {previewData.errors.join(", ")}
              </p>
            )}
          </div>
        )}

        {/* Available variables */}
        {variables && variables.length > 0 && (
          <Collapsible open={variablesOpen} onOpenChange={setVariablesOpen}>
            <CollapsibleTrigger asChild>
              <AppButton
                icon={<ChevronRight className={cn("transition-transform", variablesOpen && "rotate-90")} />}
                label="Show template variables"
                variant="ghost"
                className="text-muted-foreground"
              >
                Available Template Variables
              </AppButton>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-2 grid gap-1">
                {variables.map((v) => (
                  <div
                    key={v.name}
                    className="flex items-baseline gap-2 rounded px-2 py-1 text-xs"
                  >
                    <code className="font-mono text-primary">
                      {"{{ " + v.name + " }}"}
                    </code>
                    <span className="text-muted-foreground">
                      {v.description}
                    </span>
                  </div>
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>
    </Card>
  );
}
