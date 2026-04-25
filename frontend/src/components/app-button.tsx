import * as React from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// AppButton — the single button component for the entire app.
//
// Philosophy:
//   - Every button has an icon.
//   - Default appearance is outline + icon + text.
//   - Only deviate (icon-only, ghost, primary) when there's a reason.
//   - Buttons next to each other always share the same style.
//
// Variants:
//   ghost   — icon-only, no border, subtle hover (inline actions, toolbars)
//   outline — bordered, neutral or action-colored (default, most buttons)
//   primary — solid primary/blue fill (main CTA per section)
//
// Sizes:
//   default — standard button height
//   sm      — compact icon-only for tight contexts (forms, trees)
// ---------------------------------------------------------------------------

export interface AppButtonProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  /** Icon element (e.g. `<Pencil />`). Always required. */
  icon: React.ReactNode;
  /** Accessible label — also shown as tooltip for icon-only buttons. */
  label: string;
  /** Optional visible text next to the icon. Omit for icon-only. */
  children?: React.ReactNode;
  /** Visual style. @default "outline" */
  variant?: "ghost" | "outline" | "primary";
  /** Semantic colour (ignored when variant is "primary"). */
  color?: "default" | "destructive" | "warning" | "success";
  /** Button size. `sm` is only valid for icon-only buttons. @default "default" */
  size?: "default" | "sm";
  /** Show a spinning loader instead of the icon. */
  loading?: boolean;
  /** Render as child element (e.g. for wrapping a `<Link>`). */
  asChild?: boolean;
}

/** Map AppButton variant → shadcn Button variant */
const SHADCN_VARIANT = {
  ghost: "ghost",
  outline: "outline",
  primary: "default",
} as const;

/** Colour classes per variant × colour (primary ignores colour). */
const COLOR_CLASSES: Record<string, Record<string, string>> = {
  ghost: {
    default: "",
    destructive:
      "text-destructive hover:bg-destructive hover:text-destructive-foreground",
    warning:
      "text-orange-600 hover:bg-orange-100 hover:text-orange-700 dark:hover:bg-orange-950",
    success:
      "text-green-600 hover:bg-green-100 hover:text-green-700 dark:hover:bg-green-950",
  },
  outline: {
    default: "",
    destructive:
      "text-destructive border-destructive/40 hover:bg-destructive hover:text-destructive-foreground",
    warning:
      "text-orange-600 border-orange-300 hover:bg-orange-100 hover:text-orange-700 dark:border-orange-700 dark:hover:bg-orange-950",
    success:
      "text-green-600 border-green-300 hover:bg-green-100 hover:text-green-700 dark:border-green-700 dark:hover:bg-green-950",
  },
  primary: {
    default: "border-2 border-transparent shadow-sm",
    destructive:
      "border-2 border-transparent shadow-sm bg-destructive text-destructive-foreground hover:bg-destructive/90",
    warning:
      "border-2 border-transparent shadow-sm bg-orange-600 text-white hover:bg-orange-700 dark:bg-orange-600 dark:hover:bg-orange-700",
    success:
      "border-2 border-transparent shadow-sm bg-green-600 text-white hover:bg-green-700 dark:bg-green-600 dark:hover:bg-green-700",
  },
};

export const AppButton = React.forwardRef<HTMLButtonElement, AppButtonProps>(
  (
    {
      icon,
      label,
      children,
      variant = "outline",
      color = "default",
      size = "default",
      loading,
      asChild,
      className,
      ...props
    },
    ref,
  ) => {
    // When asChild is used, `children` is the wrapper element (e.g. <Link>)
    // and `visibleText` is extracted from it. For normal usage, `children`
    // is the visible text string.
    const isAsChild = asChild && React.isValidElement(children);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const visibleText = isAsChild ? (children as React.ReactElement<any>).props.children : children;
    const isIconOnly = !visibleText;

    // --- sizing ---
    const sizeClass = isIconOnly
      ? size === "sm"
        ? "h-6 w-6"
        : "h-8 w-8"
      : "h-8 px-3 gap-1.5";

    const iconSize =
      size === "sm"
        ? "[&>svg]:h-3 [&>svg]:w-3"
        : "[&>svg]:h-3.5 [&>svg]:w-3.5";

    // --- colour ---
    const colorClass = COLOR_CLASSES[variant]?.[color] ?? "";

    const innerContent = (
      <>
        {loading ? (
          <Loader2
            className={cn(
              "animate-spin",
              size === "sm" ? "h-3 w-3" : "h-3.5 w-3.5",
            )}
          />
        ) : (
          <span className={cn("shrink-0", iconSize)}>{icon}</span>
        )}
        {visibleText && (
          <span className="truncate text-xs font-medium">{visibleText}</span>
        )}
      </>
    );

    const buttonContent = isAsChild
      ? React.cloneElement(children as React.ReactElement, {}, innerContent)
      : innerContent;

    const button = (
      <Button
        ref={ref}
        type="button"
        variant={SHADCN_VARIANT[variant]}
        size={isIconOnly ? "icon" : "sm"}
        className={cn(sizeClass, colorClass, className)}
        aria-label={label}
        asChild={isAsChild}
        {...props}
      >
        {buttonContent}
      </Button>
    );

    // Icon-only buttons always get a tooltip for discoverability.
    if (isIconOnly) {
      return (
        <Tooltip>
          <TooltipTrigger asChild>{button}</TooltipTrigger>
          <TooltipContent>{label}</TooltipContent>
        </Tooltip>
      );
    }

    return button;
  },
);
AppButton.displayName = "AppButton";
