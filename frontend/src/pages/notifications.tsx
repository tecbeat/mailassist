import { useState, useEffect, useCallback, useRef } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  Bell,
  ChevronRight,
  Plus,
  Trash2,
  Send,
  Eye,
  EyeOff,
  Pencil,
  Save,
  RotateCcw,

  Variable,
  FileCode2,
  AlertCircle,
  Check,
} from "lucide-react";
import { z } from "zod/v4";

import {
  useGetConfigApiNotificationsConfigGet,
  useUpdateConfigApiNotificationsConfigPut,
  useTestNotificationApiNotificationsTestPost,
  usePreviewNotificationApiNotificationsPreviewPost,
  useListVariablesApiNotificationsVariablesGet,
  getGetConfigApiNotificationsConfigGetQueryKey,
  getDefaultTemplateApiNotificationsTemplatesDefaultEventTypeGet,
  addUrlApiNotificationsConfigUrlsPost,
  removeUrlApiNotificationsConfigUrlsIndexDelete,
} from "@/services/api/notifications/notifications";
import { useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import {
  PluginSettingsDialog,
  PluginSettingsButton,
} from "@/components/plugin-settings-dialog";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import type {
  NotificationConfigResponse,
  NotifyOnConfig,
  TemplateVariable,
} from "@/types/api";
import { cn, unwrapResponse } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NotificationConfig {
  apprise_urls: string[];
  notify_on: NotifyOnConfig;
  templates: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NOTIFY_EVENT_LABELS: Record<keyof NotifyOnConfig, string> = {
  reply_needed: "Reply Needed",
  spam_detected: "Spam Detected",
  coupon_found: "Coupon Found",
  calendar_event_created: "Calendar Event Created",
  rule_executed: "Rule Executed",
  newsletter_detected: "Newsletter Detected",
  email_summary: "Email Summary",
  ai_error: "AI Error",
  contact_assigned: "Contact Assigned",
  approval_needed: "Approval Needed",
};

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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function NotificationsPage() {
  usePageTitle("Notifications");
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selectedTemplate, setSelectedTemplate] = useState(
    TEMPLATE_TYPES[0]!.value,
  );
  const [templateContent, setTemplateContent] = useState("");
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [testingUrl, setTestingUrl] = useState<string | null>(null);
  const [variablesOpen, setVariablesOpen] = useState(false);

  // Unsaved-changes guard
  const [pendingSwitchType, setPendingSwitchType] = useState<string | null>(null);
  const [discardDialogOpen, setDiscardDialogOpen] = useState(false);
  const [showUrls, setShowUrls] = useState(false);

  // Server state ref to prevent background refetches from overwriting edits
  const serverStateRef = useRef<string | null>(null);

  const configQuery = useGetConfigApiNotificationsConfigGet();
  const config = unwrapResponse<NotificationConfigResponse>(configQuery.data);

  const updateMutation = useUpdateConfigApiNotificationsConfigPut();
  const testMutation = useTestNotificationApiNotificationsTestPost();
  const previewMutation = usePreviewNotificationApiNotificationsPreviewPost();

  const [previewResult, setPreviewResult] = useState<string | null>(null);
  const [previewErrors, setPreviewErrors] = useState<string[]>([]);

  const variablesQuery = useListVariablesApiNotificationsVariablesGet();
  const variables = unwrapResponse<TemplateVariable[]>(variablesQuery.data);

  // --- Load template content when config loads or type changes ---
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
      getDefaultTemplateApiNotificationsTemplatesDefaultEventTypeGet(selectedTemplate, { signal: controller.signal })
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

  // --- Track unsaved changes ---
  const handleContentChange = useCallback(
    (value: string) => {
      setTemplateContent(value);
      setPreviewVisible(false);
      setPreviewResult(null);
      if (serverStateRef.current !== null) {
        setHasUnsavedChanges(value !== serverStateRef.current);
      }
    },
    [],
  );

  // --- Sidebar navigation with unsaved-changes guard ---
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

  // --- Helpers ---
  function currentUrls(): string[] {
    return config?.apprise_urls ?? [];
  }

  function currentNotifyOn(): NotifyOnConfig {
    return (config?.notify_on ?? {}) as NotifyOnConfig;
  }

  function currentTemplates(): Record<string, string> {
    return (config?.templates ?? {}) as Record<string, string>;
  }

  // Check if current template is custom (differs from default)
  const isCustomTemplate = !!currentTemplates()[selectedTemplate];

  // --- Save handler ---
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
        description: `Template for ${TEMPLATE_TYPES.find((t) => t.value === selectedTemplate)?.label ?? selectedTemplate} updated successfully.`,
      });
    } catch {
      toast({ title: "Failed to save template", description: "An error occurred while saving the template. Please try again.", variant: "destructive" });
    }
  }

  // --- Reset to default handler ---
  async function onResetTemplate() {
    try {
      // Remove the custom template entry
      const templates = { ...currentTemplates() };
      delete templates[selectedTemplate];
      await updateMutation.mutateAsync({
        data: {
          notify_on: currentNotifyOn(),
          templates,
        },
      });
      queryClient.invalidateQueries({
        queryKey: getGetConfigApiNotificationsConfigGetQueryKey(),
      });
      // Fetch the default template from disk
      const res = await getDefaultTemplateApiNotificationsTemplatesDefaultEventTypeGet(selectedTemplate);
      const defaultResult = unwrapResponse<{ template: string }>(res);
      const tmpl = defaultResult?.template ?? "";
      serverStateRef.current = tmpl;
      setTemplateContent(tmpl);
      setHasUnsavedChanges(false);
      setPreviewVisible(false);
      setPreviewResult(null);
      toast({
        title: "Template reset",
        description: `Template for ${TEMPLATE_TYPES.find((t) => t.value === selectedTemplate)?.label ?? selectedTemplate} reset to default.`,
      });
    } catch {
      toast({ title: "Failed to reset template", description: "Could not restore the default template. Please try again.", variant: "destructive" });
    }
  }

  // --- Preview handler (toggle) ---
  async function onPreviewTemplate() {
    if (previewVisible) {
      setPreviewVisible(false);
      return;
    }
    try {
      const res = await previewMutation.mutateAsync({
        data: {
          template: templateContent,
          event_type: selectedTemplate,
        },
      });
      const result = unwrapResponse<{ rendered: string; errors?: string[] }>(res);
      setPreviewResult(result?.rendered ?? "");
      setPreviewErrors(result?.errors ?? []);
      setPreviewVisible(true);
    } catch {
      toast({ title: "Preview failed", description: "Could not render the template preview.", variant: "destructive" });
    }
  }

  // --- Settings dialog handlers ---
  async function saveConfig(patch: Partial<NotificationConfig>) {
    try {
      await updateMutation.mutateAsync({
        data: {
          notify_on: patch.notify_on ?? currentNotifyOn(),
          templates: patch.templates ?? currentTemplates(),
        },
      });
      queryClient.invalidateQueries({
        queryKey: getGetConfigApiNotificationsConfigGetQueryKey(),
      });
      toast({ title: "Configuration saved", description: "Notification settings have been updated." });
    } catch {
      toast({
        title: "Failed to save configuration",
        description: "Could not save the notification configuration. Please try again.",
        variant: "destructive",
      });
    }
  }

  const webhookUrlSchema = z.string().min(1, "URL is required").url("Must be a valid URL");
  const [urlError, setUrlError] = useState<string | null>(null);
  const [isAddingUrl, setIsAddingUrl] = useState(false);
  const [removingUrlIndex, setRemovingUrlIndex] = useState<number | null>(null);

  async function onAddUrl(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const formData = new FormData(form);
    const url = formData.get("url") as string;
    const parsed = webhookUrlSchema.safeParse(url?.trim());
    if (!parsed.success) {
      setUrlError(parsed.error.issues[0]?.message ?? "Invalid URL");
      return;
    }
    setUrlError(null);
    setIsAddingUrl(true);
    try {
      await addUrlApiNotificationsConfigUrlsPost({ url: parsed.data });
      queryClient.invalidateQueries({
        queryKey: getGetConfigApiNotificationsConfigGetQueryKey(),
      });
      toast({ title: "URL added", description: "The webhook URL has been added to the notification list." });
      form.reset();
    } catch {
      toast({ title: "Failed to add URL", description: "Could not add the webhook URL. Please try again.", variant: "destructive" });
    } finally {
      setIsAddingUrl(false);
    }
  }

  async function onRemoveUrl(index: number) {
    setRemovingUrlIndex(index);
    try {
      await removeUrlApiNotificationsConfigUrlsIndexDelete(index);
      queryClient.invalidateQueries({
        queryKey: getGetConfigApiNotificationsConfigGetQueryKey(),
      });
      toast({ title: "URL removed", description: "The webhook URL has been removed." });
    } catch {
      toast({ title: "Failed to remove URL", description: "Could not remove the webhook URL. Please try again.", variant: "destructive" });
    } finally {
      setRemovingUrlIndex(null);
    }
  }

  // Clean up debounce timer on unmount
  useEffect(() => {
    return () => {
      if (toggleTimerRef.current) clearTimeout(toggleTimerRef.current);
    };
  }, []);

  // --- Debounced notification event toggles ---
  const pendingTogglesRef = useRef<Partial<NotifyOnConfig>>({});
  const toggleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function onToggleEvent(key: keyof NotifyOnConfig, value: boolean) {
    pendingTogglesRef.current = { ...pendingTogglesRef.current, [key]: value };
    if (toggleTimerRef.current) clearTimeout(toggleTimerRef.current);
    toggleTimerRef.current = setTimeout(() => {
      const merged = { ...currentNotifyOn(), ...pendingTogglesRef.current };
      pendingTogglesRef.current = {};
      toggleTimerRef.current = null;
      saveConfig({ notify_on: merged });
    }, 500);
  }

  async function onTestUrl(url: string) {
    setTestingUrl(url);
    try {
      const res = await testMutation.mutateAsync({
        data: { message: "Test notification from mailassist" },
      });
      const result = unwrapResponse<{ success: boolean; message: string }>(res);
      if (result?.success) {
        toast({ title: "Test sent", description: result.message });
      } else {
        toast({
          title: "Test failed",
          description: result?.message ?? "Unknown error",
          variant: "destructive",
        });
      }
    } catch {
      toast({ title: "Test failed", description: "Could not reach the webhook endpoint.", variant: "destructive" });
    } finally {
      setTestingUrl(null);
    }
  }

  async function onSendTestNotification() {
    try {
      const res = await testMutation.mutateAsync({
        data: { message: "Test notification from mailassist" },
      });
      const result = unwrapResponse<{ success: boolean; message: string }>(res);
      if (result?.success) {
        toast({ title: "Test notification sent", description: result.message });
      } else {
        toast({
          title: "Test failed",
          description: result?.message,
          variant: "destructive",
        });
      }
    } catch {
      toast({ title: "Failed to send test notification", description: "An error occurred while sending the test. Please check your configuration.", variant: "destructive" });
    }
  }

  // --- Selected type label ---
  const selectedLabel = TEMPLATE_TYPES.find((t) => t.value === selectedTemplate)?.label ?? selectedTemplate;

  if (configQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Notifications"
          description="Configure notification channels and event triggers."
          actions={
            <div className="flex items-center gap-2">
              <PluginSettingsButton onClick={() => setSettingsOpen(true)} />
              <AppButton icon={<Send />} label="Send Test" variant="primary" disabled>Send Test</AppButton>
            </div>
          }
        />
        <QueryError
          message="Failed to load notification settings."
          onRetry={() => configQuery.refetch()}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notifications"
        description="Configure notification channels and event triggers."
        actions={
          <div className="flex items-center gap-2">
            <PluginSettingsButton onClick={() => setSettingsOpen(true)} />
            <AppButton
              icon={<Send />}
              label="Send Test"
              variant="primary"
              loading={testMutation.isPending}
              disabled={testMutation.isPending || !currentUrls().length}
              onClick={onSendTestNotification}
            >Send Test</AppButton>
          </div>
        }
      />

      {/* Discard unsaved changes dialog */}
      <AlertDialog open={discardDialogOpen} onOpenChange={setDiscardDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard unsaved changes?</AlertDialogTitle>
            <AlertDialogDescription>
              You have unsaved changes to the{" "}
              <span className="font-medium">{selectedLabel}</span>{" "}
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
        {/* Left sidebar - template types                                    */}
        {/* ---------------------------------------------------------------- */}
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
                        {hasCustom && (
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
          {/* Header */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <h2 className="text-lg font-semibold">{selectedLabel}</h2>
                {isCustomTemplate && (
                  <Badge variant="secondary">Customized</Badge>
                )}
                {hasUnsavedChanges && (
                  <Badge variant="destructive">
                    Unsaved
                  </Badge>
                )}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                Customize the Jinja2 notification template for this event type.
              </p>
            </div>
          </div>

          {/* Editor area */}
          {configQuery.isLoading ? (
            <div className="space-y-3">
              <Skeleton className="h-5 w-32" />
              <Skeleton className="h-64 w-full" />
            </div>
          ) : (
            <div className="space-y-4">
              {/* Template content / Preview inline */}
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  {previewVisible ? "Preview (with sample data)" : "Template Content"}
                </label>
                {previewVisible && previewResult !== null ? (
                  <div className="relative">
                    {previewErrors.length > 0 && (
                      <div role="alert" className="absolute right-2 top-2 z-10 flex items-start gap-2 rounded-md border border-destructive bg-destructive/5 p-2 backdrop-blur-sm">
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                        <div className="space-y-1">
                          <p className="text-xs font-medium text-destructive">
                            Template Errors
                          </p>
                          {previewErrors.map((err, i) => (
                            <p key={i} className="text-xs text-destructive/80">
                              {err}
                            </p>
                          ))}
                        </div>
                      </div>
                    )}
                    {previewErrors.length === 0 && (
                      <div className="absolute right-[18px] top-2 z-10 flex items-center gap-1.5 rounded-md border border-green-200 bg-green-50/90 px-2 py-1 text-xs text-green-600 backdrop-blur-sm dark:border-green-800 dark:bg-green-950/90">
                        <Check className="h-3.5 w-3.5" />
                        Rendered successfully
                      </div>
                    )}
                    <pre
                      role="region"
                      aria-label="Template preview"
                      className="h-[300px] overflow-auto whitespace-pre-wrap break-words rounded-md border border-input bg-muted px-3 py-2 pr-4 md:pr-48 font-mono text-xs leading-relaxed"
                    >
                      {previewResult}
                    </pre>
                  </div>
                ) : (
                  <Textarea
                    value={templateContent}
                    onChange={(e) => handleContentChange(e.target.value)}
                    className="h-[300px] resize-none font-mono text-xs leading-relaxed"
                    placeholder="Enter your Jinja2 template here..."
                  />
                )}
              </div>

              {/* Available variables header + action buttons in one row */}
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

                  {/* Buttons pushed to the right */}
                  <div className="ml-auto flex flex-wrap gap-2">
                    {isCustomTemplate && (
                          <AlertDialog>
                            <AlertDialogTrigger asChild>
                              <AppButton icon={<RotateCcw />} label="Reset to Default" disabled={updateMutation.isPending}>
                                Reset to Default
                              </AppButton>
                            </AlertDialogTrigger>
                            <AlertDialogContent>
                              <AlertDialogHeader>
                                <AlertDialogTitle>Reset to default template?</AlertDialogTitle>
                                <AlertDialogDescription>
                                  This will discard your custom template for{" "}
                                  <span className="font-medium">{selectedLabel}</span> and
                                  restore the built-in default. This action cannot be undone.
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
                    >{previewMutation.isPending ? "Rendering..." : previewVisible ? "Edit" : "Preview"}</AppButton>

                    <AppButton
                      icon={<Save />}
                      label="Save template"
                      variant="primary"
                     
                      loading={updateMutation.isPending}
                      disabled={updateMutation.isPending || !hasUnsavedChanges}
                      onClick={onSaveTemplate}
                    >{updateMutation.isPending ? "Saving..." : "Save"}</AppButton>
                  </div>
                </div>

                {/* 3-column grid of variable cards (no wrapping Card) */}
                <CollapsibleContent>
                  <div className="mt-3">
                    {variablesQuery.isError ? (
                      <p className="text-sm text-destructive">Failed to load variables.</p>
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
        </div>
      </div>

      {/* Settings Dialog -- Apprise URLs + Event Toggles */}
      <PluginSettingsDialog
        open={settingsOpen}
        onOpenChange={setSettingsOpen}
        title="Notification Settings"
        description="Configure notification channels and choose which events trigger notifications."
      >
        <div className="space-y-6">
          {/* Apprise URLs */}
          <div className="space-y-3">
            <div>
              <h4 className="text-sm font-medium flex items-center gap-2">
                <Bell className="h-4 w-4" />
                Notification URLs
              </h4>
              <p className="text-sm text-muted-foreground mt-1">
                Add Apprise-compatible notification URLs (max 10). Each URL
                represents a notification channel (e.g. Telegram, Discord, email).
              </p>
            </div>

            {currentUrls().length === 0 && (
              <p className="text-sm text-muted-foreground">
                No notification URLs configured yet.
              </p>
            )}
            {currentUrls().length > 0 && (
              <div className="flex justify-end">
                <AppButton
                  icon={showUrls ? <EyeOff /> : <Eye />}
                  label={showUrls ? "Hide URLs" : "Reveal URLs"}
                  variant="ghost"
                  onClick={() => setShowUrls((v) => !v)}
                >
                  {showUrls ? "Hide" : "Reveal"}
                </AppButton>
              </div>
            )}
            {currentUrls().map((url, index) => (
              <div key={index} className="flex items-center gap-2">
                <Input
                  type={showUrls ? "text" : "password"}
                  value={url}
                  readOnly
                  className="flex-1 font-mono text-sm"
                />
                <AppButton
                  icon={<Send />}
                  label="Test notification URL"
                  variant="ghost"
                  loading={testingUrl === url}
                  onClick={() => onTestUrl(url)}
                  disabled={testingUrl === url}
                />
                <AppButton
                  icon={<Trash2 />}
                  label="Remove notification URL"
                  variant="ghost"
                  color="destructive"
                  onClick={() => onRemoveUrl(index)}
                  disabled={updateMutation.isPending || removingUrlIndex !== null}
                  loading={removingUrlIndex === index}
                />
              </div>
            ))}

            {currentUrls().length < 10 && (
              <>
                <Separator />
                <form
                  onSubmit={onAddUrl}
                  className="flex items-start gap-2"
                >
                  <div className="flex-1">
                    <Input
                      name="url"
                      placeholder="apprise://service/token..."
                      className="font-mono text-sm"
                      onChange={() => setUrlError(null)}
                    />
                    {urlError && <p className="mt-1 text-xs text-destructive">{urlError}</p>}
                  </div>
                  <AppButton icon={<Plus />} label="Add URL" type="submit" variant="primary" disabled={isAddingUrl} loading={isAddingUrl}>Add</AppButton>
                </form>
              </>
            )}
          </div>

          <Separator />

          {/* Notification Event Toggles */}
          <div className="space-y-3">
            <div>
              <h4 className="text-sm font-medium">Notification Events</h4>
              <p className="text-sm text-muted-foreground mt-1">
                Choose which events trigger a notification.
              </p>
            </div>

            {(
              Object.entries(NOTIFY_EVENT_LABELS) as [
                keyof NotifyOnConfig,
                string,
              ][]
            ).map(([key, label]) => (
              <div key={key} className="flex items-center justify-between">
                <Label htmlFor={`event-${key}`} className="cursor-pointer">
                  {label}
                </Label>
                <Switch
                  id={`event-${key}`}
                  checked={!!currentNotifyOn()[key]}
                  onCheckedChange={(checked) => onToggleEvent(key, checked)}
                  disabled={updateMutation.isPending}
                />
              </div>
            ))}
          </div>
        </div>
      </PluginSettingsDialog>
    </div>
  );
}
