import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useListVariablesApiNotificationsVariablesGet } from "@/services/api/notifications/notifications";
import { unwrapResponse } from "@/lib/utils";
import type { TemplateVariable } from "@/types/api";

/** Fetches and renders the template variables reference grid. */
export function TemplateVariables() {
  const variablesQuery = useListVariablesApiNotificationsVariablesGet();
  const variables = unwrapResponse<TemplateVariable[]>(variablesQuery.data);

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
