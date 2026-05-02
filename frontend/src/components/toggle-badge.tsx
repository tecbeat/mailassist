import { Badge } from "@/components/ui/badge";
import type { BadgeProps } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/* -------------------------------------------------------------------------- */
/*  ToggleBadge — clickable badge that switches variant on selection          */
/* -------------------------------------------------------------------------- */

export interface ToggleBadgeProps extends Omit<BadgeProps, "variant" | "onClick"> {
  /** Whether the badge is currently selected / active. */
  selected?: boolean;
  /** Badge variant when selected (default: "default"). */
  selectedVariant?: BadgeProps["variant"];
  /** Badge variant when not selected (default: "secondary"). */
  unselectedVariant?: BadgeProps["variant"];
  /** Click handler. */
  onClick?: () => void;
}

export function ToggleBadge({
  selected = false,
  selectedVariant = "default",
  unselectedVariant = "secondary",
  onClick,
  className,
  children,
  ...rest
}: ToggleBadgeProps) {
  return (
    <Badge
      variant={selected ? selectedVariant : unselectedVariant}
      className={cn("cursor-pointer select-none transition-colors", className)}
      onClick={onClick}
      {...rest}
    >
      {children}
    </Badge>
  );
}
