import {
  BrainCircuit,
  Pencil,
  Trash2,
  Plug,
  Pause,
  Play,
} from "lucide-react";

import type { AIProviderResponse } from "@/types/api";

import { Badge } from "@/components/ui/badge";
import { AppButton } from "@/components/app-button";
import { ResourceStatusBanner } from "@/components/resource-status-banner";

import { providerTypeLabel } from "./ai-settings-schemas";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PipelinePlugin {
  name: string;
  display_name: string;
  runs_in_pipeline?: boolean;
}

interface AIProviderRowProps {
  provider: AIProviderResponse;
  pipelinePlugins: PipelinePlugin[];
  pluginProviderMap: Record<string, string>;
  onEdit: (provider: AIProviderResponse) => void;
  onDelete: (provider: AIProviderResponse) => void;
  onTest: (providerId: string) => void;
  onPause: (providerId: string) => void;
  onUnpause: (providerId: string) => void;
  onResetHealth: (providerId: string) => void;
  onTogglePlugin: (pluginName: string, providerId: string) => void;
  pauseLoading: boolean;
  unpauseLoading: boolean;
  testLoading: boolean;
  resetHealthLoading: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AIProviderRow({
  provider,
  pipelinePlugins,
  pluginProviderMap,
  onEdit,
  onDelete,
  onTest,
  onPause,
  onUnpause,
  onResetHealth,
  onTogglePlugin,
  pauseLoading,
  unpauseLoading,
  testLoading,
  resetHealthLoading,
}: AIProviderRowProps) {
  return (
    <div className="px-6 py-4 space-y-3">
      {/* Row 1: Name, badges, action buttons */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <BrainCircuit className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="font-medium text-sm truncate">
            {provider.name || providerTypeLabel(provider.provider_type)}
          </span>
          <Badge variant="secondary">
            {providerTypeLabel(provider.provider_type)}
          </Badge>
          {provider.is_paused && (
            <Badge variant="warning">Paused</Badge>
          )}
          {provider.is_paused && provider.paused_reason === "circuit_breaker" && (
            <Badge variant="destructive">Circuit Breaker</Badge>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <AppButton
            icon={provider.is_paused ? <Play /> : <Pause />}
            label={provider.is_paused ? "Resume" : "Pause"}
            variant="ghost"
            loading={pauseLoading || unpauseLoading}
            disabled={pauseLoading || unpauseLoading}
            onClick={() =>
              provider.is_paused
                ? onUnpause(provider.id)
                : onPause(provider.id)
            }
          />
          <AppButton
            icon={<Pencil />}
            label="Edit"
            variant="ghost"
            onClick={() => onEdit(provider)}
          />
          <AppButton
            icon={<Plug />}
            label="Test connection"
            variant="ghost"
            loading={testLoading}
            disabled={testLoading}
            onClick={() => onTest(provider.id)}
          />
          <AppButton
            icon={<Trash2 />}
            label="Delete"
            variant="ghost"
            color="destructive"
            onClick={() => onDelete(provider)}
          />
        </div>
      </div>

      {/* Row 2: Details grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 text-sm pl-7">
        <div>
          <span className="text-muted-foreground text-xs">Model</span>
          <p className="truncate font-mono text-xs">{provider.model_name}</p>
        </div>
        <div>
          <span className="text-muted-foreground text-xs">Base URL</span>
          <p className="truncate font-mono text-xs">{provider.base_url}</p>
        </div>
        <div>
          <span className="text-muted-foreground text-xs">Temperature</span>
          <p className="text-xs">{provider.temperature}</p>
        </div>
        <div>
          <span className="text-muted-foreground text-xs">Max Tokens</span>
          <p className="text-xs">{provider.max_tokens.toLocaleString()}</p>
        </div>
      </div>

      {/* Status banner (pause / circuit breaker) */}
      {provider.is_paused && (
        <div className="pl-7">
          <ResourceStatusBanner
            isPaused={provider.is_paused}
            pausedReason={provider.paused_reason}
            pausedAt={provider.paused_at}
            consecutiveErrors={provider.consecutive_errors}
            lastError={provider.last_error}
            lastErrorAt={provider.last_error_at}
            onResetHealth={() => onResetHealth(provider.id)}
            resetHealthLoading={resetHealthLoading}
          />
        </div>
      )}

      {/* Row 3: Plugin toggle badges */}
      <div className="pl-7">
        <span className="text-muted-foreground text-xs">Plugins</span>
        <div className="flex flex-wrap gap-2 mt-1">
          {pipelinePlugins.map((plugin) => {
            const isAssigned = pluginProviderMap[plugin.name] === provider.id;
            return (
              <Badge
                key={plugin.name}
                variant={isAssigned ? "default" : "secondary"}
                className="cursor-pointer select-none transition-colors"
                onClick={() => onTogglePlugin(plugin.name, provider.id)}
              >
                {plugin.display_name}
              </Badge>
            );
          })}
        </div>
      </div>
    </div>
  );
}
