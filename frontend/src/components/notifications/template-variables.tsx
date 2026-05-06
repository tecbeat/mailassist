import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import customInstance from "@/services/client";
import type { TemplateVariable } from "@/types/api";

interface TemplateVariablesProps {
  /** When provided, only variables relevant to this event type are shown. */
  eventType?: string;
}

/** Fetches and renders the template variables reference grid. */
export function TemplateVariables({ eventType }: TemplateVariablesProps) {
  const url = eventType
    ? `/api/notifications/variables?event_type=${encodeURIComponent(eventType)}`
    : `/api/notifications/variables`;

  const variablesQuery = useQuery({
    queryKey: ["/api/notifications/variables", eventType ?? null],
    queryFn: () =>
      customInstance<{ data: TemplateVariable[]; status: number }>(url, { method: "GET" }),
  });

  const variables = (variablesQuery.data as { data: TemplateVariable[] } | undefined)?.data;

  if (variablesQuery.isError) {
    return <p className="text-sm text-destructive">Failed to load variables.</p>;
  }

  if (variablesQuery.isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-4 w-full" />
        ))}
      </div>
    );
  }

  if (!variables?.length) {
    return <p className="text-sm text-muted-foreground">No variables available.</p>;
  }

  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {variables.map((v) => (
        <div key={v.name} className="rounded-md border border-border p-2.5">
          <div className="flex items-center gap-2">
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-semibold">
              {"{{ " + v.name + " }}"}
            </code>
            <Badge variant="secondary">{v.var_type}</Badge>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">{v.description}</p>
          {v.example && (
            <p className="mt-0.5 text-xs text-muted-foreground/70">
              e.g. <code className="text-foreground/60">{v.example}</code>
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
