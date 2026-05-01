import { AlertCircle, Check } from "lucide-react";

interface TemplatePreviewProps {
  result: string;
  errors: string[];
}

/** Renders a rendered Jinja2 template with an inline success / error badge. */
export function TemplatePreview({ result, errors }: TemplatePreviewProps) {
  return (
    <div className="relative">
      {errors.length > 0 && (
        <div
          role="alert"
          className="absolute right-2 top-2 z-10 flex items-start gap-2 rounded-md border border-destructive bg-destructive/5 p-2 backdrop-blur-sm"
        >
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
          <div className="space-y-1">
            <p className="text-xs font-medium text-destructive">Template Errors</p>
            {errors.map((err, i) => (
              <p key={i} className="text-xs text-destructive/80">
                {err}
              </p>
            ))}
          </div>
        </div>
      )}
      {errors.length === 0 && (
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
        {result}
      </pre>
    </div>
  );
}
