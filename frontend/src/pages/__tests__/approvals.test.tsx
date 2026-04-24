import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/test-utils";
import ApprovalsPage from "@/pages/approvals";
import {
  createMockApproval,
  createMockApprovalList,
  envelope,
} from "@/test/mocks";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api/approvals/approvals", () => ({
  useListApprovalsApiApprovalsGet: vi.fn(),
  getListApprovalsApiApprovalsGetQueryKey: vi.fn().mockReturnValue(["/api/approvals"]),
  useApproveActionApiApprovalsApprovalIdApprovePost: vi.fn(),
  useRejectActionApiApprovalsApprovalIdRejectPost: vi.fn(),
  useBulkActionApiApprovalsBulkPost: vi.fn(),
  useEditApprovalApiApprovalsApprovalIdPatch: vi.fn(),
}));

// SpamButton makes its own API calls; replace with a simple stub.
vi.mock("@/components/spam-button", () => ({
  SpamButton: () => <button>Spam</button>,
}));

import {
  useListApprovalsApiApprovalsGet,
  useApproveActionApiApprovalsApprovalIdApprovePost,
  useRejectActionApiApprovalsApprovalIdRejectPost,
  useEditApprovalApiApprovalsApprovalIdPatch,
} from "@/services/api/approvals/approvals";

type MockedFn = ReturnType<typeof vi.fn>;

const mockListHook = useListApprovalsApiApprovalsGet as MockedFn;
const mockApproveMutation = useApproveActionApiApprovalsApprovalIdApprovePost as MockedFn;
const mockRejectMutation = useRejectActionApiApprovalsApprovalIdRejectPost as MockedFn;
const mockEditMutation = useEditApprovalApiApprovalsApprovalIdPatch as MockedFn;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function querySuccess<T>(data: T) {
  return {
    data: envelope(data),
    isLoading: false,
    isError: false,
    isFetching: false,
    error: null,
    refetch: vi.fn(),
    dataUpdatedAt: Date.now(),
  };
}

function queryLoading() {
  return {
    data: undefined,
    isLoading: true,
    isError: false,
    isFetching: true,
    error: null,
    refetch: vi.fn(),
    dataUpdatedAt: 0,
  };
}

function queryError() {
  return {
    data: undefined,
    isLoading: false,
    isError: true,
    isFetching: false,
    error: new Error("Network error"),
    refetch: vi.fn(),
    dataUpdatedAt: 0,
  };
}

function mutationIdle() {
  return {
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ApprovalsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockListHook.mockReturnValue(querySuccess(createMockApprovalList()));
    mockApproveMutation.mockReturnValue(mutationIdle());
    mockRejectMutation.mockReturnValue(mutationIdle());
    mockEditMutation.mockReturnValue(mutationIdle());
  });

  it("renders the page header", () => {
    render(<ApprovalsPage />);

    expect(screen.getByText("Pending Approvals")).toBeInTheDocument();
    expect(
      screen.getByText("Review and manage AI-proposed actions on your mail."),
    ).toBeInTheDocument();
  });

  it("renders the approval queue card", () => {
    render(<ApprovalsPage />);

    expect(screen.getByText("Approval Queue")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Review and approve or reject AI-proposed actions on your emails.",
      ),
    ).toBeInTheDocument();
  });

  it("renders status filter tabs", () => {
    render(<ApprovalsPage />);

    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Expired")).toBeInTheDocument();
    expect(screen.getByText("All")).toBeInTheDocument();
  });

  it("renders approval items from mock data", () => {
    render(<ApprovalsPage />);

    // Subjects from the default mock list
    expect(screen.getByText("Meeting Tomorrow")).toBeInTheDocument();
    expect(screen.getByText("Invoice #1234")).toBeInTheDocument();
    expect(screen.getByText("Out of Office?")).toBeInTheDocument();
  });

  it("renders sender information for each approval", () => {
    render(<ApprovalsPage />);

    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByText("billing@corp.com")).toBeInTheDocument();
    expect(screen.getByText("bob@example.com")).toBeInTheDocument();
  });

  it("renders action type badges", () => {
    render(<ApprovalsPage />);

    expect(screen.getByText("Label")).toBeInTheDocument();
    expect(screen.getByText("Smart Folders")).toBeInTheDocument();
    expect(screen.getByText("Auto Reply")).toBeInTheDocument();
  });

  it("renders approve and reject buttons for pending approvals", () => {
    render(<ApprovalsPage />);

    const approveButtons = screen.getAllByLabelText("Approve");
    const rejectButtons = screen.getAllByLabelText("Reject");

    // 3 pending approvals = 3 approve + 3 reject buttons
    expect(approveButtons).toHaveLength(3);
    expect(rejectButtons).toHaveLength(3);
  });

  it("renders AI reasoning when present", () => {
    render(<ApprovalsPage />);

    // AI reasoning is now combined with proposed action in preview text
    expect(
      screen.getAllByText((_content, element) =>
        element?.tagName === "DIV" &&
        (element?.textContent?.includes("The email discusses an upcoming meeting that requires attention.") ?? false),
      ).length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText((_content, element) =>
        element?.tagName === "DIV" &&
        (element?.textContent?.includes("Invoice detected, filed under Finance.") ?? false),
      ).length,
    ).toBeGreaterThan(0);
  });

  it("renders the Refresh button", () => {
    render(<ApprovalsPage />);

    expect(screen.getByText("Refresh")).toBeInTheDocument();
  });

  it("shows skeletons when data is loading", () => {
    mockListHook.mockReturnValue(queryLoading());

    const { container } = render(<ApprovalsPage />);

    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("shows error message when query fails", () => {
    mockListHook.mockReturnValue(queryError());

    render(<ApprovalsPage />);

    expect(
      screen.getByText("Failed to load approvals."),
    ).toBeInTheDocument();
  });

  it("shows empty state when no pending approvals exist", () => {
    mockListHook.mockReturnValue(
      querySuccess(createMockApprovalList([])),
    );

    render(<ApprovalsPage />);

    expect(
      screen.getByText(
        "You're all caught up! No actions are awaiting your review.",
      ),
    ).toBeInTheDocument();
  });

  it("does not render action buttons for non-pending approvals", () => {
    mockListHook.mockReturnValue(
      querySuccess(
        createMockApprovalList([
          createMockApproval({
            id: "approved-1",
            status: "approved",
            mail_subject: "Already Approved",
          }),
        ]),
      ),
    );

    render(<ApprovalsPage />);

    expect(screen.getByText("Already Approved")).toBeInTheDocument();
    expect(screen.queryByLabelText("Approve")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Reject")).not.toBeInTheDocument();
  });

  it("renders status badges for approval items", () => {
    mockListHook.mockReturnValue(
      querySuccess(
        createMockApprovalList([
          createMockApproval({ id: "1", status: "approved", mail_subject: "Approved Email" }),
          createMockApproval({ id: "2", status: "rejected", mail_subject: "Rejected Email" }),
        ]),
      ),
    );

    render(<ApprovalsPage />);

    expect(screen.getByText("approved")).toBeInTheDocument();
    expect(screen.getByText("rejected")).toBeInTheDocument();
  });

  it("renders search input with correct placeholder", () => {
    render(<ApprovalsPage />);

    expect(
      screen.getByPlaceholderText("Search by subject or sender..."),
    ).toBeInTheDocument();
  });
});
