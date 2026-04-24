import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Link } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ErrorBoundary } from "@/components/error-boundary";
import { RouteErrorBoundary } from "@/components/route-error-boundary";
import { AppLayout } from "@/components/layout/app-layout";
import { Skeleton } from "@/components/ui/skeleton";
import { pluginRoutes } from "@/plugin-routes";

// Lazy-loaded page components (static routes only)
const Dashboard = lazy(() => import("@/pages/dashboard"));
const MailAccounts = lazy(() => import("@/pages/mail-accounts"));
const AIProviders = lazy(() => import("@/pages/ai-settings"));
const Plugins = lazy(() => import("@/pages/plugins"));
const Prompts = lazy(() => import("@/pages/prompts"));
const Approvals = lazy(() => import("@/pages/approvals"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function PageSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-4 w-72" />
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
    </div>
  );
}

function NotFound() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-20">
      <h1 className="text-4xl font-bold">404</h1>
      <p className="text-muted-foreground">Page not found.</p>
      <Link to="/" className="text-sm text-primary underline">
        Back to Dashboard
      </Link>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <ErrorBoundary onRetry={() => queryClient.resetQueries()}>
          <BrowserRouter>
            <Routes>
              <Route
                path="/*"
                element={
                  <AppLayout>
                    <Suspense fallback={<PageSkeleton />}>
                      <Routes>
                        {/* Overview */}
                        <Route index element={<RouteErrorBoundary><Dashboard /></RouteErrorBoundary>} />
                        <Route path="approvals" element={<RouteErrorBoundary><Approvals /></RouteErrorBoundary>} />

                        {/* Configuration (static) */}
                        <Route path="plugins" element={<RouteErrorBoundary><Plugins /></RouteErrorBoundary>} />
                        <Route path="prompts" element={<RouteErrorBoundary><Prompts /></RouteErrorBoundary>} />
                        <Route path="mail-accounts" element={<RouteErrorBoundary><MailAccounts /></RouteErrorBoundary>} />
                        <Route path="ai-providers" element={<RouteErrorBoundary><AIProviders /></RouteErrorBoundary>} />

                        {/* Plugin pages (dynamic from registry) */}
                        {Object.entries(pluginRoutes).map(
                          ([path, Component]) => (
                            <Route
                              key={path}
                              path={path}
                              element={<RouteErrorBoundary><Component /></RouteErrorBoundary>}
                            />
                          ),
                        )}

                        <Route path="*" element={<NotFound />} />
                      </Routes>
                    </Suspense>
                  </AppLayout>
                }
              />
            </Routes>
          </BrowserRouter>
        </ErrorBoundary>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
