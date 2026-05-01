import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@/test/test-utils";
import { ChangelogDialog } from "@/components/changelog-dialog";

const MOCK_CHANGELOG = {
  version: "1.2.0",
  entries: {
    "1.2.0": "### Added\n- New changelog dialog\n- Version display",
  },
};

vi.mock("@/services/client", () => ({
  customInstance: vi.fn(),
}));

import { customInstance } from "@/services/client";
const mockCustomInstance = vi.mocked(customInstance);

describe("ChangelogDialog", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  it("shows dialog when version differs from localStorage", async () => {
    mockCustomInstance.mockResolvedValueOnce({ data: MOCK_CHANGELOG });

    render(<ChangelogDialog />);

    await waitFor(() => {
      expect(screen.getByText("What's New")).toBeInTheDocument();
    });
    expect(screen.getByText(/v1\.2\.0/)).toBeInTheDocument();
    expect(screen.getByText("Okay, Let's Go!")).toBeInTheDocument();
  });

  it("does not show dialog when localStorage version matches", async () => {
    localStorage.setItem("mailassist-last-seen-version", "1.2.0");
    mockCustomInstance.mockResolvedValueOnce({ data: MOCK_CHANGELOG });

    render(<ChangelogDialog />);

    // Wait for the fetch to complete, then verify no dialog
    await waitFor(() => {
      expect(mockCustomInstance).toHaveBeenCalled();
    });
    expect(screen.queryByText("What's New")).not.toBeInTheDocument();
  });

  it("saves version to localStorage on dismiss", async () => {
    mockCustomInstance.mockResolvedValueOnce({ data: MOCK_CHANGELOG });

    const { userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    render(<ChangelogDialog />);

    await waitFor(() => {
      expect(screen.getByText("Okay, Let's Go!")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Okay, Let's Go!"));

    expect(localStorage.getItem("mailassist-last-seen-version")).toBe("1.2.0");
  });

  it("handles API error gracefully without crashing", async () => {
    mockCustomInstance.mockRejectedValueOnce(new Error("Not Found"));

    render(<ChangelogDialog />);

    // Wait for the fetch to settle
    await waitFor(() => {
      expect(mockCustomInstance).toHaveBeenCalled();
    });

    // No dialog, no crash
    expect(screen.queryByText("What's New")).not.toBeInTheDocument();
  });
});
