import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { NavLink } from "react-router";
import {
  LayoutDashboard,
  Mail,
  Brain,
  FileText,
  GitBranch,
  CheckCircle,
  Bell,
  CalendarDays,
  Contact,
  FolderTree,
  ListChecks,
  Newspaper,
  Reply,
  ShieldAlert,
  Tags,
  Ticket,
  Puzzle,
  LogOut,
  Menu,
  X,
  Globe,
  Languages,
  type LucideIcon,
} from "lucide-react";
import { cn, unwrapResponse } from "@/lib/utils";
import { AppButton } from "@/components/app-button";
import { useToast } from "@/components/ui/toast";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/use-auth";
import { useVersion } from "@/hooks/use-version";
import {
  useGetSettingsApiSettingsGet,
  useUpdateSettingsApiSettingsPut,
  getGetSettingsApiSettingsGetQueryKey,
} from "@/services/api/settings/settings";
import { useListPluginsApiAiProvidersPluginsGet } from "@/services/api/ai-providers/ai-providers";
import { useQueryClient } from "@tanstack/react-query";
import type { SettingsResponse } from "@/types/api";
import type { PluginInfo } from "@/types/api/pluginInfo";

// ---------------------------------------------------------------------------
// Icon map — resolves backend icon name strings to Lucide components.
// Only icons actually used by plugins are imported to keep the bundle small.
// ---------------------------------------------------------------------------

const ICON_MAP: Record<string, LucideIcon> = {
  ShieldAlert,
  Newspaper,
  Tags,
  FolderTree,
  Ticket,
  CalendarDays,
  Reply,
  ListChecks,
  GitBranch,
  Contact,
  Bell,
};

interface NavItem {
  label: string;
  to: string;
  icon: LucideIcon;
}

// ---------------------------------------------------------------------------
// Section definitions
// ---------------------------------------------------------------------------

const OVERVIEW_ITEMS: NavItem[] = [
  { label: "Dashboard", to: "/", icon: LayoutDashboard },
  { label: "Approvals", to: "/approvals", icon: CheckCircle },
];

const STATIC_CONFIG_ITEMS_TOP: NavItem[] = [
  { label: "Plugins", to: "/plugins", icon: Puzzle },
  { label: "Prompts", to: "/prompts", icon: FileText },
];

const STATIC_CONFIG_ITEMS_BOTTOM: NavItem[] = [
  { label: "Mail Accounts", to: "/mail-accounts", icon: Mail },
  { label: "AI Providers", to: "/ai-providers", icon: Brain },
];

// ---------------------------------------------------------------------------
// Timezone list
// ---------------------------------------------------------------------------

const COMMON_TIMEZONES = [
  "UTC",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "Europe/Zurich",
  "Europe/Vienna",
  "Europe/Amsterdam",
  "Europe/Rome",
  "Europe/Madrid",
  "Europe/Stockholm",
  "Europe/Warsaw",
  "Europe/Moscow",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Toronto",
  "America/Sao_Paulo",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Kolkata",
  "Asia/Dubai",
  "Asia/Singapore",
  "Australia/Sydney",
  "Pacific/Auckland",
];

// ---------------------------------------------------------------------------
// Language list
// ---------------------------------------------------------------------------

