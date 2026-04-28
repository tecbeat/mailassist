import { useState } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { useAnimatedNumber } from "@/hooks/use-animated-number";
import {
  ShieldCheck,
  Coins,
  AlertTriangle,
  Inbox,
  BrainCircuit,
  MailX,
  PauseCircle,
} from "lucide-react";

import {
  useGetDashboardStatsApiDashboardStatsGet,
} from "@/services/api/dashboard/dashboard";
import { useListMailAccountsApiMailAccountsGet } from "@/services/api/mail-accounts/mail-accounts";
import { useListProvidersApiAiProvidersGet } from "@/services/api/ai-providers/ai-providers";

import type { DashboardStatsResponse } from "@/types/api/dashboardStatsResponse";
import type { MailAccountResponse } from "@/types/api/mailAccountResponse";
import type { AIProviderResponse } from "@/types/api/aIProviderResponse";

import { PageHeader } from "@/components/layout/page-header";
import { QueryError } from "@/components/query-error";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
} from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { formatNumber, unwrapResponse } from "@/lib/utils";

import type { TimePeriod } from "./dashboard-helpers";
import { StatsSkeletons } from "./dashboard-helpers";
import { DashboardApprovalsSection } from "./dashboard-approvals-section";
import { DashboardFailedMailsSection } from "./dashboard-failed-mails-section";
import { DashboardJobsSection } from "./dashboard-jobs-section";

// ---------------------------------------------------------------------------
// Animated stat value
// ---------------------------------------------------------------------------

function AnimatedStat({ value }: { value: number }) {
  const animated = useAnimatedNumber(value);
  return <>{formatNumber(animated)}</>;
}

// ---------------------------------------------------------------------------
// Dashboard Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  usePageTitle("Dashboard");
  const [period, setPeriod] = useState<TimePeriod>("24h");

  // --- Data fetching ---
  const statsQuery = useGetDashboardStatsApiDashboardStatsGet({
    query: { refetchInterval: 30_000 },
  });
  const stats = unwrapResponse<DashboardStatsResponse>(statsQuery.data);

  const accountsQuery = useListMailAccountsApiMailAccountsGet();
  const accounts = unwrapResponse<MailAccountResponse[]>(accountsQuery.data);

  const providersQuery = useListProvidersApiAiProvidersGet();
  const providers = unwrapResponse<AIProviderResponse[]>(providersQuery.data);

  // Queue is effectively paused when ALL accounts or ALL providers are paused
  const allAccountsPaused =
    (accounts?.length ?? 0) > 0 && accounts!.every((a) => a.is_paused);
  const allProvidersPaused =
    (providers?.length ?? 0) > 0 && providers!.every((p) => p.is_paused);
  const anyProviderPaused =
    (providers?.length ?? 0) > 0 && providers!.some((p) => p.is_paused);

  // --- Stat cards config ---
  const statCards: {
    label: string;
    icon: React.ReactNode;
    base: string;
    todayOnly?: boolean;
    value?: number;
    subtitle?: string;
  }[] = [
    { label: "Processed Mails", icon: <Inbox className="h-4 w-4 text-muted-foreground" />, base: "processed_mails" },
    { label: "Pending Approvals", icon: <ShieldCheck className="h-4 w-4 text-muted-foreground" />, base: "", todayOnly: true, value: stats?.pending_approvals },
    { label: "Tokens Used", icon: <Coins className="h-4 w-4 text-muted-foreground" />, base: "token_usage" },
    { label: "Unhealthy Accounts", icon: <AlertTriangle className="h-4 w-4 text-muted-foreground" />, base: "", todayOnly: true, value: stats?.unhealthy_accounts },
    { label: "AI Provider Issues", icon: <BrainCircuit className="h-4 w-4 text-muted-foreground" />, base: "", todayOnly: true, value: (stats?.unhealthy_ai_providers ?? 0) + (stats?.paused_ai_providers ?? 0), subtitle: stats ? `${stats.unhealthy_ai_providers ?? 0} unhealthy · ${stats.paused_ai_providers ?? 0} paused` : undefined },
    { label: "Failed Mails", icon: <MailX className="h-4 w-4 text-destructive" />, base: "", todayOnly: true, value: stats?.failed_mails },
  ];

  const periodStats: Record<string, Record<TimePeriod, keyof DashboardStatsResponse>> = {
    processed_mails: { "24h": "processed_mails_24h", "7d": "processed_mails_7d", "30d": "processed_mails_30d" },
    token_usage: { "24h": "token_usage_today", "7d": "token_usage_7d", "30d": "token_usage_30d" },
  };

  function resolveValue(card: (typeof statCards)[number]): number {
    if (card.todayOnly && card.value !== undefined) return card.value;
    if (!stats || !card.base) return 0;
    const keyMap = periodStats[card.base];
    if (!keyMap) return 0;
    return (stats[keyMap[period]] as number) ?? 0;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <PageHeader
          title="Dashboard"
          description="Overview of your mailassist activity."
        />
        <Tabs value={period} onValueChange={(v) => setPeriod(v as TimePeriod)}>
          <TabsList>
            <TabsTrigger value="24h">24h</TabsTrigger>
            <TabsTrigger value="7d">7d</TabsTrigger>
            <TabsTrigger value="30d">30d</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {/* Stats cards */}
      {statsQuery.isError ? (
        <QueryError message="Failed to load dashboard stats." onRetry={() => statsQuery.refetch()} />
      ) : statsQuery.isLoading ? (
        <StatsSkeletons />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {statCards.map((card) => (
            <Card key={card.label}>
              <CardHeader className="flex min-h-[3.5rem] flex-row items-center justify-between space-y-0 pb-2">
                <CardDescription className="text-sm font-medium">{card.label}</CardDescription>
                {card.icon}
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold"><AnimatedStat value={resolveValue(card)} /></div>
                {card.subtitle && (
                  <p className="text-xs text-muted-foreground">{card.subtitle}</p>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Queue paused banner */}
      {(allAccountsPaused || allProvidersPaused || anyProviderPaused) && (
        <div className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${
          allAccountsPaused || allProvidersPaused
            ? "border-amber-500/30 bg-amber-500/10"
            : "border-destructive/30 bg-destructive/10"
        }`}>
          <PauseCircle className={`h-5 w-5 shrink-0 mt-0.5 ${
            allAccountsPaused || allProvidersPaused ? "text-amber-600" : "text-destructive"
          }`} />
          <div className="space-y-1">
            <p className={`text-sm font-medium ${
              allAccountsPaused || allProvidersPaused
                ? "text-amber-700 dark:text-amber-400"
                : "text-destructive"
            }`}>
              {allAccountsPaused || allProvidersPaused ? "Queue paused" : "Provider issues"}
            </p>
            <p className="text-xs text-muted-foreground">
              {allAccountsPaused && allProvidersPaused
                ? "All mail accounts and AI providers are paused. No mails will be processed until at least one of each is available."
                : allAccountsPaused
                  ? "All mail accounts are paused. No new mails will be fetched until at least one account is available."
                  : allProvidersPaused
                    ? "All AI providers are paused. Mails will be queued but not processed until at least one provider is available."
                    : `${providers!.filter((p) => p.is_paused).length} of ${providers!.length} AI provider(s) paused. Processing may fail for plugins assigned to paused providers.`}
            </p>
          </div>
        </div>
      )}

      {/* Pending approvals */}
      <DashboardApprovalsSection />

      {/* Failed mails */}
      <DashboardFailedMailsSection />

      {/* Cron jobs + Job queue */}
      <DashboardJobsSection />
    </div>
  );
}
