import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, userEvent } from "@/test/test-utils";
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
  useListAllSendersApiContactsSendersGet: vi.fn(),
  useAssignEmailToContactApiContactsContactIdEmailsPost: vi.fn(),
  useRemoveEmailFromContactEndpointApiContactsContactIdEmailsDelete: vi.fn(),
  useListContactMailsApiContactsContactIdMailsGet: vi.fn(),
  useUnlinkContactMailApiContactsContactIdMailsAssignmentIdDelete: vi.fn(),
  getListContactsApiContactsGetQueryKey: vi.fn().mockReturnValue(["/api/contacts"]),
  getGetConfigApiContactsConfigGetQueryKey: vi.fn().mockReturnValue(["/api/contacts/config"]),
  getListAllSendersApiContactsSendersGetQueryKey: vi.fn().mockReturnValue(["/api/contacts/senders"]),
  getListContactMailsApiContactsContactIdMailsGetQueryKey: vi.fn().mockReturnValue(["/api/contacts/mails"]),
}));

import {
  useGetConfigApiContactsConfigGet,
  useTriggerSyncApiContactsSyncPost,
  useUpsertConfigApiContactsConfigPut,
  useTestConfigApiContactsConfigTestPost,
  useListContactsApiContactsGet,
  useListAllSendersApiContactsSendersGet,
  useAssignEmailToContactApiContactsContactIdEmailsPost,
  useRemoveEmailFromContactEndpointApiContactsContactIdEmailsDelete,
  useListContactMailsApiContactsContactIdMailsGet,
  useUnlinkContactMailApiContactsContactIdMailsAssignmentIdDelete,
} from "@/services/api/contacts/contacts";

type MockedFn = ReturnType<typeof vi.fn>;

const mockConfigHook = useGetConfigApiContactsConfigGet as MockedFn;
const mockSyncHook = useTriggerSyncApiContactsSyncPost as MockedFn;
const mockUpsertHook = useUpsertConfigApiContactsConfigPut as MockedFn;
const mockTestHook = useTestConfigApiContactsConfigTestPost as MockedFn;
const mockListContactsHook = useListContactsApiContactsGet as MockedFn;
const mockListSendersHook = useListAllSendersApiContactsSendersGet as MockedFn;
const mockAssignHook = useAssignEmailToContactApiContactsContactIdEmailsPost as MockedFn;
const mockRemoveHook = useRemoveEmailFromContactEndpointApiContactsContactIdEmailsDelete as MockedFn;
const mockListMailsHook = useListContactMailsApiContactsContactIdMailsGet as MockedFn;
const mockUnlinkHook = useUnlinkContactMailApiContactsContactIdMailsAssignmentIdDelete as MockedFn;

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
  mockAssignHook.mockReturnValue(mutationIdle);
  mockRemoveHook.mockReturnValue(mutationIdle);
  mockListMailsHook.mockReturnValue(querySuccess({ items: [], total: 0, page: 1, per_page: 10 }));
  mockUnlinkHook.mockReturnValue(mutationIdle);
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

  it("shows error toast when sync fails", async () => {
    const mutateFn = vi.fn();
    setupDefaults({
      id: "00000000-0000-0000-0000-000000000001",
      carddav_url: "https://dav.example.com",
      address_book: "contacts",
      sync_interval: 60,
      last_sync_at: null,
      is_active: true,
    });
    mockSyncHook.mockReturnValue({ mutate: mutateFn, isPending: false });

    render(<ContactsPage />);

    const btn = screen.getByRole("button", { name: /sync now/i });
    await userEvent.click(btn);

    // Verify mutate was called and extract the onError callback
    expect(mutateFn).toHaveBeenCalledTimes(1);
    const callArgs = mutateFn.mock.calls[0] as [unknown, { onError: () => void }];
    expect(callArgs[1]).toHaveProperty("onError");
    expect(typeof callArgs[1].onError).toBe("function");
  });
});
