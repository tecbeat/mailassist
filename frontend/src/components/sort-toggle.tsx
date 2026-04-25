import { ArrowDown, ArrowUp, Loader2 } from "lucide-react";

import { AppButton } from "@/components/app-button";
import { cn } from "@/lib/utils";

interface SortToggleProps {
  sortOrder: "newest" | "oldest" | string;
  onToggle: (newOrder: "newest" | "oldest") => void;
  /** Show a spinning loader next to the button. */
  isFetching?: boolean;
  /**
   * Display variant:
   * - `"icon"` (default): compact icon-only button, suitable for toolbars.
   * - `"inline"`: segmented buttons with text labels, suitable for inside
   *   popovers / filter panels where more context is helpful.
   */
  variant?: "icon" | "inline";
}

export function SortToggle({
  sortOrder,
  onToggle,
  isFetching,
  variant = "icon",
}: SortToggleProps) {
  if (variant === "inline") {
    return (
      <div className="flex items-center gap-1.5">
        <div className="inline-flex rounded-md border border-input">
          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-l-md px-3 py-1.5 text-xs transition-colors",
              sortOrder === "newest"
                ? "bg-primary text-primary-foreground"
                : "bg-background text-muted-foreground hover:bg-muted",
            )}
            onClick={() => onToggle("newest")}
          >
            <ArrowDown className="h-3.5 w-3.5" />
            Newest
          </button>
          <button
            type="button"
            className={cn(
              "inline-flex items-center gap-1.5 rounded-r-md border-l border-input px-3 py-1.5 text-xs transition-colors",
              sortOrder === "oldest"
                ? "bg-primary text-primary-foreground"
                : "bg-background text-muted-foreground hover:bg-muted",
            )}
            onClick={() => onToggle("oldest")}
          >
            <ArrowUp className="h-3.5 w-3.5" />
            Oldest
          </button>
        </div>
        {isFetching && (
          <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
        )}
      </div>
    );
  }

  return (
    <div className="ml-auto flex items-center gap-2">
      {isFetching && (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      )}
      <AppButton
        icon={sortOrder === "newest" ? <ArrowDown /> : <ArrowUp />}
        label={sortOrder === "newest" ? "Newest first" : "Oldest first"}
        variant="outline"
        onClick={() =>
          onToggle(sortOrder === "newest" ? "oldest" : "newest")
        }
      />
    </div>
  );
}
