import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpDown,
  ChevronUp,
  ChevronDown,
  Puzzle,
  FlaskConical,
  Loader2,
  CheckCircle2,
  XCircle,
  SkipForward,
  Coins,
} from "lucide-react";

import {
  useGetSettingsApiSettingsGet,
  useUpdateSettingsApiSettingsPut,
  getGetSettingsApiSettingsGetQueryKey,
} from "@/services/api/settings/settings";
import { useListPluginsApiAiProvidersPluginsGet } from "@/services/api/ai-providers/ai-providers";
import type { SettingsResponse, PluginInfo } from "@/types/api";
import { ApprovalMode } from "@/types/api";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import { AppButton } from "@/components/app-button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  TooltipProvider,
} from "@/components/ui/tooltip";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";

import { cn, unwrapResponse } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const APPROVAL_MODE_OPTIONS = [
  { value: "auto", label: "Auto" },
  { value: "approval", label: "Approval" },
  { value: "disabled", label: "Off" },
];

/** Return the available mode options for a plugin. */
function getModeOptions(plugin: PluginInfo) {
  if (plugin.supports_approval === false) {
    return APPROVAL_MODE_OPTIONS.filter((o) => o.value !== "approval");
  }
  return APPROVAL_MODE_OPTIONS;
}

// ---------------------------------------------------------------------------
// Pipeline test types (matches backend SSE events)
// ---------------------------------------------------------------------------

interface PipelineTestRequest {
  sender: string;
  sender_name: string;
  recipient: string;
  subject: string;
  body: string;
  date: string;
  has_attachments: boolean;
  is_reply: boolean;
  is_forwarded: boolean;
}

interface PluginTestResult {
  plugin_name: string;
  display_name: string;
  success: boolean;
  actions: string[];
  ai_response: Record<string, unknown> | null;
  tokens_used: number;
  error: string | null;
  skipped: boolean;
  skip_reason: string | null;
}

/** Plugin info from the init SSE event. */
interface PipelinePluginInfo {
  name: string;
  display_name: string;
}

/** Current step state for the live progress display. */
type StepStatus = "pending" | "running" | "done" | "skipped" | "error";

interface StepState {
  plugin: PipelinePluginInfo;
  status: StepStatus;
  result?: PluginTestResult;
}

const DEFAULT_TEST_DATA: PipelineTestRequest = {
  sender: "newsletter@example.com",
  sender_name: "Example Newsletter",
  recipient: "me@example.com",
  subject: "Your Weekly Update - Special Offers Inside!",
  body: "Hi there,\n\nHere's your weekly newsletter with the latest updates and special offers.\n\nBest regards,\nThe Example Team",
  date: "",
  has_attachments: false,
  is_reply: false,
  is_forwarded: false,
};

// ---------------------------------------------------------------------------
// SSE stream helpers
// ---------------------------------------------------------------------------

/** Read CSRF token from cookie for POST request. */
function getCsrfToken(): string | undefined {
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrf_token="));
  return match?.split("=")[1];
}

/** Parse raw SSE text chunks into {event, data} pairs. */
function parseSSE(text: string): Array<{ event: string; data: string }> {
  const events: Array<{ event: string; data: string }> = [];
  // SSE events are separated by double newlines
  const blocks = text.split("\n\n").filter(Boolean);
  for (const block of blocks) {
    let event = "message";
    let data = "";
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) event = line.slice(7);
      else if (line.startsWith("data: ")) data = line.slice(6);
    }
    if (data) events.push({ event, data });
  }
  return events;
}

// ---------------------------------------------------------------------------
// Test Pipeline Dialog
// ---------------------------------------------------------------------------

function TestPipelineDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { toast } = useToast();
  const [formData, setFormData] = useState<PipelineTestRequest>({
    ...DEFAULT_TEST_DATA,
  });
  const [loading, setLoading] = useState(false);
  const [steps, setSteps] = useState<StepState[]>([]);
  const [totalTokens, setTotalTokens] = useState(0);
  const [pluginsExecuted, setPluginsExecuted] = useState(0);
  const [pipelineDone, setPipelineDone] = useState(false);
  const [pipelineError, setPipelineError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  function updateField<K extends keyof PipelineTestRequest>(
    key: K,
    value: PipelineTestRequest[K],
  ) {
    setFormData((prev) => ({ ...prev, [key]: value }));
  }

  function resetState() {
    setSteps([]);
    setTotalTokens(0);
    setPluginsExecuted(0);
    setPipelineDone(false);
    setPipelineError(null);
  }

  async function runTest() {
    setLoading(true);
    resetState();

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      const csrf = getCsrfToken();
      if (csrf) headers["X-CSRF-Token"] = csrf;

      const response = await fetch("/api/pipeline/test", {
        method: "POST",
        headers,
        credentials: "include",
        body: JSON.stringify(formData),
        signal: controller.signal,
      });

      if (response.status === 401) {
        window.location.href = "/auth/login";
        return;
      }

      if (!response.ok || !response.body) {
        throw new Error(`Request failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      // Timeout: abort if no data received for 60 seconds
      let timeoutId: ReturnType<typeof setTimeout> | null = null;
      const resetTimeout = () => {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => controller.abort(), 60_000);
      };
      resetTimeout();

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          resetTimeout();

          buffer += decoder.decode(value, { stream: true });

          // Process complete SSE events (separated by \n\n)
          const parts = buffer.split("\n\n");
          // Keep last incomplete chunk in buffer
          buffer = parts.pop() ?? "";

          for (const part of parts) {
            if (!part.trim()) continue;
            const events = parseSSE(part + "\n\n");
            for (const { event, data } of events) {
              try {
                const payload = JSON.parse(data);
                handleSSEEvent(event, payload);
              } catch {
                // Ignore malformed events
              }
            }
          }
        }

        // Process any remaining buffer
        if (buffer.trim()) {
          const events = parseSSE(buffer + "\n\n");
          for (const { event, data } of events) {
            try {
              const payload = JSON.parse(data);
              handleSSEEvent(event, payload);
            } catch {
              // Ignore
            }
          }
        }
      } finally {
        if (timeoutId) clearTimeout(timeoutId);
        reader.releaseLock();
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        toast({
          title: "Pipeline test failed",
          description: err instanceof Error ? err.message : "Unknown error",
          variant: "destructive",
        });
        setPipelineError(err instanceof Error ? err.message : "Unknown error");
      }
      // Mark any in-progress steps as errored so the UI doesn't show stale "running" state
      setSteps((prev) =>
        prev.map((s) =>
          s.status === "running" ? { ...s, status: "error" as StepStatus } : s,
        ),
      );
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }

  function handleSSEEvent(event: string, payload: Record<string, unknown>) {
    switch (event) {
      case "init": {
        const plugins = payload.plugins as PipelinePluginInfo[];
        setSteps(
          plugins.map((p) => ({ plugin: p, status: "pending" as StepStatus })),
        );
        break;
      }
      case "step": {
        const stepIdx = payload.step as number;
        setSteps((prev) =>
          prev.map((s, i) =>
            i === stepIdx ? { ...s, status: "running" } : s,
          ),
        );
        break;
      }
      case "skip": {
        const stepIdx = payload.step as number;
        const result = payload.result as PluginTestResult;
        setSteps((prev) =>
          prev.map((s, i) =>
            i === stepIdx ? { ...s, status: "skipped", result } : s,
          ),
        );
        break;
      }
      case "result": {
        const stepIdx = payload.step as number;
        const result = payload.result as PluginTestResult;
        setSteps((prev) =>
          prev.map((s, i) =>
            i === stepIdx
              ? {
                  ...s,
                  status: result.success ? "done" : "error",
                  result,
                }
              : s,
          ),
        );
        break;
      }
      case "done": {
        setPipelineDone(true);
        setPluginsExecuted(payload.plugins_executed as number);
        setTotalTokens(payload.total_tokens as number);
        break;
      }
      case "error": {
        setPipelineError(payload.error as string);
        setPipelineDone(true);
        break;
      }
    }
  }

  function handleClose(open: boolean) {
    if (!loading) {
      onOpenChange(open);
      if (!open) {
        resetState();
      }
    } else if (!open) {
      // Cancel running test
      abortRef.current?.abort();
    }
  }

  const hasResults = steps.length > 0;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FlaskConical className="h-5 w-5" />
            Test Pipeline
          </DialogTitle>
          <DialogDescription>
            Run a dry-run of the AI processing pipeline with sample email data.
            No actions will be persisted.
          </DialogDescription>
        </DialogHeader>

        {/* Form */}
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="test-sender">Sender Email</Label>
              <Input
                id="test-sender"
                value={formData.sender}
                onChange={(e) => updateField("sender", e.target.value)}
                placeholder="sender@example.com"
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="test-sender-name">Sender Name</Label>
              <Input
                id="test-sender-name"
                value={formData.sender_name}
                onChange={(e) => updateField("sender_name", e.target.value)}
                placeholder="John Doe"
                disabled={loading}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="test-recipient">Recipient</Label>
              <Input
                id="test-recipient"
                value={formData.recipient}
                onChange={(e) => updateField("recipient", e.target.value)}
                placeholder="me@example.com"
                disabled={loading}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="test-date">Date (optional)</Label>
              <Input
                id="test-date"
                type="datetime-local"
                value={formData.date}
                onChange={(e) => updateField("date", e.target.value)}
                disabled={loading}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="test-subject">Subject</Label>
            <Input
              id="test-subject"
              value={formData.subject}
              onChange={(e) => updateField("subject", e.target.value)}
              placeholder="Email subject line"
              disabled={loading}
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="test-body">Body</Label>
            <Textarea
              id="test-body"
              rows={4}
              value={formData.body}
              onChange={(e) => updateField("body", e.target.value)}
              placeholder="Email body text..."
              disabled={loading}
            />
          </div>

          <div className="flex items-center gap-6">
            <div className="flex items-center gap-2">
              <Switch
                id="test-attachments"
                checked={formData.has_attachments}
                onCheckedChange={(v) => updateField("has_attachments", v)}
                disabled={loading}
              />
              <Label htmlFor="test-attachments" className="text-sm">
                Has attachments
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="test-reply"
                checked={formData.is_reply}
                onCheckedChange={(v) => updateField("is_reply", v)}
                disabled={loading}
              />
              <Label htmlFor="test-reply" className="text-sm">
                Is reply
              </Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch
                id="test-forwarded"
                checked={formData.is_forwarded}
                onCheckedChange={(v) => updateField("is_forwarded", v)}
                disabled={loading}
              />
              <Label htmlFor="test-forwarded" className="text-sm">
                Is forwarded
              </Label>
            </div>
          </div>

          <AppButton
            icon={<FlaskConical />}
            label="Run Test"
            variant="primary"
            loading={loading}
            onClick={runTest}
            disabled={loading}
            className="w-full"
          >
            {loading ? "Running Pipeline..." : "Run Test"}
          </AppButton>
        </div>

        {/* Live progress + results */}
        {hasResults && (
          <div className="mt-4 space-y-3">
            {/* Header with summary (shown when done) */}
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-sm flex items-center gap-2">
                {loading ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                    Pipeline running...
                  </>
                ) : pipelineDone ? (
                  "Results"
                ) : (
                  "Pipeline"
                )}
              </h3>
              {pipelineDone && !pipelineError && (
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span>
                    {pluginsExecuted} plugin
                    {pluginsExecuted !== 1 ? "s" : ""} executed
                  </span>
                  <span className="flex items-center gap-1">
                    <Coins className="h-3 w-3" />
                    {totalTokens} tokens
                  </span>
                </div>
              )}
            </div>

            {pipelineError && (
              <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                {pipelineError}
              </div>
            )}

            {/* Step list */}
            <div className="divide-y divide-border rounded-md border">
              {steps.map((s, i) => (
                <div key={s.plugin.name} className="space-y-2 p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {/* Status icon */}
                      {s.status === "running" ? (
                        <Loader2 className="h-4 w-4 animate-spin text-primary" />
                      ) : s.status === "skipped" ? (
                        <SkipForward className="h-4 w-4 text-muted-foreground" />
                      ) : s.status === "done" ? (
                        <CheckCircle2 className="h-4 w-4 text-green-600" />
                      ) : s.status === "error" ? (
                        <XCircle className="h-4 w-4 text-destructive" />
                      ) : (
                        <div className="h-4 w-4 rounded-full border-2 border-muted-foreground/30" />
                      )}
                      <span
                        className={cn(
                          "text-sm font-medium",
                          s.status === "pending" && "text-muted-foreground",
                          s.status === "running" && "text-primary",
                        )}
                      >
                        {s.plugin.display_name}
                      </span>
                      {s.status === "running" && (
                        <Badge variant="default" className="animate-pulse">
                          Processing
                        </Badge>
                      )}
                      {s.status === "skipped" && (
                        <Badge variant="secondary">
                          Skipped
                        </Badge>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      {s.status !== "pending" && s.status !== "running" && (
                        <span className="tabular-nums">
                          Step {i + 1}/{steps.length}
                        </span>
                      )}
                      {s.result && s.result.tokens_used > 0 && (
                        <span>{s.result.tokens_used} tokens</span>
                      )}
                    </div>
                  </div>

                  {/* Skip reason */}
                  {s.result?.skip_reason && (
                    <p className="text-xs text-muted-foreground pl-6">
                      {s.result.skip_reason}
                    </p>
                  )}

                  {/* Error */}
                  {s.result?.error && (
                    <p className="text-xs text-destructive pl-6">
                      {s.result.error}
                    </p>
                  )}

                  {/* Actions */}
                  {s.result && s.result.actions.length > 0 && (
                    <div className="flex flex-wrap gap-1 pl-6">
                      {s.result.actions.map((action, j) => (
                        <Badge
                          key={j}
                          variant="secondary"
                         
                        >
                          {action}
                        </Badge>
                      ))}
                    </div>
                  )}

                  {/* AI Response */}
                  {s.result?.ai_response && (
                    <pre className="ml-6 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-2 text-[11px] leading-relaxed">
                      {JSON.stringify(s.result.ai_response, null, 2)}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function PluginsSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <Card key={i}>
          <CardContent className="flex items-center gap-4 py-4">
            <Skeleton className="h-10 w-10 rounded-lg" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-64" />
            </div>
            <Skeleton className="h-6 w-12" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PluginsPage() {
  usePageTitle("Plugins");
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [testDialogOpen, setTestDialogOpen] = useState(false);

  const pluginsQuery = useListPluginsApiAiProvidersPluginsGet();
  const plugins = unwrapResponse<PluginInfo[]>(pluginsQuery.data);

  const settingsQuery = useGetSettingsApiSettingsGet();
  const settings = unwrapResponse<SettingsResponse>(settingsQuery.data);

  const updateMutation = useUpdateSettingsApiSettingsPut();

  // All plugins come from backend, sorted by execution_order by default.
  // User can reorder; order is persisted to backend via plugin_order.
  const baseList = useMemo(() => plugins ?? [], [plugins]);
  const [orderedNames, setOrderedNames] = useState<string[]>([]);

  // Initialise orderedNames from backend settings (plugin_order) or
  // fall back to the default execution_order from the plugin list.
  useEffect(() => {
    if (baseList.length === 0) return;

    const backendOrder = settings?.plugin_order;
    const baseNames = baseList.map((p) => p.name);

    if (backendOrder && backendOrder.length > 0) {
      // Merge: keep backend order but add any new plugins not yet in it
      const orderSet = new Set(backendOrder);
      const baseSet = new Set(baseNames);
      const merged = backendOrder.filter((n) => baseSet.has(n));
      for (const n of baseNames) {
        if (!orderSet.has(n)) merged.push(n);
      }
      setOrderedNames(merged);
    } else if (orderedNames.length === 0) {
      setOrderedNames(baseNames);
    }
  }, [baseList, settings?.plugin_order]); // eslint-disable-line react-hooks/exhaustive-deps

  const pluginEntries = useMemo(() => {
    if (orderedNames.length === 0) return baseList;
    const map = new Map(baseList.map((p) => [p.name, p]));
    return orderedNames
      .map((name) => map.get(name))
      .filter((p): p is PluginInfo => !!p);
  }, [baseList, orderedNames]);

  // Read the current approval mode for a plugin from settings
  function getApprovalMode(plugin: PluginInfo): string {
    if (!plugin.approval_key) return "auto";
    const modes = settings?.approval_modes as Record<string, string> | undefined;
    return modes?.[plugin.approval_key] ?? "auto";
  }

  function isPluginEnabled(plugin: PluginInfo): boolean {
    return getApprovalMode(plugin) !== "disabled";
  }

  // Save a single approval mode change via PUT /api/settings
  async function saveApprovalMode(approvalKey: string, newValue: string) {
    try {
      await updateMutation.mutateAsync({
        data: {
          approval_modes: {
            [approvalKey]: newValue as ApprovalMode,
          },
        },
      });
      queryClient.invalidateQueries({
        queryKey: getGetSettingsApiSettingsGetQueryKey(),
      });
    } catch {
      toast({ title: "Failed to save setting", description: "Could not update the approval mode. Please try again.", variant: "destructive" });
    }
  }

  // Priority reorder — persists to backend
  const movePlugin = useCallback(
    (index: number, direction: "up" | "down") => {
      setOrderedNames((prev) => {
        const next = [...prev];
        const swapIndex = direction === "up" ? index - 1 : index + 1;
        if (swapIndex < 0 || swapIndex >= next.length) return prev;
        const a = next[index]!;
        const b = next[swapIndex]!;
        next[index] = b;
        next[swapIndex] = a;

        // Persist new order to backend
        updateMutation.mutate(
          { data: { plugin_order: next } },
          {
            onSuccess: () => {
              queryClient.invalidateQueries({
                queryKey: getGetSettingsApiSettingsGetQueryKey(),
              });
            },
            onError: () => {
              toast({
                title: "Error",
                description: "Failed to reorder plugins. Please try again.",
                variant: "destructive",
              });
            },
          },
        );

        return next;
      });
    },
    [updateMutation, queryClient],
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (pluginsQuery.isError || settingsQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Plugins"
          description="Enable, disable, and configure AI plugins and the rules engine."
        />
        <QueryError
          message="Failed to load plugin settings."
          onRetry={() => {
            pluginsQuery.refetch();
            settingsQuery.refetch();
          }}
        />
      </div>
    );
  }

  if (pluginsQuery.isLoading || settingsQuery.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Plugins"
          description="Enable, disable, and configure AI plugins and the rules engine."
        />
        <PluginsSkeleton />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Plugins"
        description="Enable, disable, and configure AI plugins and the rules engine."
        actions={
          <AppButton
            icon={<FlaskConical />}
            label="Test Pipeline"
            onClick={() => setTestDialogOpen(true)}
          >
            Test Pipeline
          </AppButton>
        }
      />

      <TestPipelineDialog
        open={testDialogOpen}
        onOpenChange={setTestDialogOpen}
      />

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <ArrowUpDown className="h-4 w-4" />
                Processing Pipeline
              </CardTitle>
              <CardDescription>
                Plugins are executed in order. Drag to reorder, toggle to enable/disable.
              </CardDescription>
            </div>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          <TooltipProvider delayDuration={200}>
            <div className="divide-y divide-border">
              {pluginEntries.map((plugin, index) => {
                const enabled = isPluginEnabled(plugin);
                const approvalMode = getApprovalMode(plugin);

                return (
                  <div
                    key={plugin.name}
                    className={cn(
                      "flex items-center gap-4 px-6 py-4 transition-opacity",
                      !enabled && "opacity-50",
                    )}
                  >
                    {/* Reorder buttons */}
                    <div className="flex flex-col shrink-0">
                      <AppButton
                        icon={<ChevronUp />}
                        label="Move up"
                        variant="ghost"
                        className="h-5 w-5"
                        disabled={index === 0 || updateMutation.isPending}
                        onClick={() => movePlugin(index, "up")}
                      />
                      <AppButton
                        icon={<ChevronDown />}
                        label="Move down"
                        variant="ghost"
                        className="h-5 w-5"
                        disabled={index === pluginEntries.length - 1 || updateMutation.isPending}
                        onClick={() => movePlugin(index, "down")}
                      />
                    </div>

                    {/* Info */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">
                          {plugin.display_name}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground truncate">
                        {plugin.description}
                      </p>
                    </div>

                    {/* Approval mode tabs */}
                    {plugin.approval_key && (
                      <div className="shrink-0">
                        <Tabs
                          value={approvalMode}
                          onValueChange={(v) =>
                            saveApprovalMode(plugin.approval_key!, v)
                          }
                        >
                          <TabsList className="h-8">
                            {getModeOptions(plugin).map((opt) => (
                              <TabsTrigger
                                key={opt.value}
                                value={opt.value}
                                className="h-6 px-3 text-xs"
                                disabled={updateMutation.isPending}
                              >
                                {opt.label}
                              </TabsTrigger>
                            ))}
                          </TabsList>
                        </Tabs>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </TooltipProvider>
        </CardContent>
      </Card>

      {/* Information card */}
      <Card>
        <CardContent className="py-4">
          <div className="flex gap-3">
            <Puzzle className="h-5 w-5 shrink-0 text-muted-foreground mt-0.5" />
            <div className="space-y-1 text-sm text-muted-foreground">
              <p>
                <strong>Off</strong> -- plugin is disabled and skipped during mail processing.
              </p>
              <p>
                <strong>Auto</strong> -- the plugin runs automatically without user intervention.
              </p>
              <p>
                <strong>Approval</strong> -- AI actions are queued for manual review before execution.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
