import { useState, useEffect, useCallback, useRef } from "react";
import {
  ChevronRight,
  Eye,
  FileCode2,
  Pencil,
  RotateCcw,
  Save,
  Variable,
} from "lucide-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/ui/toast";
import { AppButton } from "@/components/app-button";
import { Badge } from "@/components/ui/badge";
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
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { TemplatePreview } from "./template-preview";
import { TemplateVariables } from "./template-variables";

// ---------------------------------------------------------------------------
// Types & API helpers
// ---------------------------------------------------------------------------

interface NotificationConfig {
  id: string;
  templates: Record<string, string>;
  updated_at: string;
}

interface NotificationEventInfo {
  event_type: string;
  plugin_name: string;
  display_name: string;
  execution_order: number;
}

const API_BASE = "/api/notifications";

async function fetchConfig(): Promise<NotificationConfig> {
  const res = await fetch(`${API_BASE}/config`);
  if (!res.ok) throw new Error("Failed to load config");
  return res.json();
}

async function updateConfig(templates: Record<string, string>): Promise<NotificationConfig> {
  const res = await fetch(`${API_BASE}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ templates }),
  });
  if (!res.ok) throw new Error("Failed to save config");
  return res.json();
}

async function fetchDefaultTemplate(eventType: string): Promise<string> {
  const res = await fetch(`${API_BASE}/templates/default/${eventType}`);
  if (!res.ok) throw new Error("Failed to load default template");
  const data = await res.json();
  return data.template;
}

async function previewTemplate(
  template: string,
  eventType: string,
): Promise<{ rendered: string; errors: string[] }> {
  const res = await fetch(`${API_BASE}/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template, event_type: eventType }),
  });
  if (!res.ok) throw new Error("Failed to preview");
  return res.json();
}

