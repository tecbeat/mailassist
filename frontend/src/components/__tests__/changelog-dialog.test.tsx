import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@/test/test-utils";
import { ChangelogDialog } from "@/components/changelog-dialog";

const MOCK_CHANGELOG = {
  version: "1.2.0",
  since_version: "1.0.0",
  entries: {
    "1.2.0": "### Added\n- New changelog dialog\n- Version display",
    "1.1.0": "### Fixed\n- Bug fix",
  },
};

const MOCK_CHANGELOG_EMPTY = {
  version: "1.2.0",
  since_version: "1.2.0",
  entries: {},
};

const MOCK_CHANGELOG_FIRST_VISIT = {
  version: "1.2.0",
  since_version: null,
  entries: {
    "1.2.0": "### Added\n- New changelog dialog",
  },
};

vi.mock("@/services/client", () => ({
  customInstance: vi.fn(),
}));

import { customInstance } from "@/services/client";
const mockCustomInstance = vi.mocked(customInstance);

describe("ChangelogDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows dialog when server returns entries", async () => {
    mockCustomInstance.mockResolvedValueOnce({ data: MOCK_CHANGELOG });

    render(<ChangelogDialog />);

    await waitFor(() => {
      expect(screen.getByText("What's New")).toBeInTheDocument();
    });
    expect(screen.getByText("Got it")).toBeInTheDocument();
  });

  it("shows version range in description when since_version is set", async () => {
    mockCustomInstance.mockResolvedValueOnce({ data: MOCK_CHANGELOG });

    render(<ChangelogDialog />);

    await waitFor(() => {
      expect(screen.getByText("What's New")).toBeInTheDocument();
    });
    expect(screen.getByText("v1.0.0 → v1.2.0")).toBeInTheDocument();
  });

  it("shows only current version when since_version is null", async () => {
    mockCustomInstance.mockResolvedValueOnce({ data: MOCK_CHANGELOG_FIRST_VISIT });

    render(<ChangelogDialog />);

    await waitFor(() => {
      expect(screen.getByText("What's New")).toBeInTheDocument();
    });
    expect(screen.queryByText(/→/)).not.toBeInTheDocument();
  });

  it("does not show dialog when server returns empty entries", async () => {
    mockCustomInstance.mockResolvedValueOnce({ data: MOCK_CHANGELOG_EMPTY });

    render(<ChangelogDialog />);

    await waitFor(() => {
      expect(mockCustomInstance).toHaveBeenCalled();
    });
    expect(screen.queryByText("What's New")).not.toBeInTheDocument();
  });

  it("calls dismiss endpoint on dismiss", async () => {
    mockCustomInstance.mockResolvedValueOnce({ data: MOCK_CHANGELOG });
    // Mock the dismiss POST call
    mockCustomInstance.mockResolvedValueOnce({ status: "ok" });

    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    render(<ChangelogDialog />);

    await waitFor(() => {
      expect(screen.getByText("Got it")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Got it"));

    expect(mockCustomInstance).toHaveBeenCalledWith("/api/changelog/dismiss", { method: "POST" });
  });

  it("handles API error gracefully without crashing", async () => {
    mockCustomInstance.mockRejectedValueOnce(new Error("Not Found"));

    render(<ChangelogDialog />);

    await waitFor(() => {
      expect(mockCustomInstance).toHaveBeenCalled();
    });

    // No dialog, no crash
    expect(screen.queryByText("What's New")).not.toBeInTheDocument();
  });
});
