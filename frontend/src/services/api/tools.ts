/**
 * Manual API hooks for tools endpoint.
 * Will be replaced by orval generation on next openapi.json update.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { UseQueryOptions } from "@tanstack/react-query";

import { customInstance } from "@/services/client";
import type { ToolInfo } from "@/types/api/toolInfo";

// Wrapper types matching orval pattern
type ToolsListResponse = { data: ToolInfo[]; status: 200; headers: Headers };

export const useListTools = <TData = ToolInfo[]>(
  options?: Partial<UseQueryOptions<ToolInfo[], unknown, TData>>,
) => {
  return useQuery<ToolInfo[], unknown, TData>({
    queryKey: ["/api/ai-providers/tools"],
    queryFn: async () => {
      const resp = (await customInstance<ToolsListResponse>(
        "/api/ai-providers/tools",
        { method: "GET" },
      )) as ToolsListResponse;
      return resp.data;
    },
    ...options,
  });
};

export const useUpdateToolMode = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      toolName,
      enabled,
    }: {
      toolName: string;
      enabled: boolean;
    }) => {
      await customInstance("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          tool_modes: { [toolName]: enabled ? "enabled" : "disabled" },
        }),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/ai-providers/tools"] });
      queryClient.invalidateQueries({ queryKey: ["/api/settings"] });
    },
  });
};
