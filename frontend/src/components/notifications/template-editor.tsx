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
import { useQueryClient } from "@tanstack/react-query";

import {
  useGetConfigApiNotificationsConfigGet,
  useUpdateConfigApiNotificationsConfigPut,
  usePreviewNotificationApiNotificationsPreviewPost,
  getGetConfigApiNotificationsConfigGetQueryKey,
  getDefaultTemplateApiNotificationsTemplatesDefaultEventTypeGet,
} from "@/services/api/notifications/notifications";
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
import { cn, unwrapResponse } from "@/lib/utils";
import type { NotificationConfigResponse, NotifyOnConfig } from "@/types/api";

import { TemplatePreview } from "./template-preview";
import { TemplateVariables } from "./template-variables";

const TEMPLATE_TYPES = [
  { value: "reply_needed", label: "Reply Needed" },
  { value: "spam_detected", label: "Spam Detected" },
  { value: "coupon_found", label: "Coupon Found" },
  { value: "calendar_event_created", label: "Calendar Event Created" },
  { value: "rule_executed", label: "Rule Executed" },
  { value: "newsletter_detected", label: "Newsletter Detected" },
  { value: "email_summary", label: "Email Summary" },
  { value: "ai_error", label: "AI Error" },
  { value: "contact_assigned", label: "Contact Assigned" },
  { value: "approval_needed", label: "Approval Needed" },
];

/**
 * Full template editing experience: type sidebar, editor textarea, preview,
 * save/reset/preview actions, and the variables reference panel.
 *
 * Queries config from the React Query cache (shared with the parent page).
 */
