import * as React from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/*  FilterListItem — universal card for searchable / filterable lists         */
/* -------------------------------------------------------------------------- */

export interface FilterListItemProps {
  /** Leading slot rendered before the icon (e.g. Checkbox). */
  leading?: React.ReactNode;

  /** Icon shown before the title row. */
  icon?: React.ReactNode;

  /** Primary title — truncated by default. */
  title: React.ReactNode;

  /** Inline badges after the title. */
  badges?: React.ReactNode;

  /** Secondary lines below the title (from, description, …). */
  subtitle?: React.ReactNode;

  /**
   * Collapsible body preview text.
   * Clamped to `previewLines` when collapsed, shown in full when expanded.
   */
  preview?: React.ReactNode;

  /** Max lines for the clamped preview (default 3). */
  previewLines?: 2 | 3 | 4;

  /**
   * Arbitrary expanded content shown below a divider.
   * Only rendered when `expanded` is true.
   */
  expandedContent?: React.ReactNode;

  /** Whether the item is expandable. Shows a chevron at the bottom center. */
  expandable?: boolean;

  /** Controlled expand state. */
  expanded?: boolean;

  /** Called when the user toggles expand. */
  onToggleExpand?: () => void;

  /** Date / timestamp rendered top-right. */
  date?: React.ReactNode;

  /** Action buttons rendered top-right (after date). */
  actions?: React.ReactNode;

  /** Additional className on the outer Card. */
  className?: string;
}

/* --------------------------------- helpers -------------------------------- */

const CLAMP: Record<number, string> = {
  2: "line-clamp-2",
  3: "line-clamp-3",
  4: "line-clamp-4",
};

/* -------------------------------- component ------------------------------- */

export function FilterListItem({
  leading,
  icon,
  title,
  badges,
  subtitle,
  preview,
  previewLines = 3,
  expandedContent,
  expandable = false,
  expanded = false,
  onToggleExpand,
  date,
  actions,
  className,
}: FilterListItemProps) {
  return (
    <Card className={className}>
      <CardContent className="pt-4">
        {/* Header row */}
        <div className="flex items-start justify-between gap-3">
          {/* Left: leading + icon + text */}
          <div className="flex min-w-0 flex-1 items-start gap-2">
            {leading}
            {icon && (
              <span className="mt-0.5 shrink-0 text-muted-foreground [&>svg]:h-4 [&>svg]:w-4">
                {icon}
              </span>
            )}
            <div className="min-w-0 flex-1">
              {/* Title + badges */}
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-medium">{title}</span>
                {badges && (
                  <span className="flex shrink-0 items-center gap-1.5">
                    {badges}
                  </span>
                )}
              </div>
              {/* Subtitle */}
              {subtitle && <div className="mt-0.5">{subtitle}</div>}
              {/* Preview — clamped when collapsed, full when expanded */}
              {preview && (
                <div
                  className={cn(
                    "mt-1 whitespace-pre-wrap text-sm text-muted-foreground",
                    expandable && !expanded && CLAMP[previewLines],
                  )}
                >
                  {preview}
                </div>
              )}
            </div>
          </div>

          {/* Right: date + actions */}
          <div className="flex shrink-0 items-center gap-2">
            {date && (
              <span className="text-xs text-muted-foreground">{date}</span>
            )}
            {actions}
          </div>
        </div>

        {/* Expanded content */}
        {expanded && expandedContent && (
          <div className="mt-4 space-y-3 border-t border-border pt-4">
            {expandedContent}
          </div>
        )}

        {/* Expand/collapse chevron — bottom center */}
        {expandable && (
          <button
            type="button"
            onClick={onToggleExpand}
            className="mt-2 flex w-full items-center justify-center text-muted-foreground hover:text-foreground transition-colors"
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse" : "Expand"}
          >
            {expanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
        )}
      </CardContent>
    </Card>
  );
}
