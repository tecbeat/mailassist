import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/test-utils";
import PluginsPage from "@/pages/plugins";
import {
  createMockPluginList,
  createMockSettings,
  envelope,
} from "@/test/mocks";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api/ai-providers/ai-providers", () => ({
  useListPluginsApiAiProvidersPluginsGet: vi.fn(),
}));

vi.mock("@/services/api/settings/settings", () => ({
  useGetSettingsApiSettingsGet: vi.fn(),
  useUpdateSettingsApiSettingsPut: vi.fn(),
  getGetSettingsApiSettingsGetQueryKey: vi.fn().mockReturnValue(["settings"]),
}));

import { useListPluginsApiAiProvidersPluginsGet } from "@/services/api/ai-providers/ai-providers";
import {
  useGetSettingsApiSettingsGet,
  useUpdateSettingsApiSettingsPut,
} from "@/services/api/settings/settings";

type MockedFn = ReturnType<typeof vi.fn>;

const mockPluginsHook = useListPluginsApiAiProvidersPluginsGet as MockedFn;
const mockSettingsHook = useGetSettingsApiSettingsGet as MockedFn;
const mockUpdateMutation = useUpdateSettingsApiSettingsPut as MockedFn;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

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

describe("PluginsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockPluginsHook.mockReturnValue(querySuccess(createMockPluginList()));
    mockSettingsHook.mockReturnValue(querySuccess(createMockSettings()));
    mockUpdateMutation.mockReturnValue({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
    });
  });

  it("renders the page header", () => {
    render(<PluginsPage />);

    expect(screen.getByText("Plugins")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Enable, disable, and configure AI plugins and the rules engine.",
      ),
    ).toBeInTheDocument();
  });

  it("renders the 'Test Pipeline' button", () => {
    render(<PluginsPage />);

    expect(screen.getByText("Test Pipeline")).toBeInTheDocument();
  });

  it("renders the 'Processing Pipeline' card title", () => {
    render(<PluginsPage />);

    expect(screen.getByText("Processing Pipeline")).toBeInTheDocument();
  });

  it("renders all plugin display names", () => {
    render(<PluginsPage />);

    expect(screen.getByText("Spam Detection")).toBeInTheDocument();
    expect(screen.getByText("Email Summary")).toBeInTheDocument();
    expect(screen.getByText("Labeling")).toBeInTheDocument();
    expect(screen.getByText("Smart Folders")).toBeInTheDocument();
  });

  it("renders plugin descriptions", () => {
    render(<PluginsPage />);

    expect(
      screen.getByText("Detects spam and phishing emails."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Generates a concise summary with key points and urgency level.",
      ),
    ).toBeInTheDocument();
  });

  it("renders approval mode tabs for each plugin", () => {
    render(<PluginsPage />);

    // Each plugin with an approval_key should show Auto / Approval / Aus tabs
    const autoTabs = screen.getAllByText("Auto");
    expect(autoTabs.length).toBeGreaterThanOrEqual(4);

    const approvalTabs = screen.getAllByText("Approval");
    expect(approvalTabs.length).toBeGreaterThanOrEqual(4);
  });

  it("renders information card explaining the three modes", () => {
    render(<PluginsPage />);

    expect(
      screen.getByText(/plugin is disabled and skipped/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/runs automatically without user intervention/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/queued for manual review before execution/),
    ).toBeInTheDocument();
  });

  it("shows skeleton when plugins are loading", () => {
    mockPluginsHook.mockReturnValue(queryLoading());

    const { container } = render(<PluginsPage />);

    const skeletons = container.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  it("shows error card when plugins fail to load", () => {
    mockPluginsHook.mockReturnValue(queryError());

    render(<PluginsPage />);

    expect(
      screen.getByText("Failed to load plugin settings."),
    ).toBeInTheDocument();
  });

  it("renders reorder buttons for each plugin", () => {
    render(<PluginsPage />);

    const upButtons = screen.getAllByLabelText("Move up");
    const downButtons = screen.getAllByLabelText("Move down");

    // 4 plugins = 4 up + 4 down buttons
    expect(upButtons).toHaveLength(4);
    expect(downButtons).toHaveLength(4);
  });
});