export function TemplateEditor() {
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const configQuery = useGetConfigApiNotificationsConfigGet();
  const config = unwrapResponse<NotificationConfigResponse>(configQuery.data);

  const updateMutation = useUpdateConfigApiNotificationsConfigPut();
  const previewMutation = usePreviewNotificationApiNotificationsPreviewPost();

  const [selectedTemplate, setSelectedTemplate] = useState(TEMPLATE_TYPES[0]!.value);
  const [templateContent, setTemplateContent] = useState("");
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [previewResult, setPreviewResult] = useState<string | null>(null);
  const [previewErrors, setPreviewErrors] = useState<string[]>([]);
  const [variablesOpen, setVariablesOpen] = useState(false);
  const [pendingSwitchType, setPendingSwitchType] = useState<string | null>(null);
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);

  // Prevents background refetches from overwriting in-progress edits.
  const serverStateRef = useRef<string | null>(null);

  function currentTemplates(): Record<string, string> {
    return (config?.templates ?? {}) as Record<string, string>;
  }

  function currentNotifyOn(): NotifyOnConfig {
    return (config?.notify_on ?? {}) as NotifyOnConfig;
  }

  const isCustomTemplate = !!currentTemplates()[selectedTemplate];
  const selectedLabel =
    TEMPLATE_TYPES.find((t) => t.value === selectedTemplate)?.label ?? selectedTemplate;

  // Load template content when config loads or the selected type changes.
  useEffect(() => {
    if (!config) return;
    const custom = (config.templates as Record<string, string>)?.[selectedTemplate] ?? "";
    if (custom) {
      serverStateRef.current = custom;
      setTemplateContent(custom);
      setHasUnsavedChanges(false);
      setPreviewVisible(false);
      setPreviewResult(null);
    } else {
      const controller = new AbortController();
      getDefaultTemplateApiNotificationsTemplatesDefaultEventTypeGet(selectedTemplate, {
        signal: controller.signal,
      })
        .then((res) => {
          if (controller.signal.aborted) return;
          const result = unwrapResponse<{ template: string }>(res);
          const tmpl = result?.template ?? "";
          serverStateRef.current = tmpl;
          setTemplateContent(tmpl);
          setHasUnsavedChanges(false);
          setPreviewVisible(false);
          setPreviewResult(null);
        })
        .catch(() => {
          if (controller.signal.aborted) return;
          serverStateRef.current = "";
          setTemplateContent("");
          setHasUnsavedChanges(false);
        });
      return () => controller.abort();
    }
  }, [config, selectedTemplate]);

  const handleContentChange = useCallback((value: string) => {
    setTemplateContent(value);
    setPreviewVisible(false);
    setPreviewResult(null);
    if (serverStateRef.current !== null) {
      setHasUnsavedChanges(value !== serverStateRef.current);
    }
  }, []);

  const handleSelectType = useCallback(
    (type: string) => {
      if (type === selectedTemplate) return;
      if (hasUnsavedChanges) {
        setPendingSwitchType(type);
        setDiscardDialogOpen(true);
      } else {
        serverStateRef.current = null;
        setSelectedTemplate(type);
      }
    },
    [selectedTemplate, hasUnsavedChanges],
  );

  const handleDiscardAndSwitch = useCallback(() => {
    if (pendingSwitchType) {
      serverStateRef.current = null;
      setSelectedTemplate(pendingSwitchType);
      setHasUnsavedChanges(false);
      setPendingSwitchType(null);
    }
    setDiscardDialogOpen(false);
  }, [pendingSwitchType]);

  const handleCancelSwitch = useCallback(() => {
    setPendingSwitchType(null);
    setDiscardDialogOpen(false);
  }, []);

  async function onSaveTemplate() {
    try {
      await updateMutation.mutateAsync({
        data: {
          notify_on: currentNotifyOn(),
          templates: { ...currentTemplates(), [selectedTemplate]: templateContent },
        },
      });
      serverStateRef.current = templateContent;
      setHasUnsavedChanges(false);
      queryClient.invalidateQueries({
        queryKey: getGetConfigApiNotificationsConfigGetQueryKey(),
      });
      toast({
        title: "Template saved",
        description: `Template for ${selectedLabel} updated successfully.`,
      });
    } catch {
      toast({
        title: "Failed to save template",
        description: "An error occurred while saving the template. Please try again.",
        variant: "destructive",
      });
    }
  }

  async function onResetTemplate() {
    try {
      const templates = { ...currentTemplates() };
      delete templates[selectedTemplate];
      await updateMutation.mutateAsync({
        data: { notify_on: currentNotifyOn(), templates },
      });
      queryClient.invalidateQueries({
        queryKey: getGetConfigApiNotificationsConfigGetQueryKey(),
      });
      const res = await getDefaultTemplateApiNotificationsTemplatesDefaultEventTypeGet(
        selectedTemplate,
      );
      const defaultResult = unwrapResponse<{ template: string }>(res);
      const tmpl = defaultResult?.template ?? "";
      serverStateRef.current = tmpl;
      setTemplateContent(tmpl);
      setHasUnsavedChanges(false);
      setPreviewVisible(false);
      setPreviewResult(null);
      toast({
        title: "Template reset",
        description: `Template for ${selectedLabel} reset to default.`,
      });
    } catch {
      toast({
        title: "Failed to reset template",
        description: "Could not restore the default template. Please try again.",
        variant: "destructive",
      });
    }
  }

  async function onPreviewTemplate() {
    if (previewVisible) {
      setPreviewVisible(false);
      return;
    }
    try {
      const res = await previewMutation.mutateAsync({
        data: { template: templateContent, event_type: selectedTemplate },
      });
      const result = unwrapResponse<{ rendered: string; errors?: string[] }>(res);
      setPreviewResult(result?.rendered ?? "");
      setPreviewErrors(result?.errors ?? []);
      setPreviewVisible(true);
    } catch {
      toast({
        title: "Preview failed",
        description: "Could not render the template preview.",
        variant: "destructive",
      });
    }
  }

  return (
    <>
      {/* Discard unsaved changes dialog */}
      <AlertDialog open={discardDialogOpen} onOpenChange={setDiscardDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              You have unsaved changes to the{" "}
              <span className="font-medium">{selectedLabel}</span> template. Switching will
              discard them.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancelSwitch}>Stay</AlertDialogCancel>
            <AlertDialogAction onClick={handleDiscardAndSwitch}>Discard</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <div className="flex flex-col gap-6 lg:flex-row">
        {/* Sidebar - template types */}
        <div className="w-full shrink-0 lg:w-64">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium">Templates</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {configQuery.isLoading ? (
                <div className="space-y-2 px-4 pb-4">
                  {Array.from({ length: 6 }).map((_, i) => (
                    <Skeleton key={i} className="h-8 w-full" />
                  ))}
                </div>
              ) : (
                <nav className="flex flex-col">
                  {TEMPLATE_TYPES.map((tmpl) => {
                    const isSelected = selectedTemplate === tmpl.value;
                    const hasCustom = !!currentTemplates()[tmpl.value];
                    return (
                      <button
                        key={tmpl.value}
                        onClick={() => handleSelectType(tmpl.value)}
                        aria-current={isSelected ? "page" : undefined}
                        className={cn(
                          "flex items-center gap-2 px-4 py-2.5 text-left text-sm transition-colors hover:bg-accent",
                          isSelected && "bg-accent font-medium",
                        )}
                      >
                        <FileCode2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="flex-1 truncate">{tmpl.label}</span>
                        {hasCustom && <Badge variant="secondary">Custom</Badge>}
                      </button>
                    );
                  })}
                </nav>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right panel - editor */}
        <div className="min-w-0 flex-1 space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold">{selectedLabel}</h2>
                {isCustomTemplate && <Badge variant="secondary">Customized</Badge>}
                {hasUnsavedChanges && <Badge variant="destructive">Unsaved</Badge>}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                Customize the Jinja2 notification template for this event type.
              </p>
            </div>
          </div>

          {configQuery.isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-64 w-full" />
            </div>
          ) : (
            <div className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  {previewVisible ? "Preview (with sample data)" : "Template Content"}
                </label>
                {previewVisible && previewResult !== null ? (
                  <TemplatePreview result={previewResult} errors={previewErrors} />
                ) : (
                  <Textarea
                    value={templateContent}
                    onChange={(e) => handleContentChange(e.target.value)}
                    className="h-[300px] resize-none font-mono text-xs leading-relaxed"
                    placeholder="Enter your Jinja2 template here..."
                  />
                )}
              </div>

              <Collapsible open={variablesOpen} onOpenChange={setVariablesOpen}>
                <div className="flex flex-wrap items-center gap-2">
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

                  <div className="ml-auto flex flex-wrap gap-2">
                    {isCustomTemplate && (
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <AppButton
                            icon={<RotateCcw />}
                            label="Reset to Default"
                            disabled={updateMutation.isPending}
                          >
                            Reset to Default
                          </AppButton>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Reset to default template?</AlertDialogTitle>
                            <AlertDialogDescription>
                              This will discard your custom template for{" "}
                              <span className="font-medium">{selectedLabel}</span> and restore
                              the built-in default. This action cannot be undone.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction onClick={() => onResetTemplate()}>
                              Reset
                            </AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    )}

                    <AppButton
                      icon={previewVisible ? <Pencil /> : <Eye />}
                      label={previewVisible ? "Edit" : "Preview"}
                      loading={previewMutation.isPending}
                      disabled={previewMutation.isPending || !templateContent.trim()}
                      onClick={onPreviewTemplate}
                    >
                      {previewMutation.isPending
                        ? "Rendering..."
                        : previewVisible
                          ? "Edit"
                          : "Preview"}
                    </AppButton>

                    <AppButton
                      icon={<Save />}
                      label="Save template"
                      variant="primary"
                      loading={updateMutation.isPending}
                      disabled={updateMutation.isPending || !hasUnsavedChanges}
                      onClick={onSaveTemplate}
                    >
                      {updateMutation.isPending ? "Saving..." : "Save"}
                    </AppButton>
                  </div>
                </div>

                <CollapsibleContent>
                  <div className="mt-3">
                    <TemplateVariables />
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
