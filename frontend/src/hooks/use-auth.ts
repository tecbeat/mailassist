import { useCallback } from "react";
import {
  useGetCurrentUserAuthMeGet,
  useLogoutAuthLogoutPost,
} from "@/services/api/auth/auth";

interface AuthUser {
  email: string;
  display_name?: string;
  sub?: string;
  [key: string]: unknown;
}

export function useAuth() {
  const {
    data: response,
    isLoading,
    isError,
  } = useGetCurrentUserAuthMeGet({
    query: {
      retry: false,
      refetchOnWindowFocus: true,
    },
  });

  const logoutMutation = useLogoutAuthLogoutPost();

  const user = (response?.data as AuthUser) ?? null;
  const isAuthenticated = !!user && !isError;

  const login = useCallback(() => {
    window.location.href = "/auth/login";
  }, []);

  const logout = useCallback(() => {
    logoutMutation.mutate(undefined, {
      onSettled: () => {
        window.location.href = "/auth/login";
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mutate reference is stable
  }, [logoutMutation.mutate]);

  return {
    user,
    isLoading,
    isAuthenticated,
    login,
    logout,
  };
}
