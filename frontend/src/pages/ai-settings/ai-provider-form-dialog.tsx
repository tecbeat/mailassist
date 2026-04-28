import { useEffect, useRef } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { X, Save } from "lucide-react";

import type { AIProviderResponse } from "@/types/api";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Slider } from "@/components/ui/slider";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AppButton } from "@/components/app-button";

import {
  aiProviderSchema,
  type AIProviderFormValues,
  PROVIDER_DEFAULTS,
  getDefaultFormValues,
} from "./ai-settings-schemas";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AIProviderFormDialogProps {
  open: boolean;
  editingProvider: AIProviderResponse | null;
  isMutating: boolean;
  onClose: () => void;
  onSubmit: (values: AIProviderFormValues) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AIProviderFormDialog({
  open,
  editingProvider,
  isMutating,
  onClose,
  onSubmit,
}: AIProviderFormDialogProps) {
  const form = useForm<AIProviderFormValues>({
    resolver: zodResolver(aiProviderSchema),
    defaultValues: getDefaultFormValues(),
  });

  const watchedProviderType = form.watch("provider_type");
  const prevProviderType = useRef(watchedProviderType);

  // Reset form when dialog opens with new context
  useEffect(() => {
    if (!open) return;
    if (editingProvider) {
      form.reset({
        name: editingProvider.name ?? "",
        provider_type: editingProvider.provider_type as "openai" | "ollama",
        base_url: editingProvider.base_url,
        model_name: editingProvider.model_name,
        api_key: "",
        temperature: editingProvider.temperature,
        max_tokens: editingProvider.max_tokens,
        timeout_seconds: editingProvider.timeout_seconds ?? null,
      });
      prevProviderType.current = editingProvider.provider_type as "openai" | "ollama";
    } else {
      form.reset(getDefaultFormValues());
      prevProviderType.current = "openai";
    }
  }, [open, editingProvider, form]);

  // Auto-apply provider-specific defaults when switching type in create mode.
  useEffect(() => {
    if (editingProvider) return;
    if (watchedProviderType === prevProviderType.current) return;

    const oldDefaults = PROVIDER_DEFAULTS[prevProviderType.current];
    const newDefaults = PROVIDER_DEFAULTS[watchedProviderType];

    if (form.getValues("temperature") === oldDefaults.temperature) {
      form.setValue("temperature", newDefaults.temperature, { shouldValidate: true });
    }
    if (form.getValues("max_tokens") === oldDefaults.max_tokens) {
      form.setValue("max_tokens", newDefaults.max_tokens, { shouldValidate: true });
    }
    if (form.getValues("base_url") === oldDefaults.base_url) {
      form.setValue("base_url", newDefaults.base_url);
    }
    if (form.getValues("model_name") === oldDefaults.model_name) {
      form.setValue("model_name", newDefaults.model_name);
    }

    prevProviderType.current = watchedProviderType;
  }, [watchedProviderType, editingProvider, form]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {editingProvider ? "Edit AI Provider" : "Add AI Provider"}
          </DialogTitle>
          <DialogDescription>
            {editingProvider
              ? "Update the provider configuration. Leave API key empty to keep the existing one."
              : "Configure a new AI provider for mail processing."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="space-y-4">
          {/* Name */}
          <div className="space-y-2">
            <Label htmlFor="provider_name">
              Name{" "}
              <span className="text-xs text-muted-foreground">(optional)</span>
            </Label>
            <Input
              id="provider_name"
              placeholder="e.g. Main OpenAI, Local Ollama"
              {...form.register("name")}
            />
            {form.formState.errors.name && (
              <p className="text-xs text-destructive">
                {form.formState.errors.name.message}
              </p>
            )}
          </div>

          {/* Provider Type */}
          <div className="space-y-2">
            <Label>Provider Type</Label>
            <Select
              value={watchedProviderType}
              onValueChange={(value) =>
                form.setValue("provider_type", value as "openai" | "ollama", {
                  shouldValidate: true,
                })
              }
            >
              <SelectTrigger>
                <SelectValue placeholder="Select provider type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="openai">OpenAI</SelectItem>
                <SelectItem value="ollama">Ollama</SelectItem>
              </SelectContent>
            </Select>
            {form.formState.errors.provider_type && (
              <p className="text-xs text-destructive">
                {form.formState.errors.provider_type.message}
              </p>
            )}
          </div>

          {/* Base URL */}
          <div className="space-y-2">
            <Label htmlFor="base_url">Base URL</Label>
            <Input
              id="base_url"
              placeholder={
                watchedProviderType === "ollama"
                  ? "http://localhost:11434"
                  : "https://api.openai.com/v1"
              }
              {...form.register("base_url")}
            />
            {form.formState.errors.base_url && (
              <p className="text-xs text-destructive">
                {form.formState.errors.base_url.message}
              </p>
            )}
          </div>

          {/* Model Name */}
          <div className="space-y-2">
            <Label htmlFor="model_name">Model Name</Label>
            <Input
              id="model_name"
              placeholder={
                watchedProviderType === "ollama" ? "llama3.1" : "gpt-4o"
              }
              {...form.register("model_name")}
            />
            {form.formState.errors.model_name && (
              <p className="text-xs text-destructive">
                {form.formState.errors.model_name.message}
              </p>
            )}
          </div>

          {/* API Key */}
          <div className="space-y-2">
            <Label htmlFor="api_key">
              API Key
              {watchedProviderType === "ollama" && (
                <span className="ml-1 text-xs text-muted-foreground">
                  (optional for Ollama)
                </span>
              )}
            </Label>
            <Input
              id="api_key"
              type="password"
              placeholder={
                editingProvider
                  ? "Leave empty to keep existing"
                  : "sk-..."
              }
              {...form.register("api_key")}
            />
            {form.formState.errors.api_key && (
              <p className="text-xs text-destructive">
                {form.formState.errors.api_key.message}
              </p>
            )}
          </div>

          <Separator />

          {/* Temperature */}
          <div className="space-y-2">
            <Label htmlFor="temperature">
              Temperature{" "}
              <span className="text-xs text-muted-foreground">
                (0 = deterministic, 2 = creative)
              </span>
            </Label>
            <div className="flex items-center gap-3">
              <Slider
                id="temperature"
                min={0}
                max={2}
                step={0.1}
                value={[form.watch("temperature")]}
                onValueChange={([value]) =>
                  form.setValue("temperature", value ?? 0, {
                    shouldValidate: true,
                  })
                }
                className="flex-1"
              />
              <span className="w-10 text-right text-sm font-medium tabular-nums">
                {form.watch("temperature").toFixed(1)}
              </span>
            </div>
            {form.formState.errors.temperature && (
              <p className="text-xs text-destructive">
                {form.formState.errors.temperature.message}
              </p>
            )}
          </div>

          {/* Timeout */}
          <div className="space-y-2">
            <Label htmlFor="timeout_seconds">
              Timeout (seconds){" "}
              <span className="text-xs text-muted-foreground">
                (empty = global default)
              </span>
            </Label>
            <Input
              id="timeout_seconds"
              type="number"
              min="10"
              max="600"
              placeholder="120"
              {...form.register("timeout_seconds", {
                setValueAs: (v: string) => (v === "" ? null : Number(v)),
              })}
            />
            {form.formState.errors.timeout_seconds && (
              <p className="text-xs text-destructive">
                {form.formState.errors.timeout_seconds.message}
              </p>
            )}
          </div>

          {/* Max Tokens */}
          <div className="space-y-2">
            <Label htmlFor="max_tokens">Max Tokens</Label>
            <Input
              id="max_tokens"
              type="number"
              min="64"
              max="32768"
              {...form.register("max_tokens", { valueAsNumber: true })}
            />
            {form.formState.errors.max_tokens && (
              <p className="text-xs text-destructive">
                {form.formState.errors.max_tokens.message}
              </p>
            )}
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
              label={editingProvider ? "Save Changes" : "Create Provider"}
              type="submit"
              variant="primary"
              loading={isMutating}
            >
              {editingProvider ? "Save Changes" : "Create Provider"}
            </AppButton>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
