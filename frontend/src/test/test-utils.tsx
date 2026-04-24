import { type ReactElement, type ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { TooltipProvider } from "@/components/ui/tooltip";

/**
 * Create a fresh QueryClient configured for tests.
 *
 * Retries are disabled so failed queries surface immediately, and
 * cacheTime is set to Infinity to prevent garbage collection during
 * assertions.
 */
function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: Infinity,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

interface WrapperProps {
  children: ReactNode;
}

/**
 * Custom render that wraps the component under test with the same
 * providers the real app uses (QueryClient, Router, Tooltip).
 *
 * A fresh QueryClient is created per render call so tests are isolated.
 */
function customRender(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper"> & { route?: string },
) {
  const { route = "/", ...renderOptions } = options ?? {};
  const queryClient = createTestQueryClient();

  function Wrapper({ children }: WrapperProps) {
    return (
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>
    );
  }

  return { ...render(ui, { wrapper: Wrapper, ...renderOptions }), queryClient };
}

// Re-export everything from testing-library so tests only import from here
export { customRender as render };
export { createTestQueryClient };
export { screen, waitFor, within, act } from "@testing-library/react";
export { default as userEvent } from "@testing-library/user-event";
