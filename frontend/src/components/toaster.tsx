import { Copy } from "lucide-react";

import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
  useToast,
} from "@/components/ui/toast";

export function Toaster() {
  const { toasts } = useToast();

  return (
    <ToastProvider>
      {toasts.map(({ id, title, description, action, ...props }) => (
        <Toast key={id} {...props}>
          <div className="grid gap-1 min-w-0 flex-1">
            {title && <ToastTitle>{title}</ToastTitle>}
            {description && <ToastDescription>{description}</ToastDescription>}
          </div>
          <div className="flex shrink-0 items-start gap-1">
            {/* Copy button — only shown for string descriptions so errors are easy to share */}
            {props.variant === "destructive" && typeof description === "string" && (
              <button
                type="button"
                aria-label="Copy error message"
                className="rounded p-1 opacity-60 hover:opacity-100 transition-opacity focus:outline-none focus:ring-1 focus:ring-ring"
                onClick={() => void navigator.clipboard.writeText(
                  [typeof title === "string" ? title : "", description].filter(Boolean).join(": ")
                )}
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            )}
            {action}
            <ToastClose />
          </div>
        </Toast>
      ))}
      <ToastViewport />
    </ToastProvider>
  );
}