async function fetchEvents(): Promise<NotificationEventInfo[]> {
  const res = await fetch(`${API_BASE}/events`);
  if (!res.ok) throw new Error("Failed to load events");
  return res.json();
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * Full template editing experience: type sidebar, editor textarea, preview,
 * save/reset/preview actions, and the variables reference panel.
 */
export function TemplateEditor() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const configQuery = useQuery({
    queryKey: ["notification-config"],
    queryFn: fetchConfig,
  });
  const config = configQuery.data;

  const eventsQuery = useQuery({
    queryKey: ["notification-events"],
    queryFn: fetchEvents,
    staleTime: 5 * 60_000,
  });
  const templateTypes = (eventsQuery.data ?? []).map((e) => ({
    value: e.event_type,
    label: e.display_name,
  }));

  const [selectedTemplate, setSelectedTemplate] = useState("");
  const [templateContent, setTemplateContent] = useState("");
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewResult, setPreviewResult] = useState<string | null>(null);
  const [previewErrors, setPreviewErrors] = useState<string[]>([]);
  const [variablesOpen, setVariablesOpen] = useState(false);
  const [pendingSwitchType, setPendingSwitchType] = useState<string | null>(null);
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);

  const serverStateRef = useRef<string | null>(null);

  // Auto-select first template type
  useEffect(() => {
    if (!selectedTemplate && templateTypes.length > 0) {
      setSelectedTemplate(templateTypes[0]!.value);
    }
  }, [selectedTemplate, templateTypes]);

  function currentTemplates(): Record<string, string> {
    return config?.templates ?? {};
  }

  const isCustomTemplate = !!currentTemplates()[selectedTemplate];
  const selectedLabel =
    templateTypes.find((t) => t.value === selectedTemplate)?.label ?? selectedTemplate;

  // Load the effective template content when selection or config changes
  const loadTemplate = useCallback(
    async (type: string) => {
      const custom = currentTemplates()[type];
      if (custom) {
        setTemplateContent(custom);
        serverStateRef.current = custom;
      } else {
        try {
          const defaultTpl = await fetchDefaultTemplate(type);
          setTemplateContent(defaultTpl);
          serverStateRef.current = defaultTpl;
        } catch {
          setTemplateContent("");
          serverStateRef.current = "";
        }
      }
      setHasUnsavedChanges(false);
      setPreviewVisible(false);
      setPreviewResult(null);
      setPreviewErrors([]);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [config],
  );

  useEffect(() => {
    if (selectedTemplate) {
      loadTemplate(selectedTemplate);
    }
  }, [selectedTemplate, loadTemplate]);

  function switchType(type: string) {
    if (hasUnsavedChanges) {
      setPendingSwitchType(type);
      setDiscardDialogOpen(true);
    } else {
      setSelectedTemplate(type);
    }
  }

  function confirmDiscard() {
    if (pendingSwitchType) {
      setSelectedTemplate(pendingSwitchType);
      setPendingSwitchType(null);
    }
    setDiscardDialogOpen(false);
  }

  // Save
  const saveMutation = useMutation({
    mutationFn: async () => {
      const templates = { ...currentTemplates() };
      // Only save if content differs from default
      templates[selectedTemplate] = templateContent;
      return updateConfig(templates);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notification-config"] });
      setHasUnsavedChanges(false);
      toast({ title: "Template saved", description: `Updated template for "${selectedLabel}".` });
    },
    onError: () => {
      toast({ title: "Save failed", description: "Could not save template.", variant: "destructive" });
    },
  });

  // Reset to default
  async function resetToDefault() {
    const templates = { ...currentTemplates() };
    delete templates[selectedTemplate];
    try {
      await updateConfig(templates);
      queryClient.invalidateQueries({ queryKey: ["notification-config"] });
      await loadTemplate(selectedTemplate);
      toast({ title: "Template reset", description: `Reverted "${selectedLabel}" to default.` });
    } catch {
      toast({ title: "Reset failed", description: "Could not reset template.", variant: "destructive" });
    }
  }

  // Preview
  async function onPreview() {
    try {
      const result = await previewTemplate(templateContent, selectedTemplate);
      setPreviewResult(result.rendered);
      setPreviewErrors(result.errors);
      setPreviewVisible(true);
    } catch {
      setPreviewErrors(["Failed to render preview"]);
      setPreviewVisible(true);
    }
  }

  if (configQuery.isLoading || eventsQuery.isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Notification Templates</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-[200px] w-full" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!templateTypes.length) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileCode2 className="h-5 w-5" />
          Notification Templates
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Template type selector */}
        <div className="flex flex-wrap gap-1.5">
          {templateTypes.map((t) => (
            <button
              key={t.value}
              onClick={() => switchType(t.value)}
              className={cn(
                "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                t.value === selectedTemplate
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-background hover:bg-muted",
              )}
            >
              {t.label}
              {currentTemplates()[t.value] && (
                <Pencil className="ml-1 inline h-3 w-3 text-primary/60" />
              )}
            </button>
          ))}
        </div>

        {/* Status badge */}
        <div className="flex items-center gap-2">
          <Badge variant={isCustomTemplate ? "default" : "secondary"}>
            {isCustomTemplate ? "Custom" : "Default"}
          </Badge>
          {hasUnsavedChanges && (
            <Badge variant="warning" className="text-amber-600 border-amber-300">
              Unsaved changes
            </Badge>
          )}
        </div>

        {/* Editor textarea */}
        <Textarea
          value={templateContent}
          onChange={(e) => {
            setTemplateContent(e.target.value);
            setHasUnsavedChanges(e.target.value !== serverStateRef.current);
          }}
          className="h-[300px] font-mono text-xs leading-relaxed resize-y"
          placeholder="Enter your Jinja2 notification template..."
        />

        {/* Actions */}
        <div className="flex flex-wrap items-center gap-2">
          <AppButton
            icon={<Save />}
            label="Save"
            variant="primary"
            disabled={!hasUnsavedChanges || saveMutation.isPending}
            loading={saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            Save
          </AppButton>
          <AppButton
            icon={<Eye />}
            label="Preview"
            variant="outline"
            onClick={onPreview}
          >
            Preview
          </AppButton>
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <AppButton
                icon={<RotateCcw />}
                label="Reset to Default"
                variant="ghost"
                disabled={!isCustomTemplate}
              >
                Reset to Default
              </AppButton>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Reset template?</AlertDialogTitle>
                <AlertDialogDescription>
                  This will revert the &ldquo;{selectedLabel}&rdquo; template back to the
                  built-in default. Any customizations will be lost.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction onClick={resetToDefault}>Reset</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>

        {/* Preview output */}
        {previewVisible && previewResult !== null && (
          <TemplatePreview result={previewResult} errors={previewErrors} />
        )}

        {/* Variables reference */}
        <Collapsible open={variablesOpen} onOpenChange={setVariablesOpen}>
          <CollapsibleTrigger className="flex items-center gap-2 text-sm font-medium hover:text-primary transition-colors">
            <ChevronRight
              className={cn("h-4 w-4 transition-transform", variablesOpen && "rotate-90")}
            />
            <Variable className="h-4 w-4" />
            Template Variables
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-3">
            <TemplateVariables eventType={selectedTemplate} />
          </CollapsibleContent>
        </Collapsible>

        {/* Discard dialog */}
        <AlertDialog open={discardDialogOpen} onOpenChange={setDiscardDialogOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
              <AlertDialogDescription>
                You have unsaved changes to the current template. Switching will discard them.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel onClick={() => setPendingSwitchType(null)}>
                Cancel
              </AlertDialogCancel>
              <AlertDialogAction onClick={confirmDiscard}>Discard</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  );
}
