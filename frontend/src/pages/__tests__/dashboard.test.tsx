import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/test-utils";
import DashboardPage from "@/pages/dashboard";
import {
  createMockDashboardStats,
  createMockJobQueueStatus,
  createMockApprovalList,
  envelope,
} from "@/test/mocks";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Mock the orval-generated dashboard hooks
vi.mock("@/services/api/dashboard/dashboard", () => ({
  useGetDashboardStatsApiDashboardStatsGet: vi.fn(),
  useGetJobQueueStatusApiDashboardJobsGet: vi.fn(),
  useGetFailedMailsApiDashboardFailedMailsGet: vi.fn(),
  useRetryFailedMailApiDashboardFailedMailsTrackedEmailIdRetryPost: vi.fn().mockReturnValue({ mutate: vi.fn(), isPending: false }),
  useResolveFailedMailApiDashboardFailedMailsTrackedEmailIdResolvePost: vi.fn().mockReturnValue({ mutate: vi.fn(), isPending: false }),
  getGetFailedMailsApiDashboardFailedMailsGetQueryKey: vi.fn().mockReturnValue(["/api/dashboard/failed-mails"]),
  getGetDashboardStatsApiDashboardStatsGetQueryKey: vi.fn().mockReturnValue(["/api/dashboard/stats"]),
  useGetCronJobsApiDashboardCronsGet: vi.fn(),
  useTriggerCronJobApiDashboardCronsCronNameTriggerPost: vi.fn().mockReturnValue({ mutate: vi.fn(), isPending: false }),
  getGetCronJobsApiDashboardCronsGetQueryKey: vi.fn().mockReturnValue(["/api/dashboard/crons"]),
}));

vi.mock("@/services/api/approvals/approvals", () => ({
  useListApprovalsApiApprovalsGet: vi.fn(),
  useApproveActionApiApprovalsApprovalIdApprovePost: vi.fn().mockReturnValue({ mutate: vi.fn(), isPending: false }),
  useRejectActionApiApprovalsApprovalIdRejectPost: vi.fn().mockReturnValue({ mutate: vi.fn(), isPending: false }),
  useEditApprovalApiApprovalsApprovalIdPatch: vi.fn().mockReturnValue({ mutate: vi.fn(), isPending: false }),
  getListApprovalsApiApprovalsGetQueryKey: vi.fn().mockReturnValue(["/api/approvals"]),
}));

vi.mock("@/services/api/mail-accounts/mail-accounts", () => ({
  useListMailAccountsApiMailAccountsGet: vi.fn(),
}));

vi.mock("@/services/api/ai-providers/ai-providers", () => ({
  useListProvidersApiAiProvidersGet: vi.fn(),
}));

// Mock customInstance so useQuery calls in the component don't make real requests.
// The cron and failed-mail queries use customInstance directly via useQuery.
vi.mock("@/services/client", () => ({
  customInstance: vi.fn().mockResolvedValue({ data: null }),
}));

import {
  useGetDashboardStatsApiDashboardStatsGet,
  useGetJobQueueStatusApiDashboardJobsGet,
  useGetFailedMailsApiDashboardFailedMailsGet,
  useGetCronJobsApiDashboardCronsGet,
} from "@/services/api/dashboard/dashboard";
import { useListApprovalsApiApprovalsGet } from "@/services/api/approvals/approvals";
import { useListMailAccountsApiMailAccountsGet } from "@/services/api/mail-accounts/mail-accounts";
import { useListProvidersApiAiProvidersGet } from "@/services/api/ai-providers/ai-providers";

type MockedFn = ReturnType<typeof vi.fn>;

const mockStatsHook = useGetDashboardStatsApiDashboardStatsGet as MockedFn;
const mockJobsHook = useGetJobQueueStatusApiDashboardJobsGet as MockedFn;
const mockFailedMailsHook = useGetFailedMailsApiDashboardFailedMailsGet as MockedFn;
const mockCronJobsHook = useGetCronJobsApiDashboardCronsGet as MockedFn;
const mockApprovalsHook = useListApprovalsApiApprovalsGet as MockedFn;
const mockAccountsHook = useListMailAccountsApiMailAccountsGet as MockedFn;
const mockProvidersHook = useListProvidersApiAiProvidersGet as MockedFn;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Simulate a successful React Query result for a given hook. */
function querySuccess<T>(data: T) {
  return {
    data: envelope(data),
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  };
}

