import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@/test/test-utils";
import ContactsPage from "@/pages/contacts/contacts-page";
import { envelope } from "@/test/mocks";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/services/api/contacts/contacts", () => ({
  useGetConfigApiContactsConfigGet: vi.fn(),
  useUpsertConfigApiContactsConfigPut: vi.fn(),
  useTestConfigApiContactsConfigTestPost: vi.fn(),
  useTriggerSyncApiContactsSyncPost: vi.fn(),
  useListContactsApiContactsGet: vi.fn(),
  useListSendersApiContactsSendersGet: vi.fn(),
  getListContactsApiContactsGetQueryKey: vi.fn().mockReturnValue(["/api/contacts"]),
  getGetConfigApiContactsConfigGetQueryKey: vi.fn().mockReturnValue(["/api/contacts/config"]),
}));

import {
  useGetConfigApiContactsConfigGet,
  useTriggerSyncApiContactsSyncPost,
  useUpsertConfigApiContactsConfigPut,
  useTestConfigApiContactsConfigTestPost,
  useListContactsApiContactsGet,
  useListSendersApiContactsSendersGet,
} from "@/services/api/contacts/contacts";

type MockedFn = ReturnType<typeof vi.fn>;

const mockConfigHook = useGetConfigApiContactsConfigGet as MockedFn;
const mockSyncHook = useTriggerSyncApiContactsSyncPost as MockedFn;
const mockUpsertHook = useUpsertConfigApiContactsConfigPut as MockedFn;
const mockTestHook = useTestConfigApiContactsConfigTestPost as MockedFn;
const mockListContactsHook = useListContactsApiContactsGet as MockedFn;
const mockListSendersHook = useListSendersApiContactsSendersGet as MockedFn;

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

const mutationIdle = { mutate: vi.fn(), isPending: false };

function setupDefaults(configData: unknown) {
  mockConfigHook.mockReturnValue(querySuccess(configData));
  mockSyncHook.mockReturnValue(mutationIdle);
  mockUpsertHook.mockReturnValue(mutationIdle);
  mockTestHook.mockReturnValue(mutationIdle);
  mockListContactsHook.mockReturnValue(
    querySuccess({ items: [], total: 0, page: 1, per_page: 50 }),
  );
  mockListSendersHook.mockReturnValue(querySuccess([]));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("Contacts Sync Now button", () => {
  beforeEach(() => vi.clearAllMocks());

  it("disables Sync Now when no CardDAV config exists", () => {
    setupDefaults(null);
    render(<ContactsPage />);

    const btn = screen.getByRole("button", { name: /sync now/i });
    expect(btn).toBeDisabled();
  });

  it("disables Sync Now when config is inactive", () => {
    setupDefaults({
      id: "00000000-0000-0000-0000-000000000001",
      carddav_url: "https://dav.example.com",
      address_book: "contacts",
      sync_interval: 60,
      last_sync_at: null,
      is_active: false,
    });
    render(<ContactsPage />);

    const btn = screen.getByRole("button", { name: /sync now/i });
    expect(btn).toBeDisabled();
  });

  it("enables Sync Now when config is active", () => {
    setupDefaults({
      id: "00000000-0000-0000-0000-000000000001",
      carddav_url: "https://dav.example.com",
      address_book: "contacts",
      sync_interval: 60,
      last_sync_at: null,
      is_active: true,
    });
    render(<ContactsPage />);

    const btn = screen.getByRole("button", { name: /sync now/i });
    expect(btn).toBeEnabled();
  });
});
