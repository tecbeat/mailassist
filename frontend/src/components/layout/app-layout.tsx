import { type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { Sidebar } from "./sidebar";
import { Toaster } from "@/components/toaster";
import { ChangelogDialog } from "@/components/changelog-dialog";
import { useAuth } from "@/hooks/use-auth";

interface AppLayoutProps {
  children: ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const { isLoading, isAuthenticated, login } = useAuth();

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!isAuthenticated) {
    login();
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">Redirecting to login...</p>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        <div className="container mx-auto p-6 pt-16 md:pt-6">{children}</div>
      </main>
      <Toaster />
      <ChangelogDialog />
    </div>
  );
}