function queryLoading() {
  return {
    data: undefined,
    isLoading: true,
    isError: false,
    error: null,
    refetch: vi.fn(),
  };
}

function queryError() {
  return {
    data: undefined,
    isLoading: false,
    isError: true,
    error: new Error("Network error"),
    refetch: vi.fn(),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    // Default: all hooks succeed
    mockStatsHook.mockReturnValue(querySuccess(createMockDashboardStats()));
    mockJobsHook.mockReturnValue(querySuccess(createMockJobQueueStatus()));
    mockApprovalsHook.mockReturnValue(querySuccess(createMockApprovalList()));
    mockAccountsHook.mockReturnValue(querySuccess([]));
    mockProvidersHook.mockReturnValue(querySuccess([]));
    mockFailedMailsHook.mockReturnValue(querySuccess({ items: [], total: 0, page: 1, per_page: 5, pages: 0 }));
    mockCronJobsHook.mockReturnValue(querySuccess([]));
  });

  it("renders the page header", () => {
    render(<DashboardPage />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(
      screen.getByText("Overview of your mailassist activity."),
    ).toBeInTheDocument();
  });

  it("renders stat cards with data", () => {
    render(<DashboardPage />);

    expect(screen.getByText("Processed Mails")).toBeInTheDocument();
    // "Pending Approvals" appears in both the stat card and the section heading
    expect(screen.getAllByText("Pending Approvals").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Tokens Used")).toBeInTheDocument();
    expect(screen.getByText("Unhealthy Accounts")).toBeInTheDocument();
    expect(screen.getByText("AI Provider Issues")).toBeInTheDocument();
    expect(screen.getByText("Failed Mails")).toBeInTheDocument();
  });

  it("renders stat values from mock data (24h period by default)", () => {
    const stats = createMockDashboardStats({
      processed_mails_24h: 150,
      pending_approvals: 5,
      token_usage_today: 12500,
    });
    mockStatsHook.mockReturnValue(querySuccess(stats));

    render(<DashboardPage />);

    // Processed mails for 24h period
    expect(screen.getByText("150")).toBeInTheDocument();
    // Pending approvals (absolute, not period-based)
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("renders time period tabs (24h, 7d, 30d)", () => {
    render(<DashboardPage />);

    expect(screen.getByText("24h")).toBeInTheDocument();
    expect(screen.getByText("7d")).toBeInTheDocument();
    expect(screen.getByText("30d")).toBeInTheDocument();
  });

  it("shows skeletons when stats are loading", () => {
    mockStatsHook.mockReturnValue(queryLoading());

    const { container } = render(<DashboardPage />);

    // Skeleton elements use the animate-pulse class
    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("shows error card when stats fail to load", () => {
    mockStatsHook.mockReturnValue(queryError());

    render(<DashboardPage />);

    expect(
      screen.getByText("Failed to load dashboard stats."),
    ).toBeInTheDocument();
  });

  it("renders pending approvals section with items", () => {
    render(<DashboardPage />);

    // "Pending Approvals" appears both as stat card title and section heading
    expect(screen.getAllByText("Pending Approvals").length).toBeGreaterThanOrEqual(2);
    // The approval list items from mock data
    expect(screen.getByText("Meeting Tomorrow")).toBeInTheDocument();
    expect(screen.getByText("Invoice #1234")).toBeInTheDocument();
  });

  it("hides approvals section when no pending approvals", () => {
    mockApprovalsHook.mockReturnValue(
      querySuccess(createMockApprovalList([])),
    );

    render(<DashboardPage />);

    // The approvals section returns null when empty, so "Pending Approvals"
    // should only appear in the stat card, not as a section heading
    expect(screen.getAllByText("Pending Approvals")).toHaveLength(1);
  });

  it("renders 'View all' link to approvals page", () => {
    render(<DashboardPage />);

    const viewAllLink = screen.getByText("View all");
    expect(viewAllLink.closest("a")).toHaveAttribute("href", "/approvals");
  });
});
