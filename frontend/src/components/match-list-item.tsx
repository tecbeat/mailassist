import * as React from "react";
import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

export interface MatchListItemProps
  extends Omit<React.HTMLAttributes<HTMLElement>, "children"> {
  /** Render as a different element (default: `"button"`). Use `"div"` when
   *  the row contains nested interactive elements (e.g. drag handles). */
  as?: "button" | "div";
  /** Left slot — avatar image, initials circle, or icon. */
  avatar: React.ReactNode;
  /** Primary text (always visible). */
  title: string;
  /** Secondary text — space is always reserved even when empty. */
  subtitle?: string;
  /** Optional badges rendered between content and action slot. */
  badges?: React.ReactNode;
  /** Right-most slot (fixed width) — check icon, spam button, etc. */
  action?: React.ReactNode;
  /** Highlight state (selected / matched). */
  marked?: boolean;
  /** Disabled state (only relevant when `as="button"`). */
  disabled?: boolean;
}

/**
 * A consistent, fixed-height list item for the two-column matching UI.
 *
 * Every row is exactly `h-14` (56 px) regardless of whether a subtitle
 * is present, so the layout never jumps when items are selected or when
 * some rows have subtitles and others don't.
 *
 * Slots:
 * ```
 * [ avatar ]  [ title / subtitle ]  [ badges ]  [ action ]
 *   shrink-0       flex-1             shrink-0    w-8 shrink-0
 * ```
 */
export const MatchListItem = React.forwardRef<
  HTMLElement,
  MatchListItemProps
>(
  (
    { as = "button", avatar, title, subtitle, badges, action, marked, disabled, className, ...props },
    ref,
  ) => {
    const Comp = as as React.ElementType;
    return (
      <Comp
        ref={ref}
        {...(as === "button" ? { type: "button", disabled } : {})}
        className={cn(
          "flex h-12 w-full min-w-0 items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-accent",
          marked && "bg-primary/10 ring-1 ring-primary",
          className,
        )}
        {...props}
      >
        {/* Avatar / icon slot */}
        <div className="flex shrink-0 items-center gap-1">{avatar}</div>

        {/* Title + optional subtitle */}
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium leading-tight">{title}</p>
          {subtitle && (
            <p className="truncate text-xs leading-tight text-muted-foreground">
              {subtitle}
            </p>
          )}
        </div>

        {/* Badges */}
        {badges && (
          <div className="flex shrink-0 items-center gap-2">{badges}</div>
        )}

        {/* Action slot — marked items show check icon unless custom action is provided */}
        {(marked || action != null) && (
          <div className="flex w-8 shrink-0 items-center justify-center">
            {action != null ? (
              action
            ) : marked ? (
              <Check className="h-4 w-4 text-primary" />
            ) : null}
          </div>
        )}
      </Comp>
    );
  },
);
MatchListItem.displayName = "MatchListItem";
