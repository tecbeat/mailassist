import { useState, useCallback, type ReactNode } from "react";
import { ErrorBoundary } from "@/components/error-boundary";

interface RouteErrorBoundaryProps {
  children: ReactNode;
}

/**
 * Per-route error boundary that contains rendering failures to a single page
 * without taking down the entire app (navigation/sidebar remain functional).
 *
 * Uses a key-based remount strategy: on retry, the key increments, forcing
 * React to unmount and remount the ErrorBoundary and its children.
 */
export function RouteErrorBoundary({ children }: RouteErrorBoundaryProps) {
  const [retryKey, setRetryKey] = useState(0);

  const handleRetry = useCallback(() => {
    setRetryKey((k) => k + 1);
  }, []);

  return (
    <ErrorBoundary key={retryKey} onRetry={handleRetry}>
      {children}
    </ErrorBoundary>
  );
}