const LANGUAGES: { code: string; label: string }[] = [
  { code: "en", label: "English" },
  { code: "de", label: "Deutsch" },
  { code: "fr", label: "Fran\u00e7ais" },
  { code: "es", label: "Espa\u00f1ol" },
  { code: "it", label: "Italiano" },
  { code: "pt", label: "Portugu\u00eas" },
  { code: "nl", label: "Nederlands" },
  { code: "pl", label: "Polski" },
  { code: "sv", label: "Svenska" },
  { code: "da", label: "Dansk" },
  { code: "nb", label: "Norsk" },
  { code: "fi", label: "Suomi" },
  { code: "ja", label: "\u65e5\u672c\u8a9e" },
  { code: "zh", label: "\u4e2d\u6587" },
  { code: "ko", label: "\ud55c\uad6d\uc5b4" },
  { code: "ru", label: "\u0420\u0443\u0441\u0441\u043a\u0438\u0439" },
  { code: "ar", label: "\u0627\u0644\u0639\u0631\u0628\u064a\u0629" },
  { code: "tr", label: "T\u00fcrk\u00e7e" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Build a NavItem from a PluginInfo entry using a specific route. */
function pluginToNavItem(plugin: PluginInfo, route: string): NavItem {
  const icon = ICON_MAP[plugin.icon ?? ""] ?? Puzzle;
  return { label: plugin.display_name, to: route, icon };
}

function UserAvatar({ name }: { name: string }) {
  const initials = name
    .split(/\s+/)
    .map((n) => n[0])
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
      {initials || "?"}
    </div>
  );
}

function SectionLabel({ label }: { label: string }) {
  return (
    <p className="px-3 pb-1 pt-4 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/70">
      {label}
    </p>
  );
}

function NavItemLink({
  item,
  onClick,
}: {
  item: NavItem;
  onClick?: () => void;
}) {
  return (
    <NavLink
      to={item.to}
      end={item.to === "/"}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
          "hover:bg-sidebar-accent hover:text-sidebar-foreground",
          isActive
            ? "bg-primary/10 text-primary"
            : "text-muted-foreground",
        )
      }
    >
      <item.icon className="h-4 w-4 shrink-0" />
      {item.label}
    </NavLink>
  );
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

