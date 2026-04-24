/**
 * Mock data factories for API response types.
 *
 * Each factory returns a valid response object with sensible defaults.
 * Override any field by passing a partial object.
 */

import type { DashboardStatsResponse } from "@/types/api/dashboardStatsResponse";
import type { JobQueueStatusResponse } from "@/types/api/jobQueueStatusResponse";
import type { ApprovalResponse } from "@/types/api/approvalResponse";
import type { ApprovalListResponse } from "@/types/api/approvalListResponse";
import type { PluginInfo } from "@/types/api/pluginInfo";
import type { SettingsResponse } from "@/types/api/settingsResponse";

export function createMockDashboardStats(
  overrides?: Partial<DashboardStatsResponse>,
): DashboardStatsResponse {
  return {
    active_accounts: 2,
    unhealthy_accounts: 0,
    total_accounts: 3,
    pending_approvals: 5,
    actions_24h: 42,
    actions_7d: 180,
    actions_30d: 720,
    processed_mails_24h: 150,
    processed_mails_7d: 800,
    processed_mails_30d: 3200,
    total_rule_matches: 30,
    token_usage_today: 12500,
    token_usage_7d: 65000,
    token_usage_30d: 280000,
    total_ai_providers: 2,
    unhealthy_ai_providers: 0,
    failed_mails: 1,
    ...overrides,
  };
}

export function createMockJobQueueStatus(
  overrides?: Partial<JobQueueStatusResponse>,
): JobQueueStatusResponse {
  return {
    queued: 3,
    in_progress: 1,
    in_progress_jobs: [],
    queued_jobs: [],
    queue_page: 1,
    queue_pages: 1,
    results_stored: 0,
    queued_total: 3,
    in_progress_system: 0,
    completed_total: 500,
    completed_today: 42,
    completed_last_hour: 8,
    failed_total: 1,
    ...overrides,
  };
}

export function createMockApproval(
  overrides?: Partial<ApprovalResponse>,
): ApprovalResponse {
  return {
    id: "a1b2c3d4-0000-0000-0000-000000000001",
    mail_account_id: "acc-0001",
    function_type: "labeling",
    mail_uid: "12345",
    mail_subject: "Meeting Tomorrow",
    mail_from: "alice@example.com",
    proposed_action: { actions: ["add_label:important"], labels: ["important"] },
    ai_reasoning: "The email discusses an upcoming meeting that requires attention.",
    status: "pending",
    created_at: new Date().toISOString(),
    resolved_at: null,
    expires_at: new Date(Date.now() + 7 * 86400 * 1000).toISOString(),
    ...overrides,
  };
}

export function createMockApprovalList(
  items?: ApprovalResponse[],
  overrides?: Partial<Omit<ApprovalListResponse, "items">>,
): ApprovalListResponse {
  const list = items ?? [
    createMockApproval(),
    createMockApproval({
      id: "a1b2c3d4-0000-0000-0000-000000000002",
      function_type: "smart_folder",
      mail_subject: "Invoice #1234",
      mail_from: "billing@corp.com",
      proposed_action: { actions: ["move_to:Finance/Invoices"], folder: "Finance/Invoices" },
      ai_reasoning: "Invoice detected, filed under Finance.",
    }),
    createMockApproval({
      id: "a1b2c3d4-0000-0000-0000-000000000003",
      function_type: "auto_reply",
      mail_subject: "Out of Office?",
      mail_from: "bob@example.com",
      proposed_action: { actions: ["draft_reply"] },
      ai_reasoning: "The sender is asking about availability.",
    }),
  ];
  return {
    items: list,
    total: list.length,
    page: 1,
    per_page: 20,
    pages: 1,
    ...overrides,
  };
}

export function createMockPlugin(
  overrides?: Partial<PluginInfo>,
): PluginInfo {
  return {
    name: "email_summary",
    display_name: "Email Summary",
    description: "Generates a concise summary with key points and urgency level.",
    execution_order: 1,
    default_prompt_template: "Summarize this email.",
    approval_key: "approval_email_summary",
    supports_approval: true,
    ...overrides,
  };
}

export function createMockPluginList(): PluginInfo[] {
  return [
    createMockPlugin({
      name: "spam_detection",
      display_name: "Spam Detection",
      description: "Detects spam and phishing emails.",
      execution_order: 0,
      approval_key: "approval_spam_detection",
    }),
    createMockPlugin(),
    createMockPlugin({
      name: "labeling",
      display_name: "Labeling",
      description: "Applies relevant labels based on content analysis.",
      execution_order: 2,
      approval_key: "approval_labeling",
    }),
    createMockPlugin({
      name: "smart_folder",
      display_name: "Smart Folders",
      description: "Assigns emails to appropriate folders.",
      execution_order: 3,
      approval_key: "approval_smart_folder",
    }),
  ];
}

export function createMockSettings(
  overrides?: Partial<SettingsResponse>,
): SettingsResponse {
  return {
    id: "settings-0001",
    timezone: "Europe/Berlin",
    language: "en",
    default_polling_interval_minutes: 5,
    draft_expiry_hours: 168,
    approval_modes: {
      spam: "auto",
      summary: "auto",
      labeling: "approval",
      smart_folder: "auto",
    },
    plugin_order: null,
    updated_at: new Date().toISOString(),
    max_concurrent_processing: 3,
    ai_timeout_seconds: 120,
    ...overrides,
  };
}

/**
 * Wraps a value in the response envelope that customInstance returns.
 *
 * Orval-generated hooks call customInstance which returns `{ data, status, headers }`.
 * When mocking query data, wrap the payload with this helper so that
 * `unwrapResponse()` works correctly.
 */
export function envelope<T>(data: T): { data: T; status: number; headers: Headers } {
  return { data, status: 200, headers: new Headers() };
}
