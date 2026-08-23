import { usePageTitle } from "@/hooks/use-page-title";
import { Wrench } from "lucide-react";

import { useListTools, useUpdateToolMode } from "@/services/api/tools";
import type { ToolInfo } from "@/types/api/toolInfo";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";

import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function ToolsSkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <Card key={i}>
          <CardContent className="flex items-center gap-4 py-4">
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

export default function ToolsPage() {
  usePageTitle("Tools");
  const { toast } = useToast();

  const toolsQuery = useListTools();
  const tools: ToolInfo[] = toolsQuery.data ?? [];
  const updateMutation = useUpdateToolMode();

  async function toggleTool(toolName: string, enabled: boolean) {
    try {
      await updateMutation.mutateAsync({ toolName, enabled });
    } catch {
      toast({
        title: "Failed to save setting",
        description: "Could not update tool mode. Please try again.",
        variant: "destructive",
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (toolsQuery.isError) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Tools"
          description="Enable or disable LLM tools available to all plugins during inference."
        />
        <QueryError
          message="Failed to load tools."
          onRetry={() => toolsQuery.refetch()}
        />
      </div>
    );
  }

  if (toolsQuery.isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Tools"
          description="Enable or disable LLM tools available to all plugins during inference."
        />
        <ToolsSkeleton />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tools"
        description="Enable or disable LLM tools available to all plugins during inference."
      />

      <Card>
        <CardHeader className="pb-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Wrench className="h-4 w-4" />
              Available Tools
            </CardTitle>
            <CardDescription>
              Tools provide additional context-gathering capabilities to the LLM
              during plugin execution. Disabled tools will not be offered to the
              model.
            </CardDescription>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          <div className="divide-y divide-border">
            {tools.map((tool) => (
              <div
                key={tool.name}
                className={cn(
                  "flex items-center gap-4 px-6 py-4 transition-opacity",
                  !tool.enabled && "opacity-50",
                )}
              >
                {/* Info */}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm font-mono">
                      {tool.name}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {tool.description}
                  </p>
                </div>

                {/* Toggle */}
                <div className="shrink-0">
                  <Switch
                    checked={tool.enabled}
                    onCheckedChange={(checked) => toggleTool(tool.name, checked)}
                    disabled={updateMutation.isPending}
                  />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Information card */}
      <Card>
        <CardContent className="py-4">
          <div className="flex gap-3">
            <Wrench className="h-5 w-5 shrink-0 text-muted-foreground mt-0.5" />
            <div className="space-y-1 text-sm text-muted-foreground">
              <p>
                <strong>Enabled</strong> -- the tool is available for the LLM to
                call during plugin execution.
              </p>
              <p>
                <strong>Disabled</strong> -- the tool is hidden from the LLM and
                cannot be invoked.
              </p>
              <p className="pt-1">
                Disabling tools you don't need can reduce inference time and
                prevent unnecessary external requests (e.g. web fetches).
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
