import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/test-utils";
import QueuePage from "@/pages/queue";
import { envelope } from "@/test/mocks";
import type {
  TrackedEmailListResponse,
  TrackedEmailResponse,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api/queue/queue", () => ({
  useListQueueApiQueueGet: vi.fn(),
  getListQueueApiQueueGetQueryKey: vi.fn().mockReturnValue(["/api/queue"]),
  useRetryEmailApiQueueEmailIdRetryPost: vi.fn(),
}));

vi.mock("@/services/api/mail-accounts/mail-accounts", () => ({
  useListMailAccountsApiMailAccountsGet: vi.fn(),
}));

import {
  useListQueueApiQueueGet,
  useRetryEmailApiQueueEmailIdRetryPost,
} from "@/services/api/queue/queue";
import { useListMailAccountsApiMailAccountsGet } from "@/services/api/mail-accounts/mail-accounts";

type MockedFn = ReturnType<typeof vi.fn>;

const mockListHook = useListQueueApiQueueGet as MockedFn;
const mockRetryMutation = useRetryEmailApiQueueEmailIdRetryPost as MockedFn;
const mockAccountsHook = useListMailAccountsApiMailAccountsGet as MockedFn;

// ---------------------------------------------------------------------------
// Factories
// ---------------------------------------------------------------------------

function createMockEmail(overrides?: Partial<TrackedEmailResponse>): TrackedEmailResponse {
  return {
    id: "e1b2c3d4-0000-0000-0000-000000000001",
    mail_uid: "uid-1",
    subject: "Test Email Subject",
    sender: "sender@example.com",
    received_at: new Date().toISOString(),
    status: "queued",
    error_type: null,
    last_error: null,
    plugins_completed: null,
    plugins_failed: null,
    plugins_skipped: null,
    completion_reason: null,
    current_folder: "INBOX",
    mail_account_id: "acc-0001",
    retry_count: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  };
}

function createMockEmailList(
  items?: TrackedEmailResponse[],
  overrides?: Partial<Omit<TrackedEmailListResponse, "items">>,
): TrackedEmailListResponse {
  const list = items ?? [createMockEmail()];
  return {
    items: list,
    total: list.length,
    page: 1,
    per_page: 20,
    pages: 1,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Query state helpers
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

describe("QueuePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockListHook.mockReturnValue(querySuccess(createMockEmailList()));
    mockRetryMutation.mockReturnValue(mutationIdle());
    mockAccountsHook.mockReturnValue(querySuccess([]));
  });

  it("renders the page header", () => {
    render(<QueuePage />);

    expect(screen.getByText("Mail Queue")).toBeInTheDocument();
    expect(
      screen.getByText("Paginated view of all tracked emails and their processing status."),
    ).toBeInTheDocument();
  });

  it("renders the processing queue card", () => {
    render(<QueuePage />);

    expect(screen.getByText("Processing Queue")).toBeInTheDocument();
    expect(
      screen.getByText("All emails discovered by the worker, sorted by last updated."),
    ).toBeInTheDocument();
  });

  it("renders email items from mock data", () => {
    render(<QueuePage />);

    expect(screen.getByText("Test Email Subject")).toBeInTheDocument();
    expect(screen.getByText("sender@example.com")).toBeInTheDocument();
  });

  it("renders status badge for queued email", () => {
    render(<QueuePage />);

    expect(screen.getByText("Queued")).toBeInTheDocument();
  });

  it("renders status badge for failed email", () => {
    mockListHook.mockReturnValue(
      querySuccess(
        createMockEmailList([
          createMockEmail({ status: "failed", last_error: "Connection refused", error_type: "provider_imap" }),
        ]),
      ),
    );

    render(<QueuePage />);

    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("renders status badge for completed email", () => {
    mockListHook.mockReturnValue(
      querySuccess(
        createMockEmailList([
          createMockEmail({ status: "completed", completion_reason: "full_pipeline" }),
        ]),
      ),
    );

    render(<QueuePage />);

    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("renders retry button for failed emails", () => {
    mockListHook.mockReturnValue(
      querySuccess(
        createMockEmailList([
          createMockEmail({ status: "failed", last_error: "Timeout" }),
        ]),
      ),
    );

    render(<QueuePage />);

    expect(screen.getByLabelText("Retry")).toBeInTheDocument();
  });

  it("does not render retry button for non-failed emails", () => {
    mockListHook.mockReturnValue(
      querySuccess(
        createMockEmailList([createMockEmail({ status: "completed" })]),
      ),
    );

    render(<QueuePage />);

    expect(screen.queryByLabelText("Retry")).not.toBeInTheDocument();
  });

  it("renders search input with correct placeholder", () => {
    render(<QueuePage />);

    expect(
      screen.getByPlaceholderText("Search by subject or sender..."),
    ).toBeInTheDocument();
  });

  it("renders Refresh button", () => {
    render(<QueuePage />);

    expect(screen.getByText("Refresh")).toBeInTheDocument();
  });

  it("shows skeletons when data is loading", () => {
    mockListHook.mockReturnValue(queryLoading());

    const { container } = render(<QueuePage />);

    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("shows error message when query fails", () => {
    mockListHook.mockReturnValue(queryError());

    render(<QueuePage />);

    expect(screen.getByText("Failed to load the mail queue.")).toBeInTheDocument();
  });

  it("shows empty state when no emails exist", () => {
    mockListHook.mockReturnValue(
      querySuccess(createMockEmailList([])),
    );

    render(<QueuePage />);

    expect(screen.getByText("No emails in the queue.")).toBeInTheDocument();
  });

  it("renders retry count when greater than zero", () => {
    mockListHook.mockReturnValue(
      querySuccess(
        createMockEmailList([
          createMockEmail({ status: "failed", retry_count: 3 }),
        ]),
      ),
    );

    render(<QueuePage />);

    expect(screen.getByText("3 retries")).toBeInTheDocument();
  });

  it("renders mail_uid as fallback when subject is null", () => {
    mockListHook.mockReturnValue(
      querySuccess(
        createMockEmailList([
          createMockEmail({ subject: null, mail_uid: "uid-fallback-42" }),
        ]),
      ),
    );

    render(<QueuePage />);

    expect(screen.getByText("uid-fallback-42")).toBeInTheDocument();
  });

  it("renders multiple emails", () => {
    mockListHook.mockReturnValue(
      querySuccess(
        createMockEmailList([
          createMockEmail({ id: "1", subject: "First Email" }),
          createMockEmail({ id: "2", subject: "Second Email" }),
          createMockEmail({ id: "3", subject: "Third Email" }),
        ]),
      ),
    );

    render(<QueuePage />);

    expect(screen.getByText("First Email")).toBeInTheDocument();
    expect(screen.getByText("Second Email")).toBeInTheDocument();
    expect(screen.getByText("Third Email")).toBeInTheDocument();
  });
});