export function Sidebar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { user, logout } = useAuth();
  const { version, releaseUrl } = useVersion();
  const { toast } = useToast();
  const queryClient = useQueryClient();

  // Fetch user settings for plugin visibility and timezone
  const settingsQuery = useGetSettingsApiSettingsGet();
  const settings = unwrapResponse<SettingsResponse>(settingsQuery.data);

  // Fetch available plugins from backend
  const pluginsQuery = useListPluginsApiAiProvidersPluginsGet();
  const plugins = unwrapResponse<PluginInfo[]>(pluginsQuery.data) ?? [];

  const updateMutation = useUpdateSettingsApiSettingsPut();

  // Build dynamic nav items from the plugins API response.
  // Plugins with has_view_page go into the "Plugins" section.
  const viewPluginItems = useMemo(() => {
    const modes = settings?.approval_modes as Record<string, string> | undefined;
    const items: NavItem[] = [];

    for (const plugin of plugins) {
      if (!plugin.has_view_page || !plugin.view_route) continue;

      // Hide plugins whose approval mode is "disabled"
      if (plugin.approval_key && modes) {
        if (modes[plugin.approval_key] === "disabled") continue;
      }

      items.push(pluginToNavItem(plugin, plugin.view_route));
    }

    return items;
  }, [settings, plugins]);

  const displayName = user?.display_name || user?.email || "User";
  const currentTimezone = settings?.timezone ?? "UTC";
  const currentLanguage = settings?.language ?? "en";

  const handleTimezoneChange = useCallback(
    async (tz: string) => {
      try {
        await updateMutation.mutateAsync({ data: { timezone: tz } });
        queryClient.invalidateQueries({
          queryKey: getGetSettingsApiSettingsGetQueryKey(),
        });
      } catch {
        toast({ title: "Error", description: "Failed to update timezone.", variant: "destructive" });
      }
    },
    [updateMutation, queryClient, toast],
  );

  const handleLanguageChange = useCallback(
    async (lang: string) => {
      try {
        await updateMutation.mutateAsync({ data: { language: lang } });
        queryClient.invalidateQueries({
          queryKey: getGetSettingsApiSettingsGetQueryKey(),
        });
      } catch {
        toast({ title: "Error", description: "Failed to update language.", variant: "destructive" });
      }
    },
    [updateMutation, queryClient, toast],
  );

  const closeMobile = useCallback(() => setMobileOpen(false), []);

  // Focus trap + Escape key for mobile sidebar
  const mobileSidebarRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!mobileOpen) return;
    const sidebar = mobileSidebarRef.current;
    if (!sidebar) return;

    // Focus the sidebar when opened
    const firstFocusable = sidebar.querySelector<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    firstFocusable?.focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMobileOpen(false);
        return;
      }
      if (e.key !== "Tab") return;

      const focusables = sidebar.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      );
      if (focusables.length === 0) return;

      const first = focusables[0]!;
      const last = focusables[focusables.length - 1]!;

      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [mobileOpen]);

  const sidebarContent = (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex h-14 items-center px-4">
        <span className="text-lg font-semibold tracking-tight">
          mailassist
        </span>
      </div>

      <Separator />

      {/* Navigation */}
      <ScrollArea className="flex-1 px-3 py-1">
        <nav className="flex flex-col gap-0.5">
          {/* Overview */}
          <SectionLabel label="Overview" />
          {OVERVIEW_ITEMS.map((item) => (
            <NavItemLink key={item.to} item={item} onClick={closeMobile} />
          ))}

          {/* Plugins (dynamic, has_view_page) */}
          <SectionLabel label="Plugins" />
          {viewPluginItems.map((item) => (
            <NavItemLink key={item.to} item={item} onClick={closeMobile} />
          ))}

          {/* Configuration (static items only) */}
          <SectionLabel label="Configuration" />
          {STATIC_CONFIG_ITEMS_TOP.map((item) => (
            <NavItemLink key={item.to} item={item} onClick={closeMobile} />
          ))}
          {STATIC_CONFIG_ITEMS_BOTTOM.map((item) => (
            <NavItemLink key={item.to} item={item} onClick={closeMobile} />
          ))}
        </nav>
      </ScrollArea>

      <Separator />

      {/* User area */}
      <div className="p-3">
        <button
          className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors hover:bg-sidebar-accent"
          onClick={() => setSettingsOpen(true)}
        >
          <UserAvatar name={displayName} />
          <div className="flex-1 truncate text-left">
            <p className="truncate text-sm font-medium">{displayName}</p>
            {user?.email && user.display_name && (
              <p className="truncate text-xs text-muted-foreground">
                {user.email}
              </p>
            )}
          </div>
        </button>

        <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
          <DialogContent className="sm:max-w-sm">
            <DialogHeader>
              <DialogTitle>User Settings</DialogTitle>
              {user?.email && (
                <DialogDescription>{user.email}</DialogDescription>
              )}
            </DialogHeader>

            <div className="space-y-4">
              {/* Timezone selector */}
              <div className="space-y-1.5">
                <label className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                  <Globe className="h-4 w-4" />
                  Timezone
                </label>
                <Select
                  value={currentTimezone}
                  onValueChange={handleTimezoneChange}
                  disabled={updateMutation.isPending}
                >
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {COMMON_TIMEZONES.map((tz) => (
                      <SelectItem key={tz} value={tz} className="text-sm">
                        {tz}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Language selector */}
              <div className="space-y-1.5">
                <label className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
                  <Languages className="h-4 w-4" />
                  Language
                </label>
                <Select
                  value={currentLanguage}
                  onValueChange={handleLanguageChange}
                  disabled={updateMutation.isPending}
                >
                  <SelectTrigger className="h-9 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LANGUAGES.map((lang) => (
                      <SelectItem key={lang.code} value={lang.code} className="text-sm">
                        {lang.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <Separator />

              {version && (
                <p className="text-center text-xs text-muted-foreground">
                  {releaseUrl ? (
                    <a
                      href={releaseUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="transition-colors hover:text-foreground"
                    >
                      v{version}
                    </a>
                  ) : (
                    <>v{version}</>
                  )}
                </p>
              )}

              <AppButton
                icon={<LogOut />}
                label="Log out"
                variant="outline"
                color="destructive"
                className="w-full"
                onClick={logout}
              >
                Log out
              </AppButton>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile toggle */}
      <AppButton
        icon={mobileOpen ? <X /> : <Menu />}
        label="Toggle navigation"
        variant="ghost"
        className="fixed left-4 top-3 z-50 md:hidden"
        onClick={() => setMobileOpen(!mobileOpen)}
        aria-expanded={mobileOpen}
        aria-controls="mobile-sidebar"
      />

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={closeMobile}
          aria-hidden="true"
        />
      )}

      {/* Mobile sidebar */}
      <aside
        ref={mobileSidebarRef}
        id="mobile-sidebar"
        role="navigation"
        aria-label="Main navigation"
        className={cn(
          "fixed inset-y-0 left-0 z-40 w-60 border-r border-sidebar-border bg-sidebar transition-transform duration-200 md:hidden",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {sidebarContent}
      </aside>

      {/* Desktop sidebar */}
      <aside role="navigation" aria-label="Main navigation" className="hidden h-screen w-60 shrink-0 border-r border-sidebar-border bg-sidebar md:block">
        {sidebarContent}
      </aside>
    </>
  );
}
